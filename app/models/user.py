from app import db
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from enum import Enum

class UserRole(Enum):
    ADMIN = "admin"
    USER = "user"

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    role = db.Column(db.Enum(UserRole), default=UserRole.USER, nullable=False)
    telegram_chat_id = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def is_admin(self):
        return self.role == UserRole.ADMIN
    
    def is_user(self):
        return self.role == UserRole.USER
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'role': self.role.value if self.role else 'user',
            
            # ✅ เพิ่มตรงนี้ (สำคัญมาก)
            'telegram_chat_id': self.telegram_chat_id,
            
            'created_at': self.created_at.isoformat() if self.created_at else None
        }