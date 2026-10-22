"""The v3 camera loop keeps detecting when raising an alert fails.

Alerting has three steps -- alert image, alert row, outbound notification -- and any of them can fail
(disk full, database error, channel down). None of that may end detection, and the next alert after the
cooldown must still be raised. The detector is a stub; the loop, the database (SQLite) and the video
capture are real.
"""
import threading
import time
import types

import cv2
import numpy as np
import pytest

COOLDOWN = 0.3


class _FakeRunner:
    """Stands in for V3FallRunner: every frame is a detected fall."""
    min_period = 0.0

    def __init__(self, detector, fps, is_video_file, **kwargs):
        self.state = types.SimpleNamespace(seen_count=1)

    def read(self, cap):
        ok, frame = cap.read()
        return ok, frame, 0

    def step(self, frame):
        top = (0, True, 0.9, "fall", None)
        return [top], top

    def alert_confidence(self, top):
        return top[2]

    def reset(self):
        pass


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    import app.services.camera_manager as cm
    from app import create_app, db
    from app.config import Config
    from app.models.camera import Camera
    from app.models.notification_history import NotificationHistory
    from app.models.user import User
    from app.services.model_manager import model_manager

    clip = str(tmp_path / "clip.mp4")
    writer = cv2.VideoWriter(clip, cv2.VideoWriter_fourcc(*"mp4v"), 24.0, (64, 48))
    for n in range(24):
        writer.write(np.full((48, 64, 3), n * 8, dtype=np.uint8))
    writer.release()

    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + str(tmp_path / "t.db").replace("\\", "/"))
    monkeypatch.setattr(Config, "ALERT_IMAGE_DIR", str(tmp_path / "alerts"))
    monkeypatch.setattr(Config, "NOTIFICATION_COOLDOWN", COOLDOWN)
    monkeypatch.setattr(cm, "V3FallRunner", _FakeRunner)
    monkeypatch.setattr(model_manager, "get_v3_fall_detector", lambda: object())

    app = create_app()
    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        cam = Camera(name="t", room_name="r", url=clip, detection_type="fall_v2", is_active=True, user_id=admin.id)
        db.session.add(cam)
        db.session.commit()
        cam_id = cam.id

    state = types.SimpleNamespace(attempts=0, finished=0, notified=[], rollbacks=0, errors=[])

    real_raise = cm._raise_v3_fall_alert
    real_rollback = cm._safe_rollback

    def counting_raise(*a, **k):
        state.attempts += 1
        try:
            return real_raise(*a, **k)
        finally:
            state.finished += 1

    def counting_rollback():
        state.rollbacks += 1
        real_rollback()

    monkeypatch.setattr(cm, "_raise_v3_fall_alert", counting_raise)
    monkeypatch.setattr(cm, "_safe_rollback", counting_rollback)
    monkeypatch.setattr(cm, "notify_fall_alert", lambda *a, **k: state.notified.append((a, k)))

    def run(until, timeout=30):
        """Run the loop in a thread until `until(state)`; stop it through is_active; return the rows."""
        def target():
            try:
                cm._process_v3_fall_detection(cam_id, {"LOGGING_INTERVAL": 2})
            except Exception as exc:                                # noqa: BLE001
                state.errors.append(repr(exc))

        th = threading.Thread(target=target, daemon=True)
        th.start()
        deadline = time.time() + timeout
        while time.time() < deadline and th.is_alive() and not until(state):
            time.sleep(0.05)
        alive_when_done = th.is_alive()
        with app.app_context():
            cam = db.session.get(Camera, cam_id)
            cam.is_active = False
            db.session.commit()
        th.join(timeout=30)
        with app.app_context():
            found = list(NotificationHistory.query.filter_by(camera_id=cam_id))
            rows = [(n.detection_type, n.image_path) for n in found]
            confidences = [n.confidence for n in found]
        return types.SimpleNamespace(alive_when_done=alive_when_done, stopped=not th.is_alive(), rows=rows,
                                     confidences=confidences, state=state)

    return types.SimpleNamespace(run=run, cm=cm, state=state)


def _after_cooldown_alert(s):
    """Two attempts, i.e. the loop got past the failure and alerted again one cooldown later."""
    return s.finished >= 2


