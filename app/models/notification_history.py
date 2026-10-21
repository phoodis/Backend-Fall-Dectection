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

    # The columns below are all nullable: rows written before they existed have NULL in them
    # (app/db_migrate.py adds them to an existing table without touching the rows).
    # Model score behind this alert.
    confidence = db.Column(db.Float, nullable=True)
    # Written once, by the first person to acknowledge (routes/logs.py); a later acknowledgement never changes them.
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    acknowledged_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # Reserved for the web UI's fields; nothing writes these yet.
    escalation_count = db.Column(db.Integer, nullable=True, default=0)
    clip_path = db.Column(db.String(512), nullable=True)
    still_down_seconds = db.Column(db.Float, nullable=True)

    camera = db.relationship('Camera', backref=db.backref('notifications', lazy=True))
