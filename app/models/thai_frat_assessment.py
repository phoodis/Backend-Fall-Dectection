from app import db
from datetime import datetime
import pytz
import json

tz = pytz.timezone('Asia/Bangkok')

class ThaiFratAssessment(db.Model):
    __tablename__ = 'thai_frat_assessments'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # User information
    creator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Personal information
    name = db.Column(db.String(100), nullable=False)
    tel = db.Column(db.String(20), nullable=True)
    province = db.Column(db.String(100), nullable=True)
    pdpa_consent = db.Column(db.Boolean, default=False)
    
    # Assessment answers - store both scores and values
    q1_score = db.Column(db.Integer, nullable=False)  # History of falling
    q1_value = db.Column(db.Text, nullable=True)      # Answer description
    q2_score = db.Column(db.Integer, nullable=False)  # Secondary diagnosis
    q2_value = db.Column(db.Text, nullable=True)      # Answer description
    q3_score = db.Column(db.Integer, nullable=False)  # Ambulatory aid
    q3_value = db.Column(db.Text, nullable=True)      # Answer description
    q4_score = db.Column(db.Integer, nullable=False)  # IV/Heparin lock
    q4_value = db.Column(db.Text, nullable=True)      # Answer description
    q5_score = db.Column(db.Integer, nullable=False)  # Gait/Transferring
    q5_value = db.Column(db.Text, nullable=True)      # Answer description
    q6_score = db.Column(db.Integer, nullable=False)  # Mental state
    q6_value = db.Column(db.Text, nullable=True)      # Answer description
    
    # Calculated results
    total_score = db.Column(db.Integer, nullable=False)
    risk_level = db.Column(db.String(20), nullable=False)  # 'low', 'medium', 'high'
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(tz))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(tz), onupdate=lambda: datetime.now(tz))
    
    # Relationships
    creator = db.relationship('User', backref=db.backref('assessments', lazy=True))
    
    def calculate_risk_level(self):
        """Calculate risk level based on total score"""
        if self.total_score <= 24:
            return 'low'
        elif self.total_score <= 50:
            return 'medium'
        else:
            return 'high'
    
    def get_question_answers(self):
        """Get predefined answer options for each question"""
        return {
            'q1': {
                25: 'เคย',
                0: 'ไม่เคย'
            },
            'q2': {
                0: 'ไม่ได้',
                15: 'ได้'
            },
            'q3': {
                0: 'เดินได้เองโดยไม่ใช้อุปกรณ์ช่วย / ใช้รถเข็นนั่ง / นอนพักบนเตียงโดยไม่ลุกจากเตียง (Bed rest) / บุคลากรช่วย (Nurse assist)',
                15: 'ไม้ค้ำยัน (Crutches) / ไม้เท้า (Cane) / Walker frame',
                30: 'เดินโดยการยึดเกาะไปตามเตียง โต๊ะ เก้าอี้ (Furniture)'
            },
            'q4': {
                25: 'ใช่',
                0: 'ไม่มี'
            },
            'q5': {
                0: 'ปกติ (Normal) / นอนพักบนเตียงโดยไม่ลุกจากเตียง (Bed rest) / ไม่เคลื่อนไหว (Immobile)',
                10: 'อ่อนแรงเล็กน้อยหรืออ่อนเพลีย (Weak) / เดินก้มตัวแต่ศีรษะตั้งตรงได้ขณะกำลังเดินโดยไม่เสียการทรงตัว / เดินก้าวสั้นและลากเท้า',
                20: 'มีความพร่อง (Impaired) เช่น ลุกจากเก้าอี้ด้วยความลำบาก พยายามจะลุกจากเก้าอี้ด้วยการใช้มือและแขนยันตัว หรือลุกด้วยความพยายามอยู่หลายครั้ง เดินก้มศีรษะและตามองพื้น เดินโดยต้องมีคนช่วยพยุงหรือใช้อุปกรณ์ช่วยเดิน ไม่สามารถเดินได้โดยปราศจากการช่วยเหลือ'
            },
            'q6': {
                0: 'รับรู้บุคคล กาลเวลา และสถานที่ได้ด้วยตนเอง (Oriented to own ability)',
                15: 'ตอบสนองไม่ตรงกับความเป็นจริง ประเมินความสามารถของตนเองเกินกว่าที่ทำได้และลืมคิดถึงข้อจำกัดที่มีอยู่ (Forgets limitations)'
            }
        }
    
    def get_answer_description(self, question, score):
        """Get answer description for a given question and score"""
        answers = self.get_question_answers()
        return answers.get(question, {}).get(score, 'Unknown answer')
    
    def set_answer_values_from_scores(self):
        """Set answer values based on scores (for backward compatibility)"""
        self.q1_value = self.get_answer_description('q1', self.q1_score)
        self.q2_value = self.get_answer_description('q2', self.q2_score)
        self.q3_value = self.get_answer_description('q3', self.q3_score)
        self.q4_value = self.get_answer_description('q4', self.q4_score)
        self.q5_value = self.get_answer_description('q5', self.q5_score)
        self.q6_value = self.get_answer_description('q6', self.q6_score)
    
    def get_risk_description(self):
        """Get risk description in Thai"""
        if self.risk_level == 'low':
            return 'ไม่มีความเสี่ยง หรือมีความเสี่ยงต่ำต่อการลื่น/ตก/หกล้ม'
        elif self.risk_level == 'medium':
            return 'มีความเสี่ยงต่อการลื่น/ตก/หกล้ม'
        else:
            return 'มีความเสี่ยงสูงต่อการลื่น/ตก/หกล้ม (ควรเฝ้าระวังและปรับสภาพแวดล้อม)'
    
    def to_dict(self, include_personal_info=True):
        """Convert to dictionary for JSON response"""
        result = {
            'id': self.id,
            'creator_id': self.creator_id,
            'creator_username': self.creator.username if self.creator else None,
            'q1_score': self.q1_score,
            'q1_value': self.q1_value,
            'q2_score': self.q2_score,
            'q2_value': self.q2_value,
            'q3_score': self.q3_score,
            'q3_value': self.q3_value,
            'q4_score': self.q4_score,
            'q4_value': self.q4_value,
            'q5_score': self.q5_score,
            'q5_value': self.q5_value,
            'q6_score': self.q6_score,
            'q6_value': self.q6_value,
            'total_score': self.total_score,
            'risk_level': self.risk_level,
            'risk_description': self.get_risk_description(),
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'pdpa_consent': self.pdpa_consent
        }
        
        if include_personal_info:
            result.update({
                'name': self.name,
                'tel': self.tel,
                'province': self.province
            })
        
        return result


class AssessmentShare(db.Model):
    __tablename__ = 'assessment_shares'
    
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey('thai_frat_assessments.id'), nullable=False)
    shared_with_username = db.Column(db.String(64), nullable=False)
    shared_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    include_personal_info = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(tz))
    
    # Relationships
    assessment = db.relationship('ThaiFratAssessment', backref=db.backref('shares', lazy=True, cascade='all, delete-orphan'))
    shared_by = db.relationship('User', backref=db.backref('shared_assessments', lazy=True))
    
    def to_dict(self):
        """Convert to dictionary for JSON response"""
        return {
            'id': self.id,
            'assessment_id': self.assessment_id,
            'shared_with_username': self.shared_with_username,
            'shared_by_id': self.shared_by_id,
            'shared_by_username': self.shared_by.username if self.shared_by else None,
            'include_personal_info': self.include_personal_info,
            'created_at': self.created_at.isoformat(),
            'assessment': self.assessment.to_dict(include_personal_info=self.include_personal_info) if self.assessment else None
        }
