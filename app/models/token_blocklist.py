from app import db
from datetime import datetime
import pytz

tz = pytz.timezone('Asia/Bangkok')

class TokenBlocklist(db.Model):
    __tablename__ = 'token_blocklist'
    
    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(36), nullable=False, unique=True)  # JWT ID
    token_type = db.Column(db.String(10), nullable=False)  # 'access' or 'refresh'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    revoked_at = db.Column(db.DateTime, default=lambda: datetime.now(tz))
    expires_at = db.Column(db.DateTime, nullable=False)
    
    @classmethod
    def is_jti_blacklisted(cls, jti):
        """Check if a token JTI is blacklisted"""
        try:
            token = cls.query.filter_by(jti=jti).first()
            return token is not None
        except Exception as e:
            print(f"Error checking blacklist: {e}")
            return False
    
    @classmethod
    def add_token_to_blacklist(cls, jti, token_type, user_id, expires_at):
        """Add a token to the blacklist"""
        try:
            revoked_token = cls(
                jti=jti,
                token_type=token_type,
                user_id=user_id,
                expires_at=expires_at
            )
            db.session.add(revoked_token)
            db.session.commit()
            return True
        except Exception as e:
            print(f"Error adding token to blacklist: {e}")
            db.session.rollback()
            return False
    
    @classmethod
    def cleanup_expired_tokens(cls):
        """Remove expired tokens from blacklist (cleanup job)"""
        try:
            now = datetime.now(tz)
            expired_tokens = cls.query.filter(cls.expires_at < now).all()
            count = len(expired_tokens)
            for token in expired_tokens:
                db.session.delete(token)
            db.session.commit()
            return count
        except Exception as e:
            print(f"Error during token cleanup: {e}")
            db.session.rollback()
            return 0
