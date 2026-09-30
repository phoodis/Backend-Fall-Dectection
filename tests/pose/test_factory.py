import subprocess
import sys
from pathlib import Path

import pytest

from pose_extraction.factory import get_pose_extractor


def test_defaults_to_mediapipe(monkeypatch):
    from pose_extraction.mediapipe_extractor import MediaPipePoseExtractor

    monkeypatch.delenv("POSE_BACKEND", raising=False)
    extractor = get_pose_extractor()
    assert isinstance(extractor, MediaPipePoseExtractor)


def test_switches_to_yolo_via_env_var(monkeypatch):
    from pose_extraction.yolo_extractor import YoloPoseExtractor

    class _FakeYOLO:
        def __init__(self, weights_path):
            self.weights_path = weights_path

    monkeypatch.setattr("pose_extraction.yolo_extractor.YOLO", _FakeYOLO)
    monkeypatch.setenv("POSE_BACKEND", "yolo")
    monkeypatch.setenv("POSE_YOLO_WEIGHTS", "yolo11n-pose.pt")

    extractor = get_pose_extractor()
    assert isinstance(extractor, YoloPoseExtractor)


def test_yolo_backend_uses_confirmed_production_defaults(monkeypatch):
    captured = {}

    class _FakeYOLO:
        def __init__(self, weights_path):
            captured["weights_path"] = weights_path

    monkeypatch.setattr("pose_extraction.yolo_extractor.YOLO", _FakeYOLO)
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


# --- lazy-import guarantees (each backend must not require the other's deps) ---

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_importing_factory_module_alone_imports_neither_backend():
    # Needs neither mediapipe/cv2 nor ultralytics/torch installed to run -
    # this is the cheapest possible proof that factory.py's top-level
    # imports stayed lazy. Subprocess so it reflects a fresh import graph.
    script = (
        "import sys\n"
        "import pose_extraction.factory\n"
        "print('pose_extraction.mediapipe_extractor' in sys.modules)\n"
        "print('pose_extraction.yolo_extractor' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd=str(_repo_root()), timeout=30,
    )
    assert result.returncode == 0, f"import failed:\n{result.stdout}\n{result.stderr}"
    assert result.stdout.strip().splitlines() == ["False", "False"], (
        f"importing pose_extraction.factory alone pulled in a backend module:\n{result.stdout}"
    )


def test_mediapipe_backend_does_not_import_yolo_extractor_module(monkeypatch):
    # Needs mediapipe/cv2 installed (we're exercising the real mediapipe
    # path) but must NOT need ultralytics/torch.
    sys.modules.pop("pose_extraction.yolo_extractor", None)
    monkeypatch.setenv("POSE_BACKEND", "mediapipe")

    get_pose_extractor()

    assert "pose_extraction.yolo_extractor" not in sys.modules


def test_yolo_backend_does_not_import_mediapipe_extractor_module(monkeypatch):
    # Needs ultralytics installed (we're exercising the real yolo path, with
    # YOLO() itself faked out) but must NOT need mediapipe/cv2.
    sys.modules.pop("pose_extraction.mediapipe_extractor", None)

    class _FakeYOLO:
        def __init__(self, weights_path):
            pass

    monkeypatch.setattr("pose_extraction.yolo_extractor.YOLO", _FakeYOLO)
    monkeypatch.setenv("POSE_BACKEND", "yolo")

    get_pose_extractor()

    assert "pose_extraction.mediapipe_extractor" not in sys.modules
