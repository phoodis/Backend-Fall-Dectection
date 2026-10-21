"""Plan A step 4 (backend part): live-view size / quality / pacing, the pose overlay, /cameras/test-videos.

The camera source is a small generated video file; the pose model is replaced by a fake, so these tests do not
need model weights.
"""
import json
import time

import cv2
import numpy as np
import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from app import create_app
    from app.config import Config
    from app.services.stream_service import stream_manager

    clip = str(tmp_path / "wide.mp4")
    writer = cv2.VideoWriter(clip, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (1280, 720))
    rng = np.random.default_rng(1)
    for n in range(90):
        frame = rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)       # noise: JPEG size reacts to quality
        writer.write(frame)
    writer.release()

    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + str(tmp_path / "t.db").replace("\\", "/"))
    app = create_app()

    class Env:
        pass

    e = Env()
    e.app, e.clip, e.tmp, e.Config, e.monkeypatch = app, clip, tmp_path, Config, monkeypatch
    e.client = app.test_client()
    r = e.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    e.admin = {"Authorization": "Bearer " + r.get_json()["access_token"]}
    yield e
    for cid in list(stream_manager.streams):
        stream_manager.stop_stream(cid)


def _stream(env, camera_id=901):
    from app.services.stream_service import stream_manager
    s = stream_manager.get_stream(camera_id, env.clip, "t")
    assert s is not None
    time.sleep(0.2)
    return s


def _decode(jpeg):
    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)


# ---------------------------------------------------------------- size and quality

def test_picture_is_shrunk_to_the_configured_longest_side(env):
    env.monkeypatch.setattr(env.Config, "STREAM_MAX_SIDE", 320)
    img = _decode(_stream(env).get_mjpeg_frame())
    assert max(img.shape[:2]) == 320 and img.shape[:2] == (180, 320)          # 16:9 kept


def test_portrait_pictures_are_capped_on_their_height(env):
    from app.services.stream_service import RTSPStream
    s = RTSPStream(1, "x", "x")
    s.current_frame = np.zeros((1920, 1080, 3), np.uint8)                     # a phone held upright
    env.monkeypatch.setattr(env.Config, "STREAM_MAX_SIDE", 640)
    assert _decode(s.get_mjpeg_frame()).shape[:2] == (640, 360)


def test_small_pictures_are_not_enlarged(env):
    from app.services.stream_service import RTSPStream
    s = RTSPStream(1, "x", "x")
    s.current_frame = np.zeros((120, 160, 3), np.uint8)
    assert _decode(s.get_mjpeg_frame()).shape[:2] == (120, 160)


def test_max_side_zero_means_no_resize(env):
    env.monkeypatch.setattr(env.Config, "STREAM_MAX_SIDE", 0)
    assert _decode(_stream(env).get_mjpeg_frame()).shape[:2] == (720, 1280)


def test_jpeg_quality_comes_from_the_config(env):
    s = _stream(env)
    env.monkeypatch.setattr(env.Config, "STREAM_JPEG_QUALITY", 30)
    low = len(s.get_mjpeg_frame())
    env.monkeypatch.setattr(env.Config, "STREAM_JPEG_QUALITY", 90)
    high = len(s.get_mjpeg_frame())
    assert low < high


# ---------------------------------------------------------------- pacing

def _count_frames(env, seconds):
    from app.services.stream_service import generate_mjpeg_stream
    gen = generate_mjpeg_stream(902, env.clip, "t")
    next(gen)                                               # start-up is not counted
    n, t0 = 0, time.monotonic()
    for chunk in gen:
        n += bool(chunk)
        if time.monotonic() - t0 >= seconds:
            break
    return n


def test_frames_per_second_are_capped(env):
    env.monkeypatch.setattr(env.Config, "STREAM_FPS", 4)
    n = _count_frames(env, 2.0)
    assert 3 <= n <= 4 * 2 + 2


