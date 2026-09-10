from app import db
from datetime import datetime
import pytz
tz = pytz.timezone('Asia/Bangkok')

class DetectionLog(db.Model):
    __tablename__ = 'detection_logs'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(tz), index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('cameras.id'), nullable=True)
    detection_result = db.Column(db.String(64), nullable=True)
    confidence_score = db.Column(db.Float, nullable=False)
    camera_name = db.Column(db.String(64), nullable=False)
    room_name = db.Column(db.String(64), nullable=False)
    risk_level = db.Column(db.String(16), nullable=True, default='normal')  # normal, yellow, red
    person_count = db.Column(db.Integer, nullable=True, default=0)

    camera = db.relationship('Camera', backref=db.backref('logs', lazy=True)) 