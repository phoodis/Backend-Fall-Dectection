from flask import Blueprint, request, jsonify
from app import db
from app.models.thai_frat_assessment import ThaiFratAssessment, AssessmentShare
from app.models.user import User, UserRole
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
import pytz

tz = pytz.timezone('Asia/Bangkok')
bp = Blueprint('thai_frat', __name__, url_prefix='/api/thai-frat')

def get_current_user():
    """Helper function to get current user"""
    current_user_id = int(get_jwt_identity())
    return User.query.get(current_user_id)

@bp.route('/assessments', methods=['GET'])
@jwt_required()
def get_assessments():
    """Get all assessments for the current user including shared ones"""
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404
    
    # Admin can see all assessments, users see only their own and shared ones
    if current_user.is_admin():
        own_assessments = ThaiFratAssessment.query.all()
        # For admin, show all assessments with owner information
        own_assessments_data = []
        for assessment in own_assessments:
            data = assessment.to_dict()
            creator = User.query.get(assessment.creator_id)
            data['creator'] = {
                'id': assessment.creator_id,
                'username': creator.username if creator else 'Unknown'
            }
            own_assessments_data.append(data)
        
        result = {
            'own_assessments': own_assessments_data,
            'shared_assessments': []  # Admin doesn't need shared assessments view
        }
    else:
        own_assessments = ThaiFratAssessment.query.filter_by(creator_id=current_user.id).all()
        
        shared_assessments = db.session.query(ThaiFratAssessment, AssessmentShare).join(
            AssessmentShare, ThaiFratAssessment.id == AssessmentShare.assessment_id
        ).filter(AssessmentShare.shared_with_username == current_user.username).all()
        
        result = {
            'own_assessments': [assessment.to_dict() for assessment in own_assessments],
            'shared_assessments': [
                {
                    'share_info': share.to_dict(),
                    'assessment': assessment.to_dict(include_personal_info=share.include_personal_info)
                }
                for assessment, share in shared_assessments
            ]
        }
    
    return jsonify(result)

@bp.route('/assessments', methods=['POST'])
@jwt_required()
def create_assessment():
    """Create a new Thai-FRAT assessment - Both admin and users can create"""
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404
    
    data = request.get_json()
    
    # Validate required fields
    required_fields = ['name', 'q1', 'q2', 'q3', 'q4', 'q5', 'q6']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400
    
    # Calculate total score
    total_score = sum([
        data['q1'], data['q2'], data['q3'], 
        data['q4'], data['q5'], data['q6']
    ])
    
    # Determine creator (admin can create on behalf of others)
    creator_id = current_user.id
    if current_user.is_admin() and 'creator_id' in data:
        target_user = User.query.get(data['creator_id'])
        if target_user:
            creator_id = data['creator_id']
    
    # Create assessment
    assessment = ThaiFratAssessment(
        creator_id=creator_id,
        name=data['name'],
        tel=data.get('tel', ''),
        province=data.get('province', ''),
        pdpa_consent=data.get('pdpa_consent', False),
        q1_score=data['q1'],
        q2_score=data['q2'],
        q3_score=data['q3'],
        q4_score=data['q4'],
        q5_score=data['q5'],
        q6_score=data['q6'],
        total_score=total_score,
        risk_level=''  # Will be calculated
    )
    
    # Calculate and set risk level
    assessment.risk_level = assessment.calculate_risk_level()
    
    # Set answer values based on scores (automatically populate descriptions)
    assessment.set_answer_values_from_scores()
    
    # Override with provided values if they exist
    if 'q1_value' in data:
        assessment.q1_value = data['q1_value']
    if 'q2_value' in data:
        assessment.q2_value = data['q2_value']
    if 'q3_value' in data:
        assessment.q3_value = data['q3_value']
    if 'q4_value' in data:
        assessment.q4_value = data['q4_value']
    if 'q5_value' in data:
        assessment.q5_value = data['q5_value']
    if 'q6_value' in data:
        assessment.q6_value = data['q6_value']
    
    try:
        db.session.add(assessment)
        db.session.commit()
        
        response_data = {
            'message': 'Assessment created successfully',
            'assessment': assessment.to_dict()
        }
        
        # Add creator info if admin created on behalf of someone
        if current_user.is_admin() and creator_id != current_user.id:
            creator = User.query.get(creator_id)
            response_data['created_for'] = {
                'id': creator_id,
                'username': creator.username if creator else 'Unknown'
            }
        
        return jsonify(response_data), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to create assessment: {str(e)}'}), 500

