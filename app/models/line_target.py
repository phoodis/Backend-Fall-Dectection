from datetime import datetime

import pytz

from app import db

tz = pytz.timezone('Asia/Bangkok')


class LineDiscoveredTarget(db.Model):
    """A LINE group or multi-person room the bot has been added to.

    It exists because a group ID cannot be typed in by hand. A person's own LINE user ID is
    printed in the LINE Developers console, but a group's ID appears nowhere a caregiver can
    read -- it is only ever delivered in a webhook event when the bot joins. Without this,
    "send alerts to the family group" means reading raw webhook logs, which is not something to
    ask of the person installing this.

    So the webhook records every group it is invited to here, and the settings page offers the
    list. Nothing is sent anywhere as a result of a row appearing: being in a group is not
    consent to be alerted in it, and the target still has to be chosen and the switch still has
    to be on.

    Not tied to a user. The webhook is called by LINE, not by a logged-in browser, and its
    signature is verified against one channel secret, so at webhook time there is no user to
    attribute the event to. Anyone who can reach the settings page can see the list; that is
    the same trust boundary the channel token already sits inside.
    """
    __tablename__ = 'line_discovered_targets'

    id = db.Column(db.Integer, primary_key=True)
    # 'group' or 'room' -- LINE's two kinds of multi-person chat. Kept rather than normalised
    # away because only a group survives everyone leaving, and a room is a weaker thing to
    # point a fall alert at.
    target_type = db.Column(db.String(16), nullable=False)
    target_id = db.Column(db.String(255), nullable=False, unique=True)
    first_seen = db.Column(db.DateTime, default=lambda: datetime.now(tz))
    last_seen = db.Column(db.DateTime, default=lambda: datetime.now(tz))
    # True once the bot has been removed again, so the list can show it without pretending it
    # still works. The row is kept rather than deleted: a target that was chosen and then left
    # explains a silent alert far better than a target that vanished.
    left = db.Column(db.Boolean, nullable=False, default=False)

    @classmethod
    def seen(cls, target_type, target_id):
        """Record that the bot is in this group. Safe to call on every event."""
        if not target_id:
            return None
        row = cls.query.filter_by(target_id=target_id).first()
        if row is None:
            row = cls(target_type=target_type, target_id=target_id)
            db.session.add(row)
        row.target_type = target_type or row.target_type
        row.last_seen = datetime.now(tz)
        row.left = False
        db.session.commit()
        return row

    @classmethod
    def departed(cls, target_id):
        row = cls.query.filter_by(target_id=target_id).first()
        if row is not None:
            row.left = True
            db.session.commit()
        return row

    def to_dict(self):
        return {
            'target_type': self.target_type,
            'target_id': self.target_id,
            # A group id is 33 characters of noise; the UI shows the tail so two of them can be
            # told apart without printing the whole thing.
            'preview': f'...{self.target_id[-8:]}' if self.target_id else '',
            'left': self.left,
            'first_seen': self.first_seen.isoformat() if self.first_seen else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
        }