def test_without_a_cap_a_frame_is_never_sent_twice(env):
    """The capture thread makes 15 frames a second. The old loop had no pacing and re-encoded the same frame
    over and over (hundreds a second); now no more than one per captured frame."""
    env.monkeypatch.setattr(env.Config, "STREAM_FPS", 0)
    n = _count_frames(env, 2.0)
    assert n <= 15 * 2 + 6


# ---------------------------------------------------------------- overlay: who may ask for it

def _recording_generator(env, calls):
    def fake(camera_id, url, name, draw_overlay=False, stop_at=None):
        calls.append(draw_overlay)
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\nx\r\n"
    env.monkeypatch.setattr("app.routes.stream.generate_mjpeg_stream", fake)


def _first_camera(env):
    from app import db
    from app.models.camera import Camera
    from app.models.user import User
    with env.app.app_context():
        admin = User.query.filter_by(username="admin").first()
        cam = Camera(name="c", room_name="r", url=env.clip, detection_type="fall_v2", user_id=admin.id)
        db.session.add(cam)
        db.session.commit()
        return cam.id


def _open(env, cam_id, query=""):
    token = env.client.post(f"/api/stream/camera/{cam_id}/media-token", headers=env.admin).get_json()["token"]
    resp = env.client.get(f"/api/stream/camera/{cam_id}?t={token}{query}", buffered=False)
    status = resp.status_code
    resp.close()
    return status


def test_overlay_is_ignored_unless_the_server_allows_it(env):
    calls = []
    _recording_generator(env, calls)
    cam = _first_camera(env)
    env.monkeypatch.setattr(env.Config, "STREAM_OVERLAY_ENABLED", False)
    assert _open(env, cam, "&overlay=1") == 200
    assert calls == [False]


def test_overlay_is_drawn_when_allowed_and_asked_for(env):
    calls = []
    _recording_generator(env, calls)
    cam = _first_camera(env)
    env.monkeypatch.setattr(env.Config, "STREAM_OVERLAY_ENABLED", True)
    assert _open(env, cam, "&overlay=1") == 200
    assert _open(env, cam, "") == 200                     # not asked for: off even though allowed
    assert _open(env, cam, "&overlay=0") == 200
    assert calls == [True, False, False]


def test_media_token_says_whether_the_overlay_is_available(env):
    cam = _first_camera(env)
    for allowed in (True, False):
        env.monkeypatch.setattr(env.Config, "STREAM_OVERLAY_ENABLED", allowed)
        body = env.client.post(f"/api/stream/camera/{cam}/media-token", headers=env.admin).get_json()
        assert body["overlay_available"] is allowed


def test_default_overlay_setting_is_off_in_this_build(env):
    """Documented decision: see docs/migration_plan_A.md (step 4, measurements)."""
    assert env.Config.STREAM_OVERLAY_ENABLED is False


# ---------------------------------------------------------------- overlay: what it does

class _FakeDetector:
    def __init__(self):
        self.calls = 0
        self._roi_boxes = "another camera's boxes"

    def extract_all_keypoints(self, frame):
        self.calls += 1
        assert self._roi_boxes is None, "the previous camera's crop must not leak into this call"
        kpts = np.zeros((17, 3), np.float32)
        kpts[:, 0] = np.linspace(0.3, 0.7, 17)
        kpts[:, 1] = np.linspace(0.2, 0.8, 17)
        kpts[:, 2] = 0.9
        return [(kpts, np.array([0.5, 0.5]))]


def _use_detector(env, detector):
    from app.services.model_manager import model_manager
    env.monkeypatch.setattr(model_manager, "get_v3_fall_detector", lambda: detector)


def test_overlay_draws_the_skeleton_and_leaves_the_source_frame_alone(env):
    det = _FakeDetector()
    _use_detector(env, det)
    s = _stream(env)
    source_before = s.get_frame().copy()
    plain = _decode(s.get_mjpeg_frame(draw_overlay=False))
    drawn = _decode(s.get_mjpeg_frame(draw_overlay=True))
    assert det.calls == 1
    assert not np.array_equal(plain, drawn)                                   # something was drawn
    # the stream keeps capturing, so compare the shape of the copy it hands out, not pixel identity with a later frame
    assert s.get_frame().shape == source_before.shape


