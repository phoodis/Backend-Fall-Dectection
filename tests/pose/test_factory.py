import pytest

from app.detection.pose.factory import get_pose_extractor
from app.detection.pose.mediapipe_extractor import MediaPipePoseExtractor
from app.detection.pose.yolo_extractor import YoloPoseExtractor


def test_defaults_to_mediapipe(monkeypatch):
    monkeypatch.delenv("POSE_BACKEND", raising=False)
    extractor = get_pose_extractor()
    assert isinstance(extractor, MediaPipePoseExtractor)


def test_switches_to_yolo_via_env_var(monkeypatch):
    class _FakeYOLO:
        def __init__(self, weights_path):
            self.weights_path = weights_path

    monkeypatch.setattr("app.detection.pose.yolo_extractor.YOLO", _FakeYOLO)
    monkeypatch.setenv("POSE_BACKEND", "yolo")
    monkeypatch.setenv("POSE_YOLO_WEIGHTS", "yolo11n-pose.pt")

    extractor = get_pose_extractor()
    assert isinstance(extractor, YoloPoseExtractor)


def test_yolo_backend_uses_confirmed_production_defaults(monkeypatch):
    captured = {}

    class _FakeYOLO:
        def __init__(self, weights_path):
            captured["weights_path"] = weights_path

    monkeypatch.setattr("app.detection.pose.yolo_extractor.YOLO", _FakeYOLO)
    monkeypatch.setenv("POSE_BACKEND", "yolo")
    monkeypatch.delenv("POSE_YOLO_WEIGHTS", raising=False)
    monkeypatch.delenv("POSE_YOLO_CONF", raising=False)
    monkeypatch.delenv("POSE_YOLO_IMGSZ", raising=False)

    extractor = get_pose_extractor()

    assert captured["weights_path"] == "yolo11n-pose.pt"
    assert extractor._conf == 0.25
    assert extractor._imgsz == 480


def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("POSE_BACKEND", "not-a-backend")
    with pytest.raises(ValueError):
        get_pose_extractor()
