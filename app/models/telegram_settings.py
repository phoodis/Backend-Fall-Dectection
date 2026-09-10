from app import db
from datetime import datetime
import pytz

tz = pytz.timezone('Asia/Bangkok')

class TelegramSettings(db.Model):
    __tablename__ = 'telegram_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    bot_token = db.Column(db.String(255), nullable=True)
    chat_id = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(tz))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(tz), onupdate=lambda: datetime.now(tz))
    
    @classmethod
    def get_settings(cls, user_id):
        settings = cls.query.filter_by(user_id=user_id).first()
        if not settings:
            settings = cls(user_id=user_id)
            db.session.add(settings)
            db.session.commit()
        return settings
    
    @classmethod
    def update_settings(cls, user_id, bot_token=None, chat_id=None):
        settings = cls.get_settings(user_id)
        if bot_token is not None:
            settings.bot_token = bot_token
        if chat_id is not None:
            settings.chat_id = chat_id
        settings.updated_at = datetime.now(tz)
        db.session.commit()
        return settings
    
    def to_dict(self):
        return {
            'id': self.id,
            'bot_token': self.bot_token,
            'chat_id': self.chat_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