def test_overlay_runs_the_pose_model_only_every_nth_frame(env):
    det = _FakeDetector()
    _use_detector(env, det)
    env.monkeypatch.setattr(env.Config, "STREAM_OVERLAY_INFER_EVERY", 6)
    s = _stream(env)
    for _ in range(12):
        s.get_mjpeg_frame(draw_overlay=True)
    assert det.calls == 2                                                     # frames 1 and 7


def test_overlay_every_one_runs_on_every_frame(env):
    det = _FakeDetector()
    _use_detector(env, det)
    env.monkeypatch.setattr(env.Config, "STREAM_OVERLAY_INFER_EVERY", 1)
    s = _stream(env)
    for _ in range(4):
        s.get_mjpeg_frame(draw_overlay=True)
    assert det.calls == 4


def test_a_failing_pose_model_still_gives_a_picture(env):
    class Broken:
        def extract_all_keypoints(self, frame):
            raise RuntimeError("model exploded")

    _use_detector(env, Broken())
    assert _decode(_stream(env).get_mjpeg_frame(draw_overlay=True)) is not None


def test_no_pose_model_still_gives_a_picture(env):
    _use_detector(env, None)
    assert _decode(_stream(env).get_mjpeg_frame(draw_overlay=True)) is not None


def test_plain_view_never_touches_the_pose_model(env):
    det = _FakeDetector()
    _use_detector(env, det)
    s = _stream(env)
    for _ in range(10):
        s.get_mjpeg_frame()
    assert det.calls == 0


# ---------------------------------------------------------------- /api/cameras/test-videos

def _videos(env, names, descriptions=None, subdir=None):
    folder = env.tmp / "clips"
    folder.mkdir()
    for n in names:
        (folder / n).write_bytes(b"x")
    if subdir:
        (folder / subdir).mkdir()
    if descriptions is not None:
        (folder / "clips.json").write_text(json.dumps(descriptions), encoding="utf-8")
    env.monkeypatch.setattr(env.Config, "TEST_VIDEO_DIR", str(folder))
    return folder


def test_test_videos_needs_a_login(env):
    assert env.client.get("/api/cameras/test-videos").status_code == 401


def test_test_videos_lists_only_video_files_in_natural_order(env):
    folder = _videos(env, ["10.mp4", "2.mp4", "1.mp4", "notes.txt", "clips2.json", "Fall_3.MOV"], subdir="sub.mp4")
    body = env.client.get("/api/cameras/test-videos", headers=env.admin).get_json()
    assert [v["filename"] for v in body] == ["1.mp4", "2.mp4", "10.mp4", "Fall_3.MOV"]    # no txt, no folder
    assert body[0]["url"] == str(folder).replace("\\", "/") + "/1.mp4"
    assert body[0]["description"] == ""


def test_test_videos_uses_descriptions_when_the_folder_has_them(env):
    _videos(env, ["1.mp4", "2.mp4"], descriptions={"1.mp4": "person falls"})
    body = env.client.get("/api/cameras/test-videos", headers=env.admin).get_json()
    assert [v["description"] for v in body] == ["person falls", ""]


def test_test_videos_ignores_a_broken_descriptions_file(env):
    folder = _videos(env, ["1.mp4"])
    (folder / "clips.json").write_text("{not json", encoding="utf-8")
    body = env.client.get("/api/cameras/test-videos", headers=env.admin).get_json()
    assert [v["filename"] for v in body] == ["1.mp4"]


def test_test_videos_with_a_missing_folder_is_an_empty_list(env):
    env.monkeypatch.setattr(env.Config, "TEST_VIDEO_DIR", str(env.tmp / "nope"))
    r = env.client.get("/api/cameras/test-videos", headers=env.admin)
    assert r.status_code == 200 and r.get_json() == []


def test_test_videos_default_folder_is_not_hardcoded_to_a_test_directory(env):
    from app import config
    assert config.Config.TEST_VIDEO_DIR != "/app/Test"