def test_save_alert_log_raises_once(harness, monkeypatch):
    cm = harness.cm
    real = cm.save_alert_log
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database exploded")
        return real(*a, **k)

    monkeypatch.setattr(cm, "save_alert_log", flaky)
    r = harness.run(_after_cooldown_alert)
    assert r.alive_when_done and r.stopped and not r.state.errors
    assert r.state.rollbacks >= 1
    assert len(r.state.notified) >= 2                       # the notification still went out for the failed row
    assert len(r.rows) >= 1 and all(t == "fall_red" for t, _ in r.rows)


def test_save_alert_log_returns_false_is_rolled_back(harness, monkeypatch):
    cm = harness.cm
    real = cm.save_alert_log
    calls = []

    def failing_once(*a, **k):
        calls.append(1)
        return False if len(calls) == 1 else real(*a, **k)   # what save_alert_log does when its commit fails

    monkeypatch.setattr(cm, "save_alert_log", failing_once)
    r = harness.run(_after_cooldown_alert)
    assert r.alive_when_done and r.stopped and not r.state.errors
    assert r.state.rollbacks >= 1
    assert len(r.rows) >= 1


def test_notification_raises_once(harness, monkeypatch):
    cm = harness.cm
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("channel down")
        harness.state.notified.append((a, k))

    monkeypatch.setattr(cm, "notify_fall_alert", flaky)
    r = harness.run(_after_cooldown_alert)
    assert r.alive_when_done and r.stopped and not r.state.errors
    assert len(calls) >= 2 and len(harness.state.notified) >= 1
    assert len(r.rows) >= 2                                  # the row is stored BEFORE notifying, so both alerts are visible


def test_alert_row_is_saved_before_the_notification(harness, monkeypatch):
    cm = harness.cm
    order = []
    real = cm.save_alert_log

    def save(*a, **k):
        order.append("save")
        return real(*a, **k)

    monkeypatch.setattr(cm, "save_alert_log", save)
    monkeypatch.setattr(cm, "notify_fall_alert", lambda *a, **k: order.append("notify"))
    harness.run(lambda s: s.finished >= 1)
    assert order[:2] == ["save", "notify"]


@pytest.mark.parametrize("mode", ["raises", "returns_false"])
def test_imwrite_fails_once(harness, monkeypatch, mode):
    real = cv2.imwrite
    calls = []

    def flaky(path, img, *a, **k):
        if str(path).endswith(".jpg"):
            calls.append(1)
            if len(calls) == 1:
                if mode == "raises":
                    raise OSError("disk full")
                return False
        return real(path, img, *a, **k)

    monkeypatch.setattr(cv2, "imwrite", flaky)
    r = harness.run(_after_cooldown_alert)
    assert r.alive_when_done and r.stopped and not r.state.errors
    assert len(r.rows) >= 2
    assert r.rows[0][1] is None                              # first alert: stored without an image
    assert any(path for _, path in r.rows[1:])               # a later alert has its image again


def test_everything_fails_always_detection_still_runs(harness, monkeypatch):
    cm = harness.cm

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(cm, "save_alert_log", boom)
    monkeypatch.setattr(cm, "notify_fall_alert", boom)
    monkeypatch.setattr(cv2, "imwrite", boom)
    r = harness.run(lambda s: s.finished >= 3)
    assert r.alive_when_done and r.stopped and not r.state.errors
    assert harness.state.attempts >= 3                       # retried every cooldown, not every frame
    assert harness.state.attempts < 40


def test_exception_escaping_the_alert_helper_is_contained(harness, monkeypatch):
    cm = harness.cm
    calls = []

    def helper(*a, **k):
        calls.append(1)
        raise RuntimeError("helper itself broke")

    monkeypatch.setattr(cm, "_raise_v3_fall_alert", helper)
    r = harness.run(lambda s: len(calls) >= 2)
    assert r.alive_when_done and r.stopped and not r.state.errors
    assert len(calls) >= 2


def test_loop_stores_the_confidence_in_the_alert_row(harness):
    r = harness.run(lambda s: s.finished >= 1)
    assert r.rows and r.confidences == [pytest.approx(0.9)] * len(r.rows)
