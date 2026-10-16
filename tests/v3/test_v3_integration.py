"""v3 fall detector wiring: configuration defaults, detector switch, and source-time sampling of files.

These tests do not load any model: the detector is a stub, so they run in seconds. The numerical
behaviour of the detector itself is covered by tools/v3_eval_via_camera_manager.py (replay of the
labelled clips against the evaluation results).
"""
import os
import subprocess
import sys

import cv2
import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _StubDetector:
    """Stands in for V3PoseFallDetector: only what V3FallRunner touches outside step()."""

    def __init__(self):
        self.resets = 0

    def reset_roi_state(self, phase=0):
        self.resets += 1


@pytest.fixture(scope="module")
def cm():
    import app.services.camera_manager as camera_manager
    return camera_manager


@pytest.fixture()
def clip(tmp_path):
    """60 frames at 24 fps; frame n has pixel value n so the frame read can be identified."""
    path = str(tmp_path / "clip.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 24.0, (64, 48))
    for n in range(60):
        writer.write(np.full((48, 64, 3), n * 4, dtype=np.uint8))
    writer.release()
    return path


def _indices(cm, path, target_fps):
    cap = cv2.VideoCapture(path)
    src_fps = cap.get(cv2.CAP_PROP_FPS)
    det = _StubDetector()
    runner = cm.V3FallRunner(det, src_fps, True, target_fps=target_fps, realtime=False)
    out = []
    while True:
        ok, _frame, idx = runner.read(cap)
        if not ok:
            break
        out.append(idx)
    cap.release()
    return out, runner, det


def test_file_is_sampled_by_source_time_at_8fps(cm, clip):
    idx, _, _ = _indices(cm, clip, 8.0)
    assert idx == [3 * n for n in range(20)]          # 24 fps / 8 fps -> every third source frame


def test_target_fps_zero_classifies_every_frame(cm, clip):
    idx, _, _ = _indices(cm, clip, 0.0)
    assert idx == list(range(60))


def test_target_fps_defaults_to_environment(cm, clip, monkeypatch):
    monkeypatch.setenv("V3_TARGET_FPS", "12")
    cap = cv2.VideoCapture(clip)
    runner = cm.V3FallRunner(_StubDetector(), cap.get(cv2.CAP_PROP_FPS), True, realtime=False)
    cap.release()
    assert runner.target_fps == 12.0 and runner.min_period == pytest.approx(1 / 12)


def test_reset_clears_position_and_resets_crop_state(cm, clip):
    cap = cv2.VideoCapture(clip)
    det = _StubDetector()
    runner = cm.V3FallRunner(det, cap.get(cv2.CAP_PROP_FPS), True, target_fps=8.0, realtime=False)
    assert det.resets == 1                             # reset on construction
    for _ in range(5):
        runner.read(cap)
    first_state = runner.state
    runner.reset()                                     # what the loop does when a file wraps to frame 0
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    assert det.resets == 2
    assert runner.state is not first_state
    assert runner.source_index == 0 and runner.source_pos == 0
    ok, _frame, idx = runner.read(cap)
    assert ok and idx == 0
    cap.release()


@pytest.mark.parametrize("setting, expected", [
    ("v2", "legacy"), ("V2", "legacy"), (" v2 ", "legacy"),
    ("v3", "v3"), ("", "v3"), ("nonsense", "v3"),
])
def test_fall_detector_switch(cm, monkeypatch, setting, expected):
    calls = []
    monkeypatch.setattr(cm, "_process_v2_fall_detection_legacy", lambda cid, cfg: calls.append("legacy"))
    monkeypatch.setattr(cm, "_process_v3_fall_detection", lambda cid, cfg: calls.append("v3"))
    monkeypatch.setattr(cm.Config, "FALL_DETECTOR", setting)
    cm.process_v2_fall_detection.run(1, {})
    assert calls == [expected]


def test_evaluated_profile_is_applied_when_nothing_is_set():
    env = {k: v for k, v in os.environ.items() if not k.startswith("V3_") and k != "FALL_DETECTOR"}
    code = ("import os, app.config as c; "
            "print({k: os.environ[k] for k in sorted(c.V3_EVALUATED_PROFILE)}); print(c.Config.FALL_DETECTOR)")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-500:]
    profile, detector = out.stdout.strip().splitlines()[-2:]
    assert eval(profile) == {
        "V3_CLASSIFIER": "fall_classifier_v3.onnx", "V3_IMGSZ": "320", "V3_PARTIAL_MIN": "4",
        "V3_POSE_MODEL": "yolo26s-pose.pt", "V3_PREPROCESS": "auto", "V3_PREPROCESS_DARK_BELOW": "70",
        "V3_ROI_FULL_EVERY": "8", "V3_ROI_IMGSZ": "256", "V3_TARGET_FPS": "8", "V3_THRESHOLD": "0.65"}
    assert detector == "v3"


def test_environment_overrides_the_evaluated_profile():
    env = dict(os.environ, V3_IMGSZ="640", FALL_DETECTOR="v2")
    code = "import os, app.config as c; print(os.environ['V3_IMGSZ'], c.Config.FALL_DETECTOR)"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip().splitlines()[-1] == "640 v2"
