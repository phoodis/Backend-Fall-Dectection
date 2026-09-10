from flask import Blueprint, request, jsonify
from app import db
from app.models.user import User, UserRole
from app.models.camera import Camera
from app.models.thai_frat_assessment import ThaiFratAssessment
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.logging_service import save_system_log

bp = Blueprint('admin', __name__, url_prefix='/api/admin')

def get_current_user():
    """Helper function to get current user"""
    current_user_id = int(get_jwt_identity())
    return User.query.get(current_user_id)

def admin_required(f):
    """Decorator to require admin role"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            current_user = get_current_user()
            if not current_user:
                return jsonify({'error': 'User not found'}), 404
            
            if not current_user.is_admin():
                return jsonify({'error': 'Admin access required'}), 403
            
            return f(*args, **kwargs)
        except Exception as e:
            return jsonify({'error': f'Authorization failed: {str(e)}'}), 500
    
    return decorated_function

@bp.route('/users', methods=['GET'])
@jwt_required()
@admin_required
def list_users():
    """List all users (Admin only)"""
    users = User.query.all()
    user_list = []
    
    for user in users:
        camera_count = Camera.query.filter_by(user_id=user.id).count()
        active_cameras = Camera.query.filter_by(user_id=user.id, is_active=True).count()
        assessment_count = ThaiFratAssessment.query.filter_by(creator_id=user.id).count()
        
        user_data = user.to_dict()
        user_data['stats'] = {
            'total_cameras': camera_count,
            'active_cameras': active_cameras,
            'total_assessments': assessment_count
        }
        user_list.append(user_data)
    
    return jsonify({
        'users': user_list,
        'total_count': len(users)
    })

@bp.route('/users', methods=['POST'])
@jwt_required()
@admin_required
def create_user():
    """Create a new user (Admin only)"""
    current_user = get_current_user()
    data = request.get_json()
    
    username = data.get('username')
    password = data.get('password')
    role = data.get('role', 'user')
    
    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400
    
    if User.query.filter_by(username=username).first():
        return jsonify({'error': f'Username "{username}" already exists'}), 409
    
    # Convert role string to enum
    try:
        user_role = UserRole.ADMIN if role.lower() == 'admin' else UserRole.USER
    except:
        user_role = UserRole.USER
    
    user = User(username=username, role=user_role)
    user.telegram_chat_id = data.get('telegram_chat_id')  # ✅ เพิ่มตรงนี้
    user.set_password(password)
    
    try:
        db.session.add(user)
        db.session.commit()
        save_system_log('INFO', f'User created by admin: {username} with role: {user_role.value}', 'USER_MANAGEMENT', current_user.id)

        return jsonify({
            'message': f'User "{username}" created successfully',
            'user': user.to_dict()
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to create user: {str(e)}'}), 500

@bp.route('/users/<int:user_id>', methods=['PUT'])
@jwt_required()
@admin_required
def update_user(user_id):
    """Update a user (Admin only)"""
    current_user = get_current_user()
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    
    # Don't allow admin to change their own role to prevent lockout
    if user.id == current_user.id and 'role' in data:
        return jsonify({'error': 'Cannot change your own role'}), 400
    
    # Update username if provided
    if 'username' in data:
        if User.query.filter(User.username == data['username'], User.id != user_id).first():
            return jsonify({'error': f'Username "{data["username"]}" already exists'}), 409
        user.username = data['username']
    
    # Update password if provided
    if 'password' in data:
        user.set_password(data['password'])
    
    # Update role if provided
    if 'role' in data:
        try:
            user.role = UserRole.ADMIN if data['role'].lower() == 'admin' else UserRole.USER
        except:
            user.role = UserRole.USER

    # Update telegram_chat_id
    if 'telegram_chat_id' in data:
        raw_chat_id = data['telegram_chat_id']
        user.telegram_chat_id = raw_chat_id
    
    try:
        db.session.commit()
        save_system_log('INFO', f'User updated by admin: {user.username}', 'USER_MANAGEMENT', current_user.id)
        
        return jsonify({
            'message': f'User "{user.username}" updated successfully',
            'user': user.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update user: {str(e)}'}), 500

@bp.route('/users/<int:user_id>', methods=['DELETE'])
@jwt_required()
@admin_required
def delete_user(user_id):
    """Delete a user (Admin only)"""
    current_user = get_current_user()
    user = User.query.get_or_404(user_id)
    
    # Don't allow admin to delete themselves
    if user.id == current_user.id:
        return jsonify({'error': 'Cannot delete your own account'}), 400
    
    # Check if user has active cameras
    active_cameras = Camera.query.filter_by(user_id=user_id, is_active=True).count()
    if active_cameras > 0:
        return jsonify({'error': f'Cannot delete user with {active_cameras} active cameras. Please stop all cameras first.'}), 400
    
    username = user.username
    
    try:
        # Delete user's cameras and assessments (cascade should handle this)
        db.session.delete(user)
        db.session.commit()
        save_system_log('INFO', f'User deleted by admin: {username}', 'USER_MANAGEMENT', current_user.id)
        
        return jsonify({'message': f'User "{username}" deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to delete user: {str(e)}'}), 500

@bp.route('/users/<int:user_id>', methods=['GET'])
@jwt_required()
@admin_required
def get_user(user_id):
    """Get detailed user information (Admin only)"""
    user = User.query.get_or_404(user_id)
    
    cameras = Camera.query.filter_by(user_id=user_id).all()
    assessments = ThaiFratAssessment.query.filter_by(creator_id=user_id).all()
    
    user_data = user.to_dict()
        
    user_data['cameras'] = [
        {
            'id': c.id,
            'name': c.name,
            'room_name': c.room_name,
            'detection_type': c.detection_type,
            'is_active': c.is_active
        } for c in cameras
    ]
    user_data['assessments'] = [
        {
            'id': a.id,
            'name': a.name,
            'total_score': a.total_score,
            'risk_level': a.risk_level,
            'created_at': a.created_at.isoformat() if a.created_at else None
        } for a in assessments
    ]
    user_data['stats'] = {
        'total_cameras': len(cameras),
        'active_cameras': sum(1 for c in cameras if c.is_active),
        'total_assessments': len(assessments)
    }
    
    return jsonify({'user': user_data})

@bp.route('/dashboard', methods=['GET'])
@jwt_required()
@admin_required
def admin_dashboard():
    """Get admin dashboard statistics"""
    total_users = User.query.count()
    admin_users = User.query.filter_by(role=UserRole.ADMIN).count()
    regular_users = User.query.filter_by(role=UserRole.USER).count()
    
    total_cameras = Camera.query.count()
    active_cameras = Camera.query.filter_by(is_active=True).count()
    
    total_assessments = ThaiFratAssessment.query.count()
    
    return jsonify({
        'users': {
            'total': total_users,
            'admins': admin_users,
            'regular_users': regular_users
        },
        'cameras': {
            'total': total_cameras,
            'active': active_cameras,
            'inactive': total_cameras - active_cameras
        },
        'assessments': {
            'total': total_assessments
        }
    })
