"""Plan A step 5: LINE instead of Telegram.

Real Flask app on a throw-away SQLite database. LINE's API is replaced by a fake `requests.post`; nothing leaves the
machine. Covers: a failing or slow send never reaches the detection loop, the webhook signature, the public-edge
filter and the restricted proxy, unguessable picture names, and that the channel token never appears in a response
or in the log.
"""
import base64
import hashlib
import hmac
import http.client
import http.server
import json
import re
import threading
import time

import pytest

TOKEN = "TOKEN-abcdef0123456789-SECRET"
SECRET = "channel-secret-for-tests"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import app as app_pkg
    from app import create_app, db
    from app.config import Config
    from app.models.camera import Camera
    from app.models.line_settings import LineSettings
    from app.models.user import User

    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + str(tmp_path / "t.db").replace("\\", "/"))
    monkeypatch.setattr(Config, "LINE_CHANNEL_SECRET", SECRET)
    monkeypatch.setattr(Config, "LINE_CHANNEL_ACCESS_TOKEN", TOKEN)
    monkeypatch.setattr(Config, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(Config, "ALERT_IMAGE_DIR", str(tmp_path / "alerts"))
    app = create_app()
    monkeypatch.setattr(app_pkg, "_worker_app", app)             # senders use this app, not a new one

    class Env:
        pass

    e = Env()
    e.app, e.tmp, e.Config, e.monkeypatch, e.db = app, tmp_path, Config, monkeypatch, db
    e.client = app.test_client()
    r = e.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    e.admin = {"Authorization": "Bearer " + r.get_json()["access_token"]}
    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        e.admin_id = admin.id
        cam = Camera(name="cam", room_name="room", url="x.mp4", detection_type="fall_v2", user_id=admin.id)
        db.session.add(cam)
        row = LineSettings.get_settings(admin.id)
        row.enabled, row.channel_access_token, row.line_user_id = True, TOKEN, "Uuser0001"
        db.session.commit()
        e.camera_id = cam.id
    yield e


def _signed(body: bytes, secret=SECRET):
    return {"X-Line-Signature": base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode(),
            "Content-Type": "application/json"}


# ------------------------------------------------------------------ sending never reaches the loop

def test_a_slow_line_api_does_not_block_the_caller(env):
    from app.services import line_service
    from app.services.camera_manager import notify_fall_alert

    started = []

    def slow_post(*a, **k):
        started.append(1)
        time.sleep(1.5)

        class R:
            status_code, text = 200, "ok"
        return R()

    env.monkeypatch.setattr(line_service.requests, "post", slow_post)
    t0 = time.monotonic()
    notify_fall_alert(env.camera_id, "cam", "room", "fall_red", None, None, confidence=0.9, notification_id=1)
    assert time.monotonic() - t0 < 0.5


@pytest.mark.parametrize("failure", ["post_raises", "app_raises", "thread_cannot_start"])
def test_sending_failures_never_raise(env, failure):
    from app.services import line_service

    if failure == "post_raises":
        env.monkeypatch.setattr(line_service.requests, "post",
                                lambda *a, **k: (_ for _ in ()).throw(ConnectionError("down " + TOKEN)))
    elif failure == "app_raises":
        env.monkeypatch.setattr("app.get_worker_app", lambda: (_ for _ in ()).throw(RuntimeError("no app " + TOKEN)))
    else:
        env.monkeypatch.setattr(line_service, "Thread", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no thread")))

    # inline and threaded forms: both return without raising
    assert line_service.send_line_message_async(env.camera_id, "c", "r", "fall_red", None, None, wait=True) == 0 \
        or failure == "thread_cannot_start"
    line_service.send_line_message_async(env.camera_id, "c", "r", "fall_red", None, None)


def test_the_alert_row_id_reaches_the_notification(env):
    """_raise_v3_fall_alert saves the row first and hands its id to LINE (the acknowledge button needs it)."""
    import numpy as np
    from app.models.camera import Camera
    from app.models.notification_history import NotificationHistory
    import app.services.camera_manager as cm

    seen = {}
    env.monkeypatch.setattr(cm, "notify_fall_alert", lambda *a, **k: seen.update(k))
    with env.app.app_context():
        cm._raise_v3_fall_alert(Camera.query.get(env.camera_id), np.zeros((20, 20, 3), np.uint8), 0.8, "fall", 1)
        row = NotificationHistory.query.one()
        assert seen["notification_id"] == row.id and seen["confidence"] == 0.8


def test_the_cooldown_is_the_cameras_own():
    import types
    from app.config import Config
    from app.services.camera_manager import _camera_cooldown

    assert _camera_cooldown(types.SimpleNamespace(notification_cooldown=120)) == 120
    assert _camera_cooldown(types.SimpleNamespace(notification_cooldown=None)) == Config.NOTIFICATION_COOLDOWN
    assert _camera_cooldown(types.SimpleNamespace(notification_cooldown=0)) == Config.NOTIFICATION_COOLDOWN


def test_the_message_is_pushed_with_the_users_token_and_never_says_confirmed(env):
    from app.services import line_service

    sent = []

    def post(url, headers=None, json=None, timeout=None):
        sent.append((url, headers, json))

        class R:
            status_code, text = 200, "ok"
        return R()

    env.monkeypatch.setattr(line_service.requests, "post", post)
    n = line_service.send_line_message_async(env.camera_id, "cam", "room", "fall_red", None, None,
                                             confidence=0.77, notification_id=5, wait=True)
    assert n == 1 and sent[0][2]["to"] == "Uuser0001"
    assert sent[0][1]["Authorization"] == "Bearer " + TOKEN
    text = json.dumps(sent[0][2], ensure_ascii=False)
    assert "อาจมีการล้ม" in text and "ตรวจพบคนล้ม" not in text
    # no PUBLIC_BASE_URL -> no button, and the message says where to acknowledge
    assert "template" not in text and "หน้าเว็บ" in text


def test_the_acknowledge_button_needs_both_public_url_and_secret(env):
    from app.services import line_service

    env.monkeypatch.setattr(env.Config, "PUBLIC_BASE_URL", "https://x.example.com")
    msgs = line_service._build_messages("hello", 7, None)
    assert msgs[0]["type"] == "template" and msgs[0]["template"]["actions"][0]["data"] == "ack=7"
    env.monkeypatch.setattr(env.Config, "LINE_CHANNEL_SECRET", "")
    assert line_service._build_messages("hello", 7, None)[0]["type"] == "text"


# ------------------------------------------------------------------ webhook

def test_webhook_rejects_a_wrong_or_missing_signature(env):
    body = json.dumps({"events": []}).encode()
    assert env.client.post("/api/line/webhook", data=body, headers=_signed(body, "wrong")).status_code == 403
    assert env.client.post("/api/line/webhook", data=body).status_code == 403
    assert env.client.post("/api/line/webhook", data=body, headers=_signed(body)).status_code == 200


def test_webhook_refuses_everything_without_a_channel_secret(env):
    env.monkeypatch.setattr(env.Config, "LINE_CHANNEL_SECRET", "")
    body = b'{"events": []}'
    assert env.client.post("/api/line/webhook", data=body, headers=_signed(body, "")).status_code == 403


def test_a_signed_button_press_acknowledges_the_alert(env):
    from app.models.notification_history import NotificationHistory
    from app.services import alert_service

    with env.app.app_context():
        row = alert_service.save_alert_log(env.camera_id, "fall_red", None, confidence=0.9)
        nid = row.id
    replies = []
    import app.routes.line as line_routes
    env.monkeypatch.setattr(line_routes, "_reply", lambda token, messages: replies.append(messages))
    body = json.dumps({"events": [{"type": "postback", "replyToken": "rt", "source": {"type": "user", "userId": "U1"},
                                   "postback": {"data": f"ack={nid}"}}]}).encode()
    assert env.client.post("/api/line/webhook", data=body, headers=_signed(body)).status_code == 200
    with env.app.app_context():
        assert NotificationHistory.query.get(nid).acknowledged_at is not None
    assert replies and "รับทราบแล้ว" in replies[0][0]["text"]


# ------------------------------------------------------------------ public edge filter

def test_public_host_reaches_only_the_webhook_and_the_pictures(env):
    env.monkeypatch.setitem(env.app.config, "PUBLIC_BASE_URL", "https://abc.trycloudflare.com")
    pub = {"base_url": "http://abc.trycloudflare.com"}
    for path in ("/api/auth/login", "/api/cameras", "/api/line/settings", "/api/health", "/videos/x.mp4",
                 "/api/stream/camera/1"):
        assert env.client.get(path, **pub).status_code == 404, path
    assert env.client.post("/api/auth/login", json={}, **pub).status_code == 404
    # the two things LINE needs get through to their own handlers (403 = bad signature, 404 = no such file, not the filter)
    body = b"{}"
    assert env.client.post("/api/line/webhook", data=body, headers=_signed(body, "bad"), **pub).status_code == 403
    # forwarded host is looked at too, and a header can only add the restriction
    assert env.client.get("/api/cameras", headers={"X-Forwarded-Host": "abc.trycloudflare.com"}).status_code == 404
    assert env.client.get("/api/health", headers={"X-Forwarded-Host": "abc.trycloudflare.com, other"}).status_code == 404
    # local requests are untouched
    assert env.client.get("/api/health").status_code == 200
    # a host that merely contains the public name is not the public host
    assert env.client.get("/api/health", base_url="http://abc.trycloudflare.com.evil.example").status_code == 200


def test_the_filter_is_off_without_a_public_url(env):
    assert env.client.get("/api/health", base_url="http://abc.trycloudflare.com").status_code == 200


# ------------------------------------------------------------------ the restricted proxy

class _FakeBackend(http.server.BaseHTTPRequestHandler):
    seen = []

    def _answer(self):
        _FakeBackend.seen.append((self.command, self.path, dict(self.headers)))
        body = b"backend"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_GET = do_HEAD = do_POST = _answer

    def log_message(self, *a):
        pass


@pytest.fixture()
def proxy():
    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location(
        "line_test_proxy", os.path.join(os.path.dirname(__file__), "..", "..", "tools", "line_test_proxy.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeBackend)
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    server = mod.make_server(0, "http://127.0.0.1:%d" % backend.server_address[1])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _FakeBackend.seen.clear()
    yield server.server_address[1]
    server.shutdown()
    backend.shutdown()


def _call(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    r.read()
    c.close()
    return r.status


def test_proxy_refuses_every_path_but_the_two(proxy):
    refused = [
        ("GET", "/"), ("GET", "/api/health"), ("GET", "/api/auth/login"), ("POST", "/api/auth/login"),
        ("GET", "/api/cameras"), ("GET", "/api/stream/camera/1?t=x"), ("GET", "/videos/clip.mp4"),
        ("GET", "/api/line/settings"), ("GET", "/api/line/webhook"), ("POST", "/api/line/webhook/x"),
        ("POST", "/api/alert-images/a.jpg"), ("GET", "/api/alert-images/"), ("GET", "/api/alert-images/a/b.jpg"),
        ("GET", "/api/alert-images/a.jpg?x=1"), ("GET", "/api/alert-images/%2e%2e%2fapp.py"),
        ("PUT", "/api/line/webhook"), ("DELETE", "/api/alert-images/a.jpg"), ("OPTIONS", "/api/line/webhook"),
        ("PATCH", "/api/cameras"),
    ]
    for method, path in refused:
        assert _call(proxy, method, path, body=b"{}" if method in ("POST", "PUT", "PATCH") else None,
                     headers={"Content-Length": "2"} if method in ("POST", "PUT", "PATCH") else {}) == 404, (method, path)
    assert _FakeBackend.seen == []                      # none of them reached the backend


def test_proxy_forwards_the_two_allowed_requests_and_drops_forwarding_headers(proxy):
    assert _call(proxy, "GET", "/api/alert-images/v3_fall_detect_1_17_AbC-_xyz.jpg") == 200
    assert _call(proxy, "HEAD", "/api/alert-images/a.jpg") == 200
    body = b'{"events": []}'
    assert _call(proxy, "POST", "/api/line/webhook", body=body,
                 headers={"Content-Length": str(len(body)), "X-Line-Signature": "sig",
                          "X-Forwarded-Host": "spoof.example", "Authorization": "Bearer x"}) == 200
    methods = [(m, p) for m, p, _ in _FakeBackend.seen]
    assert ("POST", "/api/line/webhook") in methods and len(methods) == 3
    post_headers = {k.lower(): v for k, v in [h for m, p, h in _FakeBackend.seen if m == "POST"][0].items()}
    assert post_headers.get("x-line-signature") == "sig"
    assert "x-forwarded-host" not in post_headers and "authorization" not in post_headers


def test_proxy_refuses_a_webhook_without_a_body_or_a_huge_one(proxy):
    assert _call(proxy, "POST", "/api/line/webhook", body=b"", headers={"Content-Length": "0"}) == 400
    assert _call(proxy, "POST", "/api/line/webhook", body=None, headers={"Content-Length": "5000000"}) == 413


# ------------------------------------------------------------------ picture names

def test_new_picture_names_cannot_be_guessed(env):
    from app.services.alert_service import new_alert_image_path
    import os

    names = {os.path.basename(new_alert_image_path("v3_fall_detect", 7)) for _ in range(50)}
    assert len(names) == 50                                        # same camera, same second: still all different
    for n in names:
        assert re.fullmatch(r"v3_fall_detect_7_\d+_[A-Za-z0-9_\-]{20,}\.jpg", n), n
    assert os.path.isdir(env.Config.ALERT_IMAGE_DIR)


def test_a_new_picture_is_served_under_its_random_name_and_old_names_still_work(env):
    import os
    import numpy as np
    from app.models.camera import Camera
    import app.services.camera_manager as cm

    env.monkeypatch.setattr(cm, "notify_fall_alert", lambda *a, **k: None)
    with env.app.app_context():
        cm._raise_v3_fall_alert(Camera.query.get(env.camera_id), np.zeros((20, 20, 3), np.uint8), 0.8, "fall", 1)
    files = os.listdir(env.Config.ALERT_IMAGE_DIR)
    assert len(files) == 1 and re.search(r"_\d+_[A-Za-z0-9_\-]{20,}\.jpg$", files[0])
    assert env.client.get("/api/alert-images/" + files[0]).status_code == 200
    # a file from before this change keeps its name and is still served
    old = os.path.join(env.Config.ALERT_IMAGE_DIR, "v3_fall_detect_1_1700000000.jpg")
    open(old, "wb").write(open(os.path.join(env.Config.ALERT_IMAGE_DIR, files[0]), "rb").read())
    assert env.client.get("/api/alert-images/v3_fall_detect_1_1700000000.jpg").status_code == 200


# ------------------------------------------------------------------ the token never leaks

def test_settings_response_masks_the_token(env):
    r = env.client.get("/api/line/settings", headers=env.admin)
    assert r.status_code == 200
    assert TOKEN not in r.get_data(as_text=True) and SECRET not in r.get_data(as_text=True)
    data = r.get_json()["data"]
    assert data["has_token"] is True and data["token_preview"] == "..." + TOKEN[-4:]
    assert data["channel_secret_set"] is True


def test_saving_settings_does_not_echo_the_token(env):
    r = env.client.post("/api/line/settings", headers=env.admin, json={"channel_access_token": "NEW-" + TOKEN, "enabled": True})
    assert r.status_code == 200 and ("NEW-" + TOKEN) not in r.get_data(as_text=True)


def test_a_database_error_does_not_put_the_token_in_the_response_or_the_log(env, capsys):
    from app.models.line_settings import LineSettings

    def boom(*a, **k):
        raise RuntimeError("INSERT ... parameters: ('%s',)" % TOKEN)

    env.monkeypatch.setattr(LineSettings, "update_settings", boom)
    r = env.client.post("/api/line/settings", headers=env.admin, json={"enabled": False})
    assert r.status_code == 500 and TOKEN not in r.get_data(as_text=True)
    env.monkeypatch.setattr(LineSettings, "get_settings", boom)
    r = env.client.get("/api/line/settings", headers=env.admin)
    assert r.status_code == 500 and TOKEN not in r.get_data(as_text=True)
    r = env.client.post("/api/line/test", headers=env.admin)
    assert r.status_code == 500 and TOKEN not in r.get_data(as_text=True)
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err


def test_a_failed_push_does_not_log_the_token(env, capsys):
    from app.services import line_service

    def fail(*a, **k):
        raise ConnectionError("cannot reach host with Authorization: Bearer " + TOKEN)

    env.monkeypatch.setattr(line_service.requests, "post", fail)
    assert line_service.send_line_message_async(env.camera_id, "c", "r", "fall_red", None, None, wait=True) == 0

    class Bad:
        status_code, text = 401, '{"message":"Authentication failed"}'
    env.monkeypatch.setattr(line_service.requests, "post", lambda *a, **k: Bad())
    assert line_service.send_line_message_async(env.camera_id, "c", "r", "fall_red", None, None, wait=True) == 0
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err
    assert "401" in out.out


def test_an_ordinary_user_cannot_set_the_bot_token(env):
    r = env.client.post("/api/auth/login", json={"username": "testuser", "password": "user123"})
    user = {"Authorization": "Bearer " + r.get_json()["access_token"]}
    assert env.client.post("/api/line/settings", headers=user, json={"channel_access_token": "X" * 20}).status_code == 403
    assert env.client.get("/api/line/settings", headers=user).get_json()["data"]["discovered_targets"] == []


# ------------------------------------------------------------------ data kept / user delete

def test_deleting_a_user_with_line_settings_works_and_old_tables_stay(env):
    from sqlalchemy import inspect
    from app.models.user import User, UserRole

    r = env.client.post("/api/auth/login", json={"username": "testuser", "password": "user123"})
    user = {"Authorization": "Bearer " + r.get_json()["access_token"]}
    env.client.get("/api/line/settings", headers=user)             # creates that user's line_settings row
    with env.app.app_context():
        uid = User.query.filter_by(username="testuser").first().id
    assert env.client.delete(f"/api/admin/users/{uid}", headers=env.admin).status_code == 200
    with env.app.app_context():
        tables = set(inspect(env.db.engine).get_table_names())
        assert {"telegram_settings", "line_settings", "line_discovered_targets", "notification_history"} <= tables


def test_no_loop_calls_telegram_any_more():
    import app.services.camera_manager as cm
    assert not hasattr(cm, "send_telegram_message_async")
    src = open(cm.__file__, encoding="utf-8").read()
    assert "send_telegram_message_async" not in src
