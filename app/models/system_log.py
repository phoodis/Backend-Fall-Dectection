from app import db
from datetime import datetime
import pytz

tz = pytz.timezone('Asia/Bangkok')

class SystemLog(db.Model):
    __tablename__ = 'system_logs'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(tz), index=True)
    level = db.Column(db.String(10), nullable=False)
    message = db.Column(db.Text, nullable=False)
    component = db.Column(db.String(64), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    user = db.relationship('User', backref=db.backref('system_logs', lazy=True))
