"""LINE Messaging API push for one alert.

Ported from the friend's repository (plan A, step 5) without escalation, "still down" and the pre-fall clip: one
message per alert, worded as a request to look ("may have fallen"), never as a confirmed fall.

The send runs on its own thread and never raises into the caller: the detection loop that raised the alert must
not wait for LINE or fail because of it. Nothing here prints the channel token.
"""
import os
import uuid
from threading import Thread
from datetime import datetime
import pytz
import requests
from app.models.camera import Camera
from app.config import Config
from app.models.line_settings import LineSettings

tz = pytz.timezone('Asia/Bangkok')


def acknowledge_ready():
    """True when the "รับทราบ" button is CONFIGURED: LINE posts a press to
    PUBLIC_BASE_URL/api/line/webhook, and the webhook rejects it without LINE_CHANNEL_SECRET.
    Configured is not proven reachable -- press it once on a real phone before relying on it.
    One definition for the settings page and the sender, so they can never disagree."""
    return bool((Config.PUBLIC_BASE_URL or '').strip()) and bool(Config.LINE_CHANNEL_SECRET)


def _event_text(detection_type):
    """-> (risk level, first line of the message)."""
    if "fall" in detection_type:
        # The score cannot tell a fall from a deep bend, so a fresh fall alert asks a human to look.
        return "red", "❓ อาจมีการล้ม — รบกวนตรวจสอบกล้องด้วยครับ"
    if "alone" in detection_type:
        return "yellow", "⚠️ พบว่ามีคนอยู่ตามลำพัง"
    if detection_type == "bed_exit":
        return "yellow", "⚠️ ตรวจพบการลุกออกจากเตียง"
    return "normal", "สถานะปกติ"


def _build_messages(text, notification_id, image_path):
    """The LINE message objects for one alert: text (with an acknowledge button when the webhook is
    configured), plus the picture when it can be fetched from a public URL."""
    if notification_id is not None and not acknowledge_ready():
        # Without a reachable webhook the button would do nothing when pressed. Say where acknowledging works.
        messages = [{"type": "text", "text": text + "\n\nกดรับทราบได้ที่หน้าเว็บ เมนู 'มอนิเตอร์'"}]
    elif notification_id is not None:
        # The postback carries the notification id so the webhook knows exactly which alert was answered;
        # LINE caps altText at 400 chars and shows it on the lock screen.
        messages = [{
            "type": "template",
            "altText": text[:400],
            "template": {
                "type": "buttons",
                "text": text[:160],
                "actions": [{
                    "type": "postback",
                    "label": "รับทราบ",
                    "data": f"ack={notification_id}",
                    "displayText": "รับทราบแล้ว",
                }],
            },
        }]
    else:
        messages = [{"type": "text", "text": text}]

    # LINE needs a real public HTTPS URL for images (no file upload), served from /api/alert-images/<filename>.
    if image_path and os.path.exists(image_path):
        base_url = (Config.PUBLIC_BASE_URL or "").rstrip("/")
        if base_url:
            image_url = f"{base_url}/api/alert-images/{os.path.basename(image_path)}"
            messages.append({"type": "image", "originalContentUrl": image_url, "previewImageUrl": image_url})
        else:
            print("[LINE] PUBLIC_BASE_URL not set -- sending text only, no image")
    return messages


def _push_all(camera_id, camera_name, room_name, detection_type, image_path, confidence, notification_id):
    """Send one alert to every target of the camera owner's LINE settings. -> number of targets that accepted it."""
    from app import get_worker_app
    app = get_worker_app()

    with app.app_context():
        camera = Camera.query.get(camera_id)
        if not camera:
            return 0

        risk_level, event_text = _event_text(detection_type)
        conf_line = f"\nความมั่นใจ: {confidence:.0%}" if confidence is not None else ""
        text = (
            f"{event_text}\n"
            f"กล้อง: {camera_name}\n"
            f"ห้อง: {room_name}\n"
            f"ความเสี่ยง: {risk_level.upper()}{conf_line}\n"
            f"เวลา: {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}"
        )

        # Per camera owner, not global: each user configures their own LINE target in the web UI.
        settings = LineSettings.get_settings(camera.user_id)
        if not settings.enabled:
            # Checked here rather than at each call site, so every caller (detection loops, the test button) is
            # covered by the one switch and nothing reaches a real phone until it is turned on.
            print(f"[Camera {camera_id}] LINE disabled for this user -- alert not sent")
            return 0

        token = settings.channel_access_token
        targets = settings.targets()
        if not token or not targets:
            print("[LINE] Missing channel access token or a target -- not sent")
            return 0

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        messages = _build_messages(text, notification_id, image_path)

        # One push per target; a failure on one does not stop the others (a family group still counts when one
        # phone is asleep or has blocked the bot).
        delivered = 0
        for target in targets:
            h = dict(headers)
            if notification_id is not None:
                # Idempotent at LINE's end: a retry of the SAME alert is answered 409 instead of reaching the
                # phone twice.
                h["X-Line-Retry-Key"] = str(uuid.uuid5(uuid.NAMESPACE_URL, "fall-alert/%s/%s" % (notification_id, target)))
            try:
                resp = requests.post(
                    "https://api.line.me/v2/bot/message/push",
                    headers=h,
                    json={"to": target, "messages": messages},
                    timeout=10,
                )
                if resp.status_code == 409 and "X-Line-Retry-Key" in h:
                    delivered += 1   # accepted earlier under this key; not sent twice
                    print(f"[Camera {camera_id}] LINE alert already accepted for ...{target[-8:]}")
                elif resp.status_code == 200:
                    delivered += 1
                    print(f"[Camera {camera_id}] LINE alert sent to ...{target[-8:]}")
                else:
                    print(f"[Camera {camera_id}] LINE error for ...{target[-8:]} {resp.status_code}: {resp.text[:300]}")
            except Exception as e:
                print(f"[Camera {camera_id}] LINE error for ...{target[-8:]}: {type(e).__name__}")
        return delivered


def send_line_message_async(camera_id, camera_name, room_name, detection_type, timestamp,
                            image_path, confidence=None, notification_id=None, wait=False):
    """Push one alert to every LINE target of the camera's owner. Runs on a daemon thread unless `wait` is set;
    with `wait` it runs inline and returns how many targets accepted it (0 = nothing delivered).

    Never raises: a failure while sending (or while starting the thread) is printed and swallowed, because the
    caller is a detection loop.
    """
    def _send():
        try:
            return _push_all(camera_id, camera_name, room_name, detection_type, image_path, confidence,
                             notification_id)
        except Exception as e:
            print(f"[Camera {camera_id}] LINE send failed: {type(e).__name__}")
            return 0

    if wait:
        return _send()
    try:
        Thread(target=_send, daemon=True).start()
    except Exception as e:
        print(f"[Camera {camera_id}] LINE thread could not start: {type(e).__name__}")
    return None
