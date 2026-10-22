import base64
import hashlib
import hmac
from datetime import datetime

import pytz
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

import requests

from app import db
from app.config import Config
from app.services.line_service import acknowledge_ready
from app.models.line_settings import LineSettings
from app.models.line_target import LineDiscoveredTarget
from app.models.notification_history import NotificationHistory
from app.models.user import User

tz = pytz.timezone('Asia/Bangkok')

bp = Blueprint('line', __name__, url_prefix='/api/line')


def _failure(what, exc):
    """A 500 body that cannot carry a secret. str(exc) of a database error includes the statement's parameters,
    and the parameters of a LINE settings row include the channel access token: it must not reach the response
    (or the log), so only the exception's class is reported."""
    try:
        db.session.rollback()
    except Exception:
        pass
    print(f'[LINE] {what} failed: {type(exc).__name__}')
    return jsonify({'success': False, 'error': f'{what} failed ({type(exc).__name__})'}), 500


@bp.route('/settings', methods=['GET'])
@jwt_required()
def get_line_settings():
    try:
        user_id = int(get_jwt_identity())
        settings = LineSettings.get_settings(user_id)
        data = settings.to_dict()
        # What the acknowledge button and the 60-second clip need on top of a channel token.
        # Without these, LINE alerts still arrive but pressing "รับทราบ" does nothing and no
        # clip is ever sent, with nothing on screen explaining why -- so the settings page can
        # say which piece is missing instead of leaving the feature quietly half-working.
        base = (Config.PUBLIC_BASE_URL or '').rstrip('/')
        data['acknowledge_ready'] = acknowledge_ready()
        data['public_base_url'] = base
        data['channel_secret_set'] = bool(Config.LINE_CHANNEL_SECRET)
        data['webhook_url'] = f'{base}/api/line/webhook' if base else ''
        # A group id appears nowhere a caregiver can read it -- it arrives only in a webhook
        # event when the bot is invited. The settings page offers what the webhook has seen
        # instead of asking someone to read raw logs.
        # Admin-only, enforced HERE (Codex P1, 8 Oct): the page hid the list, but the API still returned every group's
        # id to any signed-in user. An ordinary user gets an empty list.
        user = db.session.get(User, user_id)
        is_admin = bool(user and user.is_admin())
        data['discovered_targets'] = [
            t.to_dict() for t in LineDiscoveredTarget.query.order_by(
                LineDiscoveredTarget.last_seen.desc()).limit(20).all()
        ] if is_admin else []
        return jsonify({'success': True, 'data': data}), 200
    except Exception as e:
        return _failure('Reading LINE settings', e)


@bp.route('/settings', methods=['POST'])
@jwt_required()
def update_line_settings():
    try:
        user_id = int(get_jwt_identity())
        data = request.get_json() or {}

        token = data.get('channel_access_token')
        line_user_id = data.get('line_user_id')
        line_group_id = data.get('line_group_id')
        enabled = data.get('enabled')

        if token is None and line_user_id is None and line_group_id is None and enabled is None:
            return jsonify({'success': False, 'error': 'Nothing to update'}), 400

        # An empty token from the UI means "leave the stored one alone" -- the field is
        # rendered blank because the real value is never sent back to the browser, so
        # treating blank as a delete would wipe the credential every time someone saves
        # after only flipping the toggle.
        if token is not None and token.strip() == '':
            token = None
        # One system bot (owner, 8 Oct): its token is set by an administrator; an ordinary user only chooses where
        # THEIR alerts go (their LINE id / a group), so a token from a non-admin is refused, not silently stored.
        if token:
            user = db.session.get(User, user_id)
            if not (user and user.is_admin()):
                return jsonify({'success': False,
                                'error': 'Only an administrator can change the LINE bot token'}), 403
        settings = LineSettings.get_settings(user_id)
        # An empty string here means "stop sending to this one", which is how a user drops the
        # individual target and keeps the group, or the other way round. It is only rejected
        # when it would leave nowhere to send to at all.
        will_have_token = bool(token) or bool(settings.channel_access_token)
        after_user = settings.line_user_id if line_user_id is None else line_user_id.strip()
        after_group = settings.line_group_id if line_group_id is None else line_group_id.strip()
        if enabled and not will_have_token:
            return jsonify({
                'success': False,
                'error': 'Cannot enable LINE alerts without a channel access token'
            }), 400
        if enabled and not (after_user or after_group):
            return jsonify({
                'success': False,
                'error': 'Cannot enable LINE alerts without a LINE user ID or a group to send to'
            }), 400

        settings = LineSettings.update_settings(
            user_id=user_id,
            channel_access_token=token.strip() if token else None,
            line_user_id=None if line_user_id is None else line_user_id.strip(),
            line_group_id=None if line_group_id is None else line_group_id.strip(),
            enabled=enabled,
        )
        return jsonify({'success': True, 'message': 'LINE settings updated', 'data': settings.to_dict()}), 200
    except Exception as e:
        return _failure('Saving LINE settings', e)


