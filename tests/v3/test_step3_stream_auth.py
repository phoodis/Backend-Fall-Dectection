"""Plan A step 3: media token + authorisation of every /api/stream route + fail-closed logout.

Real Flask app on a throw-away SQLite database; the camera source is a small video file so the live view
really streams.
"""
import time

import cv2
import numpy as np
import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from app import create_app, db
    from app.config import Config
    from app.models.camera import Camera
    from app.models.user import User, UserRole
    from app.services.stream_service import stream_manager

    clip = str(tmp_path / "clip.mp4")
    writer = cv2.VideoWriter(clip, cv2.VideoWriter_fourcc(*"mp4v"), 24.0, (64, 48))
    for n in range(240):
        writer.write(np.full((48, 64, 3), (n * 3) % 256, dtype=np.uint8))
    writer.release()

    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + str(tmp_path / "t.db").replace("\\", "/"))
    app = create_app()

    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        alice = User.query.filter_by(username="testuser").first()
        bob = User(username="bob", role=UserRole.USER)
        bob.set_password("bob12345")
        db.session.add(bob)
        db.session.commit()
        cam_a = Camera(name="a", room_name="r", url=clip, detection_type="fall_v2", user_id=alice.id)
        cam_b = Camera(name="b", room_name="r", url=clip, detection_type="fall_v2", user_id=bob.id)
        db.session.add_all([cam_a, cam_b])
        db.session.commit()
        ids = dict(a=cam_a.id, b=cam_b.id, admin=admin.id, alice=alice.id, bob=bob.id)

    client = app.test_client()

    class Env:
        pass

    e = Env()
    e.app, e.client, e.ids, e.db = app, client, ids, db

    def login(username, password):
        r = client.post("/api/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200
        body = r.get_json()
        return {"Authorization": "Bearer " + body["access_token"]}, body["access_token"], body["refresh_token"]

    e.login = login
    e.admin, e.admin_jwt, _ = login("admin", "admin123")
    e.alice, e.alice_jwt, e.alice_refresh = login("testuser", "user123")
    e.bob, e.bob_jwt, _ = login("bob", "bob12345")

    def media_token(headers, key):
        r = client.post(f"/api/stream/camera/{ids[key]}/media-token", headers=headers)
        assert r.status_code == 200, r.get_data(as_text=True)
        return r.get_json()["token"]

    e.media_token = media_token
    yield e
    for cid in (ids["a"], ids["b"]):
        stream_manager.stop_stream(cid)


def _first_chunk(client, url):
    resp = client.get(url, buffered=False)
    try:
        if resp.status_code != 200:
            return resp.status_code, b""
        return 200, next(iter(resp.response))
    finally:
        resp.close()


# ---------------------------------------------------------------- the live view itself

def test_stream_without_a_token_is_401(env):
    assert env.client.get(f"/api/stream/camera/{env.ids['a']}").status_code == 401
    assert env.client.get(f"/api/stream/camera/{env.ids['a']}?t=").status_code == 401
    assert env.client.get(f"/api/stream/camera/{env.ids['a']}?t=garbage").status_code == 401


def test_owner_streams_with_a_media_token(env):
    token = env.media_token(env.alice, "a")
    status, chunk = _first_chunk(env.client, f"/api/stream/camera/{env.ids['a']}?t={token}")
    assert status == 200 and chunk.startswith(b"--frame")


def test_admin_can_view_every_camera(env):
    for key in ("a", "b"):
        token = env.media_token(env.admin, key)
        status, chunk = _first_chunk(env.client, f"/api/stream/camera/{env.ids[key]}?t={token}")
        assert status == 200 and chunk.startswith(b"--frame"), key


def test_user_cannot_get_a_media_token_for_someone_elses_camera(env):
    r = env.client.post(f"/api/stream/camera/{env.ids['b']}/media-token", headers=env.alice)
    assert r.status_code == 403
    assert env.client.post("/api/stream/camera/999999/media-token", headers=env.alice).status_code == 404
    assert env.client.post(f"/api/stream/camera/{env.ids['a']}/media-token").status_code == 401


def test_token_for_camera_a_does_not_open_camera_b(env):
    token = env.media_token(env.admin, "a")
    assert env.client.get(f"/api/stream/camera/{env.ids['b']}?t={token}").status_code == 401


def test_expired_media_token_is_refused(env, monkeypatch):
    from app.services import media_token
    token = env.media_token(env.alice, "a")
    monkeypatch.setattr(media_token, "START_SECONDS", -1)      # every token is now older than the allowed age
    assert env.client.get(f"/api/stream/camera/{env.ids['a']}?t={token}").status_code == 401


def test_login_jwt_in_the_url_is_refused(env):
    url = f"/api/stream/camera/{env.ids['a']}"
    assert env.client.get(f"{url}?token={env.alice_jwt}").status_code == 401      # the old style
    assert env.client.get(f"{url}?t={env.alice_jwt}").status_code == 401          # a JWT is not a media token
    assert env.client.get(url, headers=env.alice).status_code == 401              # nor is the header on this route


def test_media_token_is_not_a_login(env):
    token = env.media_token(env.alice, "a")
    r = env.client.get("/api/cameras", headers={"Authorization": "Bearer " + token})
    assert r.status_code in (401, 422)


def test_media_token_stops_working_when_the_camera_changes_owner(env):
    from app.models.camera import Camera
    token = env.media_token(env.alice, "a")
    with env.app.app_context():
        env.db.session.get(Camera, env.ids["a"]).user_id = env.ids["bob"]
        env.db.session.commit()
    assert env.client.get(f"/api/stream/camera/{env.ids['a']}?t={token}").status_code == 404


def test_view_ends_at_the_deadline(env, monkeypatch):
    from app.services import media_token
    monkeypatch.setattr(media_token, "view_deadline", lambda seconds=0: time.monotonic() + 1.5)
    token = env.media_token(env.alice, "a")
    started = time.monotonic()
    resp = env.client.get(f"/api/stream/camera/{env.ids['a']}?t={token}", buffered=False)
    chunks = 0
    for _ in resp.response:                                     # runs until the server ends the view
        chunks += 1
        assert time.monotonic() - started < 20
    resp.close()
    assert chunks >= 1 and time.monotonic() - started < 15


def test_live_view_carries_no_cors_headers_but_the_api_still_does(env):
    token = env.media_token(env.alice, "a")
    resp = env.client.get(f"/api/stream/camera/{env.ids['a']}?t={token}", headers={"Origin": "http://evil.example"},
                          buffered=False)
    try:
        assert resp.status_code == 200 and "Access-Control-Allow-Origin" not in resp.headers
    finally:
        resp.close()
    api = env.client.get("/api/cameras", headers=dict(env.alice, Origin="http://localhost:3000"))
    assert api.headers.get("Access-Control-Allow-Origin") in ("*", "http://localhost:3000")


def test_media_token_is_redacted_from_log_lines():
    from app.services.media_token import redact
    assert "SECRET" not in redact('GET /api/stream/camera/1?t=SECRET HTTP/1.1')
    assert "SECRET" not in redact('GET /api/stream/camera/1?%74=SECRET HTTP/1.1')
    assert "SECRET" not in redact('GET /api/stream/camera/1?overlay=1&token=SECRET HTTP/1.1')


# ---------------------------------------------------------------- every other stream route

JSON_ROUTES = [
    ("POST", "/api/stream/camera/{id}/start"),
    ("POST", "/api/stream/camera/{id}/stop"),
    ("GET", "/api/stream/camera/{id}/status"),
    ("GET", "/api/stream/camera/{id}/test"),
    ("POST", "/api/stream/camera/{id}/media-token"),
]


@pytest.mark.parametrize("method, path", JSON_ROUTES)
def test_camera_routes_need_a_login_and_ownership(env, method, path):
    own, foreign = path.format(id=env.ids["a"]), path.format(id=env.ids["b"])
    assert env.client.open(own, method=method).status_code == 401                        # no token
    assert env.client.open(own, method=method, headers=env.alice).status_code in (200, 400)   # owner
    assert env.client.open(foreign, method=method, headers=env.alice).status_code == 403  # somebody else's
    assert env.client.open(path.format(id=999999), method=method, headers=env.alice).status_code == 404
    assert env.client.open(foreign, method=method, headers=env.admin).status_code in (200, 400)  # admin: any camera


def test_stats_without_a_token_is_401_and_is_scoped_to_the_caller(env):
    from app.services.stream_service import stream_manager
    assert env.client.get("/api/stream/stats").status_code == 401
    stream_manager.get_stream(env.ids["a"], "x", "a")
    stream_manager.get_stream(env.ids["b"], "x", "b")
    time.sleep(0.5)
    mine = env.client.get("/api/stream/stats", headers=env.alice).get_json()
    assert {s["camera_id"] for s in mine["streams"]} <= {env.ids["a"]} and "total_system_streams" not in mine
    everything = env.client.get("/api/stream/stats", headers=env.admin).get_json()
    assert {env.ids["a"], env.ids["b"]} >= {s["camera_id"] for s in everything["streams"]}


def test_cleanup_is_admin_only(env):
    assert env.client.post("/api/stream/cleanup").status_code == 401
    assert env.client.post("/api/stream/cleanup", headers=env.alice).status_code == 403
    assert env.client.post("/api/stream/cleanup", headers=env.admin).status_code == 200


# ---------------------------------------------------------------- logout, revocation, fail-closed

def test_logout_revokes_the_session_and_its_media_tokens(env):
    token = env.media_token(env.alice, "a")
    assert env.client.get(f"/api/stream/camera/{env.ids['a']}?t={token}", buffered=False).status_code == 200
    assert env.client.post("/api/auth/logout", headers=env.alice).status_code == 200
    assert env.client.get(f"/api/stream/camera/{env.ids['a']}?t={token}").status_code == 401   # the media token
    assert env.client.get("/api/auth/verify", headers=env.alice).status_code == 401              # the login token
    assert env.client.post(f"/api/stream/camera/{env.ids['a']}/media-token", headers=env.alice).status_code == 401


def test_logout_that_cannot_record_the_revocation_says_so(env, monkeypatch):
    from app.models.token_blocklist import TokenBlocklist
    monkeypatch.setattr(TokenBlocklist, "add_token_to_blacklist", classmethod(lambda cls, *a, **k: False))
    r = env.client.post("/api/auth/logout", headers=env.alice)
    assert r.status_code == 500 and "still valid" in r.get_json()["error"]
    r = env.client.post("/api/auth/logout-all", headers=env.alice)
    assert r.status_code == 500


def test_a_broken_blocklist_lookup_refuses_instead_of_allowing(env, monkeypatch):
    from app.models.token_blocklist import TokenBlocklist

    from flask_sqlalchemy.query import Query

    def boom(self, **kw):
        raise RuntimeError("database down")

    monkeypatch.setattr(Query, "filter_by", boom)             # every filter_by now fails, as in a database fault
    with env.app.app_context():
        assert TokenBlocklist.is_jti_blacklisted("anything") is True
    assert env.client.get("/api/auth/verify", headers=env.alice).status_code == 401
    token_url = f"/api/stream/camera/{env.ids['a']}?t=whatever"
    assert env.client.get(token_url).status_code == 401


def test_logout_does_not_revoke_the_refresh_token_known_gap(env):
    """Characterisation, not an endorsement: the browser sends only the access token on logout, so the refresh token
    of that login keeps working until it expires. It can mint a new access token (and with it new media tokens).
    If logout is later made to revoke the whole session, this test should fail and be rewritten."""
    assert env.client.post("/api/auth/logout", headers=env.alice).status_code == 200
    r = env.client.post("/api/auth/refresh", headers={"Authorization": "Bearer " + env.alice_refresh})
    assert r.status_code == 200 and r.get_json()["access_token"]


def test_logout_all_only_revokes_the_token_it_is_called_with_known_gap(env):
    """Characterisation: despite its name, logout-all blocks just the presented token; another login of the same
    user stays valid. Same as the friend's backend."""
    other, _, _ = env.login("testuser", "user123")
    assert env.client.post("/api/auth/logout-all", headers=env.alice).status_code == 200
    assert env.client.get("/api/auth/verify", headers=env.alice).status_code == 401
    assert env.client.get("/api/auth/verify", headers=other).status_code == 200
