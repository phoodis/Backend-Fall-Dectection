from app import db
from datetime import datetime
import pytz
tz = pytz.timezone('Asia/Bangkok')

class NotificationHistory(db.Model):
    __tablename__ = 'notification_history'
    id = db.Column(db.Integer, primary_key=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('cameras.id'), nullable=True)
    sent_at = db.Column(db.DateTime, default=lambda: datetime.now(tz), index=True)
    detection_type = db.Column(db.String(32), nullable=False)
    image_path = db.Column(db.String(256), nullable=True)

    camera = db.relationship('Camera', backref=db.backref('notifications', lazy=True)) 