@bp.route('/test', methods=['POST'])
@jwt_required()
def test_line_settings():
    """Send one test message to the saved LINE target.

    Deliberately refuses while alerts are switched off: the toggle is what stops messages
    reaching a real phone, and a test button that ignored it would make the switch a lie.
    """
    try:
        user_id = int(get_jwt_identity())
        settings = LineSettings.get_settings(user_id)

        if not settings.enabled:
            return jsonify({'success': False, 'error': 'LINE alerts are turned off. Turn them on first.'}), 400
        targets = settings.targets()
        if not settings.channel_access_token or not targets:
            return jsonify({'success': False,
                            'error': 'Channel access token and at least one target are required'}), 400

        # One push per target: LINE's multicast endpoint would take several recipients in one
        # call but refuses group ids, so a person and a group cannot share a request.
        sent, failures = [], []
        for target in targets:
            resp = requests.post(
                'https://api.line.me/v2/bot/message/push',
                headers={
                    'Authorization': f'Bearer {settings.channel_access_token}',
                    'Content-Type': 'application/json',
                },
                json={
                    'to': target,
                    'messages': [{'type': 'text', 'text': 'ทดสอบการแจ้งเตือนจากระบบเฝ้าระวังผู้สูงอายุ'}],
                },
                timeout=10,
            )
            if resp.status_code == 200:
                sent.append(target)
            else:
                # LINE's own error body is the only thing that explains a bad token or a group
                # the bot is not in, so pass it through rather than flattening it to "failed".
                failures.append(f'...{target[-8:]}: LINE API {resp.status_code}: {resp.text[:300]}')

        if sent and not failures:
            return jsonify({'success': True,
                            'message': f'Test message sent to {len(sent)} target(s)'}), 200
        if sent:
            # Partial success is its own answer: one target working and another not is exactly
            # the case a single "failed" would hide.
            return jsonify({'success': False,
                            'error': f'Sent to {len(sent)}, failed for: ' + '; '.join(failures)}), 400
        return jsonify({'success': False, 'error': '; '.join(failures)}), 400
    except Exception as e:
        return _failure('Sending the test message', e)


def _reply(reply_token, messages):
    """LINE's reply API -- free and rate-limit-friendly, unlike push, and valid for about
    30s after the event, which is plenty for answering a button press."""
    try:
        requests.post(
            'https://api.line.me/v2/bot/message/reply',
            headers={'Authorization': f'Bearer {_token()}', 'Content-Type': 'application/json'},
            json={'replyToken': reply_token, 'messages': messages},
            timeout=10,
        )
    except Exception as e:
        print(f'[LINE] reply failed: {type(e).__name__}')


def _token():
    # The SYSTEM bot's token (one bot, owner 8 Oct) -- independent of anyone's on/off switch, so the bot can answer
    # (e.g. a new user asking for their LINE id) even when every user has alerts switched off (Codex P2). Falls back
    # to an enabled user's stored token for deployments that never set it in .env.
    if Config.LINE_CHANNEL_ACCESS_TOKEN:
        return Config.LINE_CHANNEL_ACCESS_TOKEN
    row = LineSettings.query.filter(LineSettings.enabled.is_(True)).first()
    return row.channel_access_token if row else ''


