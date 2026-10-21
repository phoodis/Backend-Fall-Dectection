"""Plan A step 2: /api/alert-images, acknowledge, the new notification_history columns and their migration.

Real Flask app on a throw-away SQLite database, no detector and no worker.
"""
import os
import sqlite3
import sys

import pytest
from sqlalchemy import create_engine, inspect

NEW_COLUMNS = ["confidence", "acknowledged_at", "acknowledged_by", "escalation_count", "clip_path", "still_down_seconds"]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from app import create_app, db
    from app.config import Config
    from app.models.camera import Camera
    from app.models.notification_history import NotificationHistory
    from app.models.user import User, UserRole

    alerts = tmp_path / "alerts"
    alerts.mkdir()
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + str(tmp_path / "t.db").replace("\\", "/"))
    monkeypatch.setattr(Config, "ALERT_IMAGE_DIR", str(alerts))
    app = create_app()

    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        alice = User.query.filter_by(username="testuser").first()
        bob = User(username="bob", role=UserRole.USER)
        bob.set_password("bob12345")
        db.session.add(bob)
        db.session.commit()
        cam_a = Camera(name="a", room_name="r", url="x.mp4", detection_type="fall_v2", user_id=alice.id)
        cam_b = Camera(name="b", room_name="r", url="y.mp4", detection_type="fall_v2", user_id=bob.id)
        db.session.add_all([cam_a, cam_b])
        db.session.commit()
        n_a = NotificationHistory(camera_id=cam_a.id, detection_type="fall_red", image_path="/x/a.jpg", confidence=0.91)
        n_b = NotificationHistory(camera_id=cam_b.id, detection_type="fall_red", image_path="/x/b.jpg")
        n_orphan = NotificationHistory(camera_id=None, detection_type="fall_red")
        db.session.add_all([n_a, n_b, n_orphan])
        db.session.commit()
        ids = dict(a=n_a.id, b=n_b.id, orphan=n_orphan.id, cam_a=cam_a.id, cam_b=cam_b.id,
                   admin=admin.id, alice=alice.id, bob=bob.id)

    client = app.test_client()

    def token(username, password):
        r = client.post("/api/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.get_data(as_text=True)
        return {"Authorization": "Bearer " + r.get_json()["access_token"]}

    class Env:
        pass

    e = Env()
    e.app, e.client, e.ids, e.alerts, e.db = app, client, ids, alerts, db
    e.admin = token("admin", "admin123")
    e.alice = token("testuser", "user123")
    e.bob = token("bob", "bob12345")
    e.tmp = tmp_path
    return e


# ---------------------------------------------------------------- /api/alert-images

def test_serves_images_and_video_without_a_token(env):
    (env.alerts / "v3_fall_detect_1_1700000000.jpg").write_bytes(b"\xff\xd8\xffJPEG")
    (env.alerts / "clip.mp4").write_bytes(b"MP4DATA")
    r = env.client.get("/api/alert-images/v3_fall_detect_1_1700000000.jpg")
    assert r.status_code == 200 and r.data == b"\xff\xd8\xffJPEG"
    assert r.mimetype == "image/jpeg" and r.headers["X-Content-Type-Options"] == "nosniff"
    r = env.client.get("/api/alert-images/clip.mp4")
    assert r.status_code == 200 and r.mimetype == "video/mp4"


@pytest.mark.parametrize("path", [
    "../secret.jpg", "..%2Fsecret.jpg", "%2e%2e%2fsecret.jpg", "..%5Csecret.jpg", "..\\secret.jpg",
    "sub/../../secret.jpg", "%2e%2e/%2e%2e/secret.jpg", "/etc/passwd", "C:%5Csecret.jpg",
    "a.jpg%00.txt", ".hidden.jpg", "..jpg", "subdir", "sub%2Fnested.jpg",
])
def test_path_traversal_and_odd_names_are_refused(env, path):
    (env.tmp / "secret.jpg").write_bytes(b"SECRET")             # one level above the alert directory
    (env.alerts / ".hidden.jpg").write_bytes(b"H")
    (env.alerts / "sub").mkdir()
    (env.alerts / "sub" / "nested.jpg").write_bytes(b"N")
    r = env.client.get("/api/alert-images/" + path)
    assert r.status_code in (404, 400), path
    assert b"SECRET" not in r.data


def test_only_listed_extensions_and_existing_files(env):
    (env.alerts / "notes.txt").write_bytes(b"TEXT")
    (env.alerts / "app.py").write_bytes(b"CODE")
    (env.alerts / "noext").write_bytes(b"X")
    for name in ("notes.txt", "app.py", "noext", "missing.jpg", "x.JPG.exe"):
        assert env.client.get("/api/alert-images/" + name).status_code == 404, name
    (env.alerts / "UPPER.JPG").write_bytes(b"U")
    assert env.client.get("/api/alert-images/UPPER.JPG").status_code == 200


def test_symlink_pointing_outside_is_refused(env):
    (env.tmp / "secret.jpg").write_bytes(b"SECRET")
    try:
        os.symlink(str(env.tmp / "secret.jpg"), str(env.alerts / "link.jpg"))
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available here")
    r = env.client.get("/api/alert-images/link.jpg")
    assert r.status_code == 404 and b"SECRET" not in r.data


# ---------------------------------------------------------------- acknowledge

def _ack(env, who, key):
    return env.client.post(f"/api/detection-logs/notifications/{env.ids[key]}/acknowledge", headers=getattr(env, who))


def _row(env, key):
    from app.models.notification_history import NotificationHistory
    with env.app.app_context():
        env.db.session.expire_all()
        n = env.db.session.get(NotificationHistory, env.ids[key])
        return n.acknowledged_at, n.acknowledged_by


def test_acknowledge_requires_login(env):
    r = env.client.post(f"/api/detection-logs/notifications/{env.ids['a']}/acknowledge")
    assert r.status_code == 401


def test_user_acknowledges_own_camera_only(env):
    r = _ack(env, "alice", "a")
    assert r.status_code == 200
    body = r.get_json()
    assert body["acknowledged_by"] == env.ids["alice"] and body["acknowledged_at"]
    assert _ack(env, "alice", "b").status_code == 403           # bob's camera
    assert _ack(env, "alice", "orphan").status_code == 403      # no camera: nobody but an admin
    assert _row(env, "b") == (None, None) and _row(env, "orphan") == (None, None)


def test_admin_acknowledges_any_camera(env):
    for key in ("a", "b", "orphan"):
        r = _ack(env, "admin", key)
        assert r.status_code == 200 and r.get_json()["acknowledged_by"] == env.ids["admin"], key


def test_unknown_notification_is_404(env):
    r = env.client.post("/api/detection-logs/notifications/999999/acknowledge", headers=env.admin)
    assert r.status_code == 404


def test_second_acknowledge_keeps_the_first(env):
    first = _ack(env, "alice", "a").get_json()
    stored = _row(env, "a")
    second = _ack(env, "admin", "a")
    again = _ack(env, "alice", "a")
    assert second.status_code == 200 and again.status_code == 200
    assert second.get_json() == first and again.get_json() == first     # the reply names the FIRST person
    assert _row(env, "a") == stored and stored[1] == env.ids["alice"]


# ---------------------------------------------------------------- GET /notifications

def test_notifications_return_every_new_field(env):
    _ack(env, "alice", "a")
    rows = {r["id"]: r for r in env.client.get("/api/detection-logs/notifications", headers=env.admin).get_json()}
    a = rows[env.ids["a"]]
    for key in ["id", "camera_id", "sent_at", "detection_type", "image_path"] + NEW_COLUMNS + ["still_down_threshold"]:
        assert key in a, key
    assert a["confidence"] == pytest.approx(0.91) and a["acknowledged_by"] == env.ids["alice"] and a["acknowledged_at"]
    assert a["escalation_count"] == 0 and a["clip_path"] is None and a["still_down_seconds"] is None
    assert a["still_down_threshold"] == 10
    b = rows[env.ids["b"]]
    assert b["acknowledged_at"] is None and b["confidence"] is None


def test_notifications_for_one_camera_return_the_new_fields_and_respect_ownership(env):
    r = env.client.get(f"/api/detection-logs/notifications/{env.ids['cam_a']}", headers=env.alice)
    assert r.status_code == 200
    item = r.get_json()[0]
    assert all(k in item for k in NEW_COLUMNS)
    assert env.client.get(f"/api/detection-logs/notifications/{env.ids['cam_b']}", headers=env.alice).status_code == 404
    mine = env.client.get("/api/detection-logs/notifications", headers=env.alice).get_json()
    assert {n["id"] for n in mine} == {env.ids["a"]}


def test_deleting_a_user_who_acknowledged_keeps_the_alert(env):
    # a second administrator (owns no camera, so the existing delete rules allow removing them) acknowledges
    from app.models.user import User, UserRole
    with env.app.app_context():
        boss = User(username="boss", role=UserRole.ADMIN)
        boss.set_password("boss12345")
        env.db.session.add(boss)
        env.db.session.commit()
        boss_id = boss.id
    login = env.client.post("/api/auth/login", json={"username": "boss", "password": "boss12345"})
    boss_headers = {"Authorization": "Bearer " + login.get_json()["access_token"]}
    r = env.client.post(f"/api/detection-logs/notifications/{env.ids['b']}/acknowledge", headers=boss_headers)
    assert r.status_code == 200 and _row(env, "b")[1] == boss_id
    r = env.client.delete(f"/api/admin/users/{boss_id}", headers=env.admin)
    assert r.status_code == 200, r.get_data(as_text=True)
    at, by = _row(env, "b")
    assert at is not None and by is None                       # the alert and its time stay, only the name goes


# ---------------------------------------------------------------- migration

def _legacy_database(path):
    """The notification_history table as it was before step 2, with rows in it."""
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(80), telegram_chat_id VARCHAR(255));
        CREATE TABLE cameras (id INTEGER PRIMARY KEY, name VARCHAR(80));
        CREATE TABLE notification_history (
            id INTEGER PRIMARY KEY, camera_id INTEGER REFERENCES cameras(id), sent_at DATETIME,
            detection_type VARCHAR(32) NOT NULL, image_path VARCHAR(256));
        INSERT INTO users VALUES (1, 'admin', NULL);
        INSERT INTO cameras VALUES (7, 'lobby');
        INSERT INTO notification_history VALUES (1, 7, '2026-10-01 10:00:00', 'fall_red', '/tmp/a.jpg');
        INSERT INTO notification_history VALUES (2, 7, '2026-10-02 11:30:00', 'bed_exit', NULL);
        INSERT INTO notification_history VALUES (3, NULL, '2026-10-03 12:45:00', 'alone_yellow', '/tmp/c.jpg');
    """)
    con.commit()
    con.close()


class _Db:
    def __init__(self, engine):
        self.engine = engine


def test_migration_adds_columns_twice_without_error_and_keeps_the_data(tmp_path):
    from app.db_migrate import ensure_columns

    path = str(tmp_path / "legacy.db")
    _legacy_database(path)
    engine = create_engine("sqlite:///" + path.replace("\\", "/"))
    before = sqlite3.connect(path).execute("SELECT * FROM notification_history ORDER BY id").fetchall()

    first = ensure_columns(_Db(engine))
    assert sorted(first) == sorted("notification_history." + c for c in NEW_COLUMNS)
    names = {c["name"] for c in inspect(engine).get_columns("notification_history")}
    assert set(NEW_COLUMNS) <= names

    second = ensure_columns(_Db(engine))                       # run it again: nothing to do, no error
    third = ensure_columns(_Db(engine))
    assert second == [] and third == []

    con = sqlite3.connect(path)
    after = con.execute("SELECT id, camera_id, sent_at, detection_type, image_path FROM notification_history ORDER BY id").fetchall()
    assert after == before                                     # every original value is untouched
    new_values = con.execute("SELECT " + ",".join(NEW_COLUMNS) + " FROM notification_history").fetchall()
    assert all(v is None for row in new_values for v in row)   # the new columns start out NULL
    con.close()


def test_migration_skips_a_missing_table_and_survives_a_failing_statement(tmp_path):
    from app.db_migrate import ensure_columns

    engine = create_engine("sqlite:///" + str(tmp_path / "empty.db").replace("\\", "/"))
    assert ensure_columns(_Db(engine)) == []                   # no tables at all: nothing to add, no error
    assert ensure_columns(_Db(engine), columns=(("nope", "x", "BAD TYPE ((("),)) == []


def test_application_start_upgrades_a_legacy_database_and_is_repeatable(tmp_path, monkeypatch):
    from app import create_app
    from app.config import Config

    path = str(tmp_path / "legacy.db")
    _legacy_database(path)
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + path.replace("\\", "/"))
    create_app()
    create_app()                                               # a second start (backend + worker) must not error
    con = sqlite3.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(notification_history)")}
    assert set(NEW_COLUMNS) <= cols
    assert con.execute("SELECT COUNT(*) FROM notification_history").fetchone()[0] == 3
    assert con.execute("SELECT image_path FROM notification_history WHERE id = 1").fetchone()[0] == "/tmp/a.jpg"
    con.close()
