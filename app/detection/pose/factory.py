import os

from .base import PoseExtractor
from .mediapipe_extractor import MediaPipePoseExtractor
from .yolo_extractor import YoloPoseExtractor

_YOLO_WEIGHTS_ENV = "POSE_YOLO_WEIGHTS"
_YOLO_CONF_ENV = "POSE_YOLO_CONF"
_YOLO_IMGSZ_ENV = "POSE_YOLO_IMGSZ"

# Confirmed production selection (see spec addendum, 2026-09-30):
# yolo11n-pose.pt at imgsz=480. Gate was only validated at imgsz=1280 -
# that risk is accepted and documented in the spec, not re-litigated here.
_DEFAULT_YOLO_WEIGHTS = "yolo11n-pose.pt"
_DEFAULT_YOLO_CONF = 0.25
_DEFAULT_YOLO_IMGSZ = 480


def get_pose_extractor() -> PoseExtractor:
    # Defaults to mediapipe so nothing changes for any existing caller
    # until POSE_BACKEND is explicitly set (STEP 3A hard constraint).
    backend = os.environ.get("POSE_BACKEND", "mediapipe").strip().lower()

    if backend == "mediapipe":
        return MediaPipePoseExtractor()

    if backend == "yolo":
        weights = os.environ.get(_YOLO_WEIGHTS_ENV, _DEFAULT_YOLO_WEIGHTS)
        conf = float(os.environ.get(_YOLO_CONF_ENV, _DEFAULT_YOLO_CONF))
        imgsz = int(os.environ.get(_YOLO_IMGSZ_ENV, _DEFAULT_YOLO_IMGSZ))
        return YoloPoseExtractor(weights_path=weights, conf=conf, imgsz=imgsz)

    raise ValueError(f"Unknown POSE_BACKEND={backend!r}; expected 'mediapipe' or 'yolo'")