@bp.route('/webhook', methods=['POST'])
def line_webhook():
    """Receives the "รับทราบ" button press from LINE.

    Deliberately unauthenticated in the JWT sense -- LINE's servers call it, not a logged-in
    browser -- so the X-Line-Signature HMAC is the only thing standing between this endpoint
    and anyone on the internet marking alerts as handled. It is verified before the body is
    parsed, and a missing channel secret is treated as "reject everything" rather than
    "trust everything".
    """
    body = request.get_data()
    signature = request.headers.get('X-Line-Signature', '')
    secret = Config.LINE_CHANNEL_SECRET
    if not secret:
        print('[LINE] webhook called but LINE_CHANNEL_SECRET is not set -- rejecting')
        return 'unconfigured', 403

    expected = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    if not hmac.compare_digest(expected, signature):
        return 'bad signature', 403

    try:
        events = (request.get_json(silent=True) or {}).get('events', [])
    except Exception:
        events = []

    for event in events:
        # join / leave carry the only copy of a group id this system will ever see. LINE sends
        # join when the bot is invited, and message events from the group afterwards; both are
        # recorded so a group added before this code existed still shows up as soon as anyone
        # posts in it. Recording is not consent -- nothing is ever sent to a target until it is
        # chosen in the settings page and the switch is on.
        source = event.get('source', {}) or {}
        source_type = source.get('type')
        if source_type in ('group', 'room'):
            target_id = source.get('groupId') or source.get('roomId')
            if event.get('type') == 'leave':
                LineDiscoveredTarget.departed(target_id)
            else:
                LineDiscoveredTarget.seen(source_type, target_id)

        # A person who adds the bot or writes to it 1:1 gets THEIR OWN LINE id back, privately, so they can paste it
        # into the web page (owner, 8 Oct: every user enters their own LINE; nobody can read their id anywhere else).
        # Only the sender sees it; nothing is stored or sent anywhere until they save it in the settings page.
        if source_type == 'user' and event.get('type') in ('follow', 'message') and event.get('replyToken'):
            uid = source.get('userId')
            if uid:
                _reply(event['replyToken'], [{'type': 'text', 'text':
                       'LINE ID ของคุณ:\n%s\n\nคัดลอกไปวางในหน้าเว็บ เมนู "ตั้งค่าการแจ้งเตือน" ช่อง LINE User ID '
                       'แล้วเปิดสวิตช์ เพื่อรับการแจ้งเตือนของคุณ' % uid}])

        if event.get('type') != 'postback':
            continue
        data = event.get('postback', {}).get('data', '')
        if not data.startswith('ack='):
            continue
        try:
            notification_id = int(data.split('=', 1)[1])
        except ValueError:
            continue
        try:
            _handle_ack(notification_id, event.get('replyToken'))
        except Exception as e:
            # LINE retries any non-2xx answer; one bad event must not turn the whole delivery into a retry loop.
            print(f'[LINE] acknowledge failed: {type(e).__name__}')
            try:
                db.session.rollback()
            except Exception:
                pass

    # LINE retries on any non-2xx, so return 200 even for events this app ignores.
    return 'ok', 200


def _handle_ack(notification_id, reply_token):
    notification = NotificationHistory.query.get(notification_id)
    if not notification:
        if reply_token:
            _reply(reply_token, [{'type': 'text', 'text': 'ไม่พบการแจ้งเตือนนี้ในระบบ'}])
        return

    already = notification.acknowledged_at is not None
    if not already:
        # acknowledged_by stays NULL: it is a FK to users, and whoever pressed the button in LINE is not
        # necessarily a user of the web app.
        # Same as the web route: an aware Bangkok time, so the stored value follows the same rule as every other column.
        notification.acknowledged_at = datetime.now(tz)
        db.session.commit()

    messages = [{
        'type': 'text',
        'text': 'รับทราบแล้ว' + ('' if not already else ' (มีคนรับทราบไปก่อนหน้านี้แล้ว)'),
    }]

    if reply_token:
        _reply(reply_token, messages)
