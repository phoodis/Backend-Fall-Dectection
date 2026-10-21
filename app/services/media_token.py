"""Short-lived, camera-scoped credentials for the live MJPEG view.

A browser loads the live view as `<img src=...>`, which cannot send an Authorization header, so
until now `GET /api/stream/camera/<id>` served any camera's video to anyone who could reach the
API. The frontend's workaround made it worse: it appended the user's full JWT access token to
the image URL as `?token=`, so a credential valid for every API ended up in access logs,
browser history and anything that records URLs -- and the backend never even read it.

Design, agreed after Codex's and Gemini's critiques (the friend's backend, 2026-09-30):

- The token is NOT a JWT. It is signed with itsdangerous under its own salt, so a leaked media
  token cannot be replayed as a bearer token against any other endpoint, and an access token
  cannot be passed off as a media token.
- It binds the user id, the camera id and the issuing session's JWT `jti`. At connect time the
  server re-checks everything rather than trusting the token: signature, age, that the user
  still exists and still owns the camera (or is an admin), that the camera exists, and that the
  session has not been logged out (`token_blocklist`). Logging out therefore revokes it.
- It can only START a view for START_SECONDS. A view then lasts at most STREAM_MAX_SECONDS and
  is closed by the server; the client reconnects with a fresh token. So a leaked URL is worth at
  most one START_SECONDS window plus one STREAM_MAX_SECONDS view -- the owner-level numbers
  stated in the handoff for confirmation.
- The query token is redacted from the request log.

Deployment requirements this code cannot enforce and does not pretend to: HTTPS, and a strong,
non-default SECRET_KEY (a warning is printed when the default is in use).
"""
import logging
import re
import time
from urllib.parse import unquote

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

START_SECONDS = 60
STREAM_MAX_SECONDS = 600
_SALT = 'mjpeg-view-v1'
_DEFAULT_SECRETS = {'dev', 'change-me', 'secret', ''}


def _signer():
    secret = current_app.config.get('SECRET_KEY') or ''
    if secret in _DEFAULT_SECRETS and not current_app.config.get('_MEDIA_SECRET_WARNED'):
        current_app.config['_MEDIA_SECRET_WARNED'] = True
        print('SECURITY: SECRET_KEY is a default value; live-view links can be forged by anyone '
              'who knows it. Set a long random SECRET_KEY before exposing this system.')
    return URLSafeTimedSerializer(secret, salt=_SALT)


def issue(user_id, camera_id, session_jti):
    return _signer().dumps({'u': int(user_id), 'c': int(camera_id), 'j': str(session_jti)})


def verify(token, camera_id):
    """-> (camera, None) when the bearer may watch `camera_id` now, else (None, http_status).

    Every rejection happens before any camera or stream work. 401 for anything wrong with the
    token itself; 404 when the token is sound but this user may not see this camera, which is
    the same answer an owner check gives elsewhere and says nothing about whether it exists.
    """
    from app.models.camera import Camera
    from app.models.token_blocklist import TokenBlocklist
    from app.models.user import User

    if not token or len(token) > 512:
        return None, 401
    try:
        data = _signer().loads(token, max_age=START_SECONDS)
    except SignatureExpired:
        return None, 401
    except BadSignature:
        return None, 401
    if not isinstance(data, dict):
        return None, 401
    try:
        user_id, token_camera, jti = int(data['u']), int(data['c']), str(data['j'])
    except (KeyError, TypeError, ValueError):
        return None, 401
    if token_camera != int(camera_id):
        return None, 401
    user = User.query.get(user_id)
    if user is None:
        return None, 401
    if TokenBlocklist.is_jti_blacklisted(jti):
        return None, 401
    camera = Camera.query.get(camera_id)
    if camera is None or not (user.is_admin() or camera.user_id == user.id):
        return None, 404
    return camera, None


def view_deadline(seconds=STREAM_MAX_SECONDS):
    """time.monotonic() at which a view must end; pass it to generate_mjpeg_stream(stop_at=)."""
    return time.monotonic() + seconds


def bounded(stream, deadline):
    """Yield from `stream` until `deadline`, checked BEFORE each frame so nothing is sent late.

    Defence in depth only: the generator itself also stops at the deadline, which is what ends
    a view whose camera has stalled and is yielding nothing.
    """
    try:
        for chunk in stream:
            if time.monotonic() >= deadline:
                break
            yield chunk
    finally:
        close = getattr(stream, 'close', None)
        if close:
            close()


_TOKEN_IN_URL = re.compile(r"""([?&;](?:t|token)=)[^&\s"']+""", re.IGNORECASE)


def _decoded(text):
    """Percent-decode until stable (max 3 rounds) so `%74=` or `t%3D` cannot slip past."""
    for _ in range(3):
        nxt = unquote(text)
        if nxt == text:
            break
        text = nxt
    return text


def redact(text):
    """-> text with any `t=`/`token=` value replaced, matched on the DECODED text.

    Matching the raw line let an encoded key (`%74=...`) through with its value intact (Codex
    REVIEW-3). The decoded form is what gets logged, so nothing encoded is left to hide in.
    """
    decoded = _decoded(text)
    return _TOKEN_IN_URL.sub(r'\1REDACTED', decoded) if _TOKEN_IN_URL.search(decoded) else text


class RedactMediaTokens(logging.Filter):
    """Strip `t=` / `token=` values from request-log lines before they are written."""

    def filter(self, record):
        try:
            text = record.getMessage()
        except Exception:
            return True
        cleaned = redact(text)
        if cleaned != text:
            record.msg, record.args = cleaned, ()
        return True


def install_log_redaction():
    flt = RedactMediaTokens()
    for name in ('werkzeug', 'gunicorn.access', 'gunicorn.error'):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactMediaTokens) for f in logger.filters):
            logger.addFilter(flt)