@bp.route('/assessments/<int:assessment_id>', methods=['GET'])
@jwt_required()
def get_assessment(assessment_id):
    """Get a specific assessment"""
    current_user_id = int(get_jwt_identity())  # Ensure integer
    current_user = User.query.get(current_user_id)
    
    assessment = ThaiFratAssessment.query.get_or_404(assessment_id)
    
    # Check if user owns the assessment or has access to it
    if assessment.creator_id == current_user_id:
        return jsonify({'assessment': assessment.to_dict()})
    
    # Check if assessment is shared with this user
    share = AssessmentShare.query.filter_by(
        assessment_id=assessment_id,
        shared_with_username=current_user.username
    ).first()
    
    if share:
        return jsonify({
            'assessment': assessment.to_dict(include_personal_info=share.include_personal_info),
            'share_info': share.to_dict()
        })
    
    return jsonify({'error': 'Assessment not found or access denied'}), 404

@bp.route('/assessments/<int:assessment_id>', methods=['PUT'])
@jwt_required()
def update_assessment(assessment_id):
    """Update an assessment (only by owner)"""
    current_user_id = int(get_jwt_identity())  # Ensure integer
    assessment = ThaiFratAssessment.query.get_or_404(assessment_id)
    
    # Check ownership
    if assessment.creator_id != current_user_id:
        return jsonify({'error': 'Access denied. You can only update your own assessments.'}), 403
    
    data = request.get_json()
    
    try:
        # Update fields if provided
        if 'name' in data:
            assessment.name = data['name']
        if 'tel' in data:
            assessment.tel = data['tel']
        if 'province' in data:
            assessment.province = data['province']
        if 'pdpa_consent' in data:
            assessment.pdpa_consent = data['pdpa_consent']
        
        # Update scores if provided
        scores_updated = False
        if 'q1' in data:
            assessment.q1_score = data['q1']
            scores_updated = True
        if 'q2' in data:
            assessment.q2_score = data['q2']
            scores_updated = True
        if 'q3' in data:
            assessment.q3_score = data['q3']
            scores_updated = True
        if 'q4' in data:
            assessment.q4_score = data['q4']
            scores_updated = True
        if 'q5' in data:
            assessment.q5_score = data['q5']
            scores_updated = True
        if 'q6' in data:
            assessment.q6_score = data['q6']
            scores_updated = True
        
        # Update values if provided
        if 'q1_value' in data:
            assessment.q1_value = data['q1_value']
        if 'q2_value' in data:
            assessment.q2_value = data['q2_value']
        if 'q3_value' in data:
            assessment.q3_value = data['q3_value']
        if 'q4_value' in data:
            assessment.q4_value = data['q4_value']
        if 'q5_value' in data:
            assessment.q5_value = data['q5_value']
        if 'q6_value' in data:
            assessment.q6_value = data['q6_value']
        
        # Recalculate total score and risk level if scores were updated
        if scores_updated:
            assessment.total_score = sum([
                assessment.q1_score, assessment.q2_score, assessment.q3_score,
                assessment.q4_score, assessment.q5_score, assessment.q6_score
            ])
            assessment.risk_level = assessment.calculate_risk_level()
            
            # Auto-populate values from scores if values weren't explicitly provided
            if 'q1_value' not in data and 'q1' in data:
                assessment.q1_value = assessment.get_answer_description('q1', assessment.q1_score)
            if 'q2_value' not in data and 'q2' in data:
                assessment.q2_value = assessment.get_answer_description('q2', assessment.q2_score)
            if 'q3_value' not in data and 'q3' in data:
                assessment.q3_value = assessment.get_answer_description('q3', assessment.q3_score)
            if 'q4_value' not in data and 'q4' in data:
                assessment.q4_value = assessment.get_answer_description('q4', assessment.q4_score)
            if 'q5_value' not in data and 'q5' in data:
                assessment.q5_value = assessment.get_answer_description('q5', assessment.q5_score)
            if 'q6_value' not in data and 'q6' in data:
                assessment.q6_value = assessment.get_answer_description('q6', assessment.q6_score)
        
        assessment.updated_at = datetime.now(tz)
        db.session.commit()
        
        return jsonify({
            'message': 'Assessment updated successfully',
            'assessment': assessment.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update assessment: {str(e)}'}), 500

@bp.route('/assessments/<int:assessment_id>', methods=['DELETE'])
@jwt_required()
def delete_assessment(assessment_id):
    """Delete an assessment (only by owner)"""
    current_user_id = int(get_jwt_identity())  # Ensure integer
    assessment = ThaiFratAssessment.query.get_or_404(assessment_id)
    
    # Check ownership
    if assessment.creator_id != current_user_id:
        return jsonify({'error': 'Access denied. You can only delete your own assessments.'}), 403
    
    try:
        # Delete associated shares (will be handled by cascade)
        db.session.delete(assessment)
        db.session.commit()
        return jsonify({'message': 'Assessment deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to delete assessment: {str(e)}'}), 500

@bp.route('/assessments/<int:assessment_id>/share', methods=['POST'])
@jwt_required()
def share_assessment(assessment_id):
    """Share an assessment with another user"""
    current_user_id = int(get_jwt_identity())  # Ensure integer
    assessment = ThaiFratAssessment.query.get_or_404(assessment_id)
    
    # Check ownership
    if assessment.creator_id != current_user_id:
        return jsonify({'error': 'Access denied. You can only share your own assessments.'}), 403
    
    data = request.get_json()
    
    if 'username' not in data:
        return jsonify({'error': 'Username is required'}), 400
    
    target_username = data['username']
    include_personal_info = data.get('include_personal_info', False)
    
    # Check if target user exists
    target_user = User.query.filter_by(username=target_username).first()
    if not target_user:
        return jsonify({'error': f'User "{target_username}" not found'}), 404
    
    # Check if already shared with this user
    existing_share = AssessmentShare.query.filter_by(
        assessment_id=assessment_id,
        shared_with_username=target_username
    ).first()
    
    if existing_share:
        # Update existing share
        existing_share.include_personal_info = include_personal_info
        message = f'Assessment sharing updated for user "{target_username}"'
    else:
        # Create new share
        share = AssessmentShare(
            assessment_id=assessment_id,
            shared_with_username=target_username,
            shared_by_id=current_user_id,
            include_personal_info=include_personal_info
        )
        db.session.add(share)
        message = f'Assessment shared with user "{target_username}"'
    
    try:
        db.session.commit()
        return jsonify({'message': message}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to share assessment: {str(e)}'}), 500

@bp.route('/question-options', methods=['GET'])
def get_question_options():
    """Get all question options and their corresponding scores"""
    # Create a temporary instance to access the question answers
    temp_assessment = ThaiFratAssessment()
    question_options = temp_assessment.get_question_answers()
    
    # Format the response with question titles
    formatted_options = {
        'q1': {
            'title': 'ประวัติการพลัดตกหกล้ม: มีการพลัดตกหกล้มระหว่าง อยู่รักษา หรือ ตกหกล้ม ภายใน 3 เดือนที่ผ่านมา (History of falling; immediate or within 3 months)?',
            'options': [
                {'score': 25, 'text': 'เคย (25 คะแนน)'},
                {'score': 0, 'text': 'ไม่เคย (0 คะแนน)'}
            ]
        },
        'q2': {
            'title': 'มีการวินิจฉัยโรคมากกว่า 1 รายการ (Secondary diagnosis)?',
            'options': [
                {'score': 0, 'text': 'ไม่ได้ (0 คะแนน)'},
                {'score': 15, 'text': 'ได้ (15 คะแนน)'}
            ]
        },
        'q3': {
            'title': 'การช่วยในการเคลื่อนย้าย (Ambulatory aid)?',
            'options': [
                {'score': 0, 'text': 'เดินได้เองโดยไม่ใช้อุปกรณ์ช่วย / ใช้รถเข็นนั่ง / นอนพักบนเตียงโดยไม่ลุกจากเตียง (Bed rest) / บุคลากรช่วย (Nurse assist) (0 คะแนน)'},
                {'score': 15, 'text': 'ไม้ค้ำยัน (Crutches) / ไม้เท้า (Cane) / Walker frame (15 คะแนน)'},
                {'score': 30, 'text': 'เดินโดยการยึดเกาะไปตามเตียง โต๊ะ เก้าอี้ (Furniture) (30 คะแนน)'}
            ]
        },
        'q4': {
            'title': 'ให้สารละลายทางหลอดเลือดดำ (IV) / ใช้ Heparin lock',
            'options': [
                {'score': 25, 'text': 'ใช่ (25 คะแนน)'},
                {'score': 0, 'text': 'ไม่มี (0 คะแนน)'}
            ]
        },
        'q5': {
            'title': 'การเดิน (Gait) / การเคลื่อนย้าย (Transferring)',
            'options': [
                {'score': 0, 'text': 'ปกติ (Normal) / นอนพักบนเตียงโดยไม่ลุกจากเตียง (Bed rest) / ไม่เคลื่อนไหว (Immobile) (0 คะแนน)'},
                {'score': 10, 'text': 'อ่อนแรงเล็กน้อยหรืออ่อนเพลีย (Weak) / เดินก้มตัวแต่ศีรษะตั้งตรงได้ขณะกำลังเดินโดยไม่เสียการทรงตัว / เดินก้าวสั้นและลากเท้า (10 คะแนน)'},
                {'score': 20, 'text': 'มีความพร่อง (Impaired) เช่น ลุกจากเก้าอี้ด้วยความลำบาก พยายามจะลุกจากเก้าอี้ด้วยการใช้มือและแขนยันตัว หรือลุกด้วยความพยายามอยู่หลายครั้ง เดินก้มศีรษะและตามองพื้น เดินโดยต้องมีคนช่วยพยุงหรือใช้อุปกรณ์ช่วยเดิน ไม่สามารถเดินได้โดยปราศจากการช่วยเหลือ (20 คะแนน)'}
            ]
        },
        'q6': {
            'title': 'สภาพจิตใจ',
            'options': [
                {'score': 0, 'text': 'รับรู้บุคคล กาลเวลา และสถานที่ได้ด้วยตนเอง (Oriented to own ability) (0 คะแนน)'},
                {'score': 15, 'text': 'ตอบสนองไม่ตรงกับความเป็นจริง ประเมินความสามารถของตนเองเกินกว่าที่ทำได้และลืมคิดถึงข้อจำกัดที่มีอยู่ (Forgets limitations) (15 คะแนน)'}
            ]
        }
    }
    
    return jsonify({
        'question_options': formatted_options,
        'risk_levels': {
            'low': {'range': '0-24', 'description': 'ไม่มีความเสี่ยง หรือมีความเสี่ยงต่ำต่อการลื่น/ตก/หกล้ม'},
            'medium': {'range': '25-50', 'description': 'มีความเสี่ยงต่อการลื่น/ตก/หกล้ม'},
            'high': {'range': '≥51', 'description': 'มีความเสี่ยงสูงต่อการลื่น/ตก/หกล้ม (ควรเฝ้าระวังและปรับสภาพแวดล้อม)'}
        }
    })
@bp.route('/assessments/<int:assessment_id>/share/<username>', methods=['DELETE'])
@jwt_required()
def unshare_assessment(assessment_id, username):
    """Remove sharing for a specific user"""
    current_user_id = int(get_jwt_identity())  # Ensure integer
    assessment = ThaiFratAssessment.query.get_or_404(assessment_id)
    
    # Check ownership
    if assessment.creator_id != current_user_id:
        return jsonify({'error': 'Access denied. You can only manage sharing for your own assessments.'}), 403
    
    share = AssessmentShare.query.filter_by(
        assessment_id=assessment_id,
        shared_with_username=username
    ).first()
    
    if not share:
        return jsonify({'error': f'Assessment is not shared with user "{username}"'}), 404
    
    try:
        db.session.delete(share)
        db.session.commit()
        return jsonify({'message': f'Assessment sharing removed for user "{username}"'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to remove sharing: {str(e)}'}), 500

@bp.route('/assessments/<int:assessment_id>/shares', methods=['GET'])
@jwt_required()
def get_assessment_shares(assessment_id):
    """Get all users this assessment is shared with"""
    current_user_id = int(get_jwt_identity())  # Ensure integer
    assessment = ThaiFratAssessment.query.get_or_404(assessment_id)
    
    # Check ownership
    if assessment.creator_id != current_user_id:
        return jsonify({'error': 'Access denied. You can only view sharing for your own assessments.'}), 403
    
    shares = AssessmentShare.query.filter_by(assessment_id=assessment_id).all()
    
    return jsonify({
        'assessment_id': assessment_id,
        'shares': [share.to_dict() for share in shares]
    })
