from app import db
from datetime import datetime
import pytz
tz = pytz.timezone('Asia/Bangkok')

class Camera(db.Model):
    __tablename__ = 'cameras'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    room_name = db.Column(db.String(64), nullable=False)
    url = db.Column(db.String(256), nullable=False)
    detection_type = db.Column(db.String(32), nullable=False)  # 'bed_exit' or 'fall_detection'
    is_active = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(tz))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(tz), onupdate=lambda: datetime.now(tz))
    alert_start_time = db.Column(db.String(5), default="08:00")  # Format HH:MM
    alert_end_time = db.Column(db.String(5), default="20:00")  # Format HH:MM
    notification_cooldown = db.Column(db.Integer, default=600)
    ai_confidence_threshold = db.Column(db.Float, default=0.5)
    enable_alone_detection = db.Column(db.Boolean, default=True)  # Enable/disable alone detection
    
    # Relationship to User model
    user = db.relationship('User', backref='cameras') 