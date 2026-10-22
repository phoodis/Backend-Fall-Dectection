from app import db
from datetime import datetime
import pytz

from app.config import Config

tz = pytz.timezone('Asia/Bangkok')


class LineSettings(db.Model):
    """Per-user LINE Messaging API credentials.

    Before this, LINE was configured only through environment variables, which meant a
    caregiver could not point alerts at their own LINE account without editing .env and
    restarting the containers. The env vars still act as the seed for a user who has never
    saved settings, so an existing single-user deployment keeps working untouched.
    """
    __tablename__ = 'line_settings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    channel_access_token = db.Column(db.Text, nullable=True)
    line_user_id = db.Column(db.String(255), nullable=True)
    # A LINE group, so the whole family sees the alert rather than one person who may be
    # asleep or out of signal. Separate from line_user_id rather than replacing it: both can
    # be set, and an alert nobody answers is the failure this system exists to avoid, so more
    # than one place to answer it is the point. The id cannot be typed in by hand -- see
    # LineDiscoveredTarget, which captures it from the webhook when the bot joins.
    line_group_id = db.Column(db.String(255), nullable=True)
    # Off unless someone deliberately turns it on: enabling this pushes messages to a real
    # phone, so it must never become true as a side effect of creating a row.
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(tz))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(tz), onupdate=lambda: datetime.now(tz))

    @classmethod
    def get_settings(cls, user_id):
        settings = cls.query.filter_by(user_id=user_id).first()
        if not settings:
            # One system bot (owner, 8 Oct): every user gets the bot's TOKEN, but only an administrator gets the .env
            # LINE id and switch -- those belong to whoever set up .env. Seeding them for everyone sent a new
            # ordinary user's alerts to the owner's phone (found in the web test: a fresh user's test push arrived
            # on the owner's LINE without any id typed).
            from app.models.user import User
            user = db.session.get(User, user_id)
            is_admin = bool(user and user.is_admin())
            settings = cls(
                user_id=user_id,
                channel_access_token=Config.LINE_CHANNEL_ACCESS_TOKEN or None,
                line_user_id=(Config.LINE_USER_ID or None) if is_admin else None,
                enabled=Config.LINE_ENABLED if is_admin else False,
            )
            db.session.add(settings)
            db.session.commit()
        return settings

    @classmethod
    def update_settings(cls, user_id, channel_access_token=None, line_user_id=None,
                        line_group_id=None, enabled=None):
        settings = cls.get_settings(user_id)
        if channel_access_token is not None:
            settings.channel_access_token = channel_access_token
        if line_user_id is not None:
            # "" clears it, which is how a user stops alerting one of the two targets without
            # clearing the other. None means "not mentioned in this request, leave it".
            settings.line_user_id = line_user_id or None
        if line_group_id is not None:
            settings.line_group_id = line_group_id or None
        if enabled is not None:
            settings.enabled = bool(enabled)
        settings.updated_at = datetime.now(tz)
        db.session.commit()
        return settings

    def targets(self):
        """-> every id this user's alerts should be pushed to, in order, no duplicates.

        LINE's multicast endpoint takes up to 500 recipients in one call but **refuses group
        ids**, so a person and a group cannot be sent in one request; the sender loops over
        this list and pushes to each. That is at most two calls, and it is the reason this
        returns a list rather than one value.
        """
        out = []
        for target in (self.line_user_id, self.line_group_id):
            target = (target or '').strip()
            if target and target not in out:
                out.append(target)
        return out

    def to_dict(self):
        # The token is a credential: the UI only ever needs to know whether one is stored
        # and to recognise the one it saved, so send a masked tail instead of the value.
        token = self.channel_access_token or ''
        return {
            'id': self.id,
            'enabled': self.enabled,
            'has_token': bool(token),
            'token_preview': f'...{token[-4:]}' if token else '',
            'line_user_id': self.line_user_id or '',
            'line_group_id': self.line_group_id or '',
            'target_count': len(self.targets()),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
