"""End-to-end smoke test of the v3 camera loop (camera_manager._process_v3_fall_detection) on a real clip,
without Postgres, Redis, Celery or an outbound channel.

    .venv-v3\\Scripts\\python.exe tools\\v3_loop_smoke_test.py "C:\\...\\Dataset_clips\\Fall_6.mp4"

It points the app at a throw-away SQLite database, registers a 'fall_v2' camera whose URL is the clip,
runs the loop in a thread, replaces the notification hook (notify_fall_alert) with a recorder, and waits for the alert. Then it
deactivates the camera and checks that the loop stopped and that the alert was stored:
  - at least one notification_history row of type fall_red,
  - the alert image exists on disk,
  - the notification hook was called once for that alert (cooldown not violated),
  - the detection log carries the 'fall_v2' label.
Fall_6 is a real fall that the detector flags at ~6.5 s of video time (8 fps profile).
"""
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

clip = os.path.abspath(sys.argv[1])
tmp = tempfile.mkdtemp(prefix="v3smoke_")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tmp, "smoke.db").replace("\\", "/")
os.environ["ALERT_IMAGE_DIR"] = os.path.join(tmp, "alerts")
os.environ.setdefault("V3_DEVICE", "cpu")

import app.services.camera_manager as cm                        # noqa: E402
from app import create_app, db                                  # noqa: E402
from app.models.camera import Camera                            # noqa: E402
from app.models.detection_log import DetectionLog               # noqa: E402
from app.models.notification_history import NotificationHistory  # noqa: E402
from app.models.user import User                                # noqa: E402

sent = []
cm.notify_fall_alert = lambda *a, **k: sent.append((time.time(), a))

app = create_app()
with app.app_context():
    admin = User.query.filter_by(username="admin").first()
    cam = Camera(name="smoke", room_name="lab", url=clip, detection_type="fall_v2", is_active=True, user_id=admin.id)
    db.session.add(cam)
    db.session.commit()
    cam_id = cam.id

errors = []


def run():
    try:
        cm._process_v3_fall_detection(cam_id, {"LOGGING_INTERVAL": 2})
    except Exception as exc:                                    # noqa: BLE001
        errors.append(repr(exc))


t0 = time.time()
th = threading.Thread(target=run, daemon=True)
th.start()
deadline = t0 + 240
while not sent and time.time() < deadline and th.is_alive():
    time.sleep(0.5)
alert_after = time.time() - t0
time.sleep(3)                                                   # let it keep running past the alert
with app.app_context():
    cam = db.session.get(Camera, cam_id)
    cam.is_active = False
    db.session.commit()
th.join(timeout=60)

with app.app_context():
    notes = NotificationHistory.query.filter_by(camera_id=cam_id, detection_type="fall_red").all()
    logs = DetectionLog.query.filter_by(camera_id=cam_id).all()
    images = [n.image_path for n in notes if n.image_path and os.path.exists(n.image_path)]

print(f"alert after {alert_after:.1f}s wall time | loop stopped: {not th.is_alive()} | errors: {errors}")
print(f"notification calls: {len(sent)} | fall_red rows: {len(notes)} | images on disk: {len(images)} | "
      f"detection logs: {[l.detection_result for l in logs]}")
ok = (not errors and not th.is_alive() and len(sent) == 1 and len(notes) == 1 and len(images) == 1
      and any(l.detection_result == "fall_v2" for l in logs))
print("SMOKE TEST", "PASSED" if ok else "FAILED")
sys.exit(0 if ok else 1)
