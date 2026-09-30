import numpy as np
from ultralytics import YOLO

from .base import PoseExtractor, PosePerson


class YoloPoseExtractor(PoseExtractor):
    """COCO-17 pose extraction via an Ultralytics YOLO-pose model, tracked
    with ByteTrack so falls can be attributed to a stable per-person id.

    Defaults (yolo11n-pose.pt, imgsz=480, conf=0.25) match the production
    config confirmed for this deployment's CPU target - see
    docs/superpowers/specs/2026-09-18-pose-extractor-migration-spec.md.
    The model is loaded once in __init__, not per frame (contrast with
    app/detection/bed_exit.py, which constructs a new
    ort.InferenceSession() every frame - do not replicate that pattern).
    """

    def __init__(self, weights_path: str = "yolo11n-pose.pt", conf: float = 0.25,
                 imgsz: int = 480, device: str = "cpu"):
        self._model = YOLO(weights_path)
        self._conf = conf
        self._imgsz = imgsz
        self._device = device

    def extract(self, frame: np.ndarray) -> list:
        results = self._model.track(
            source=[frame],
            stream=False,
            tracker="bytetrack.yaml",
            conf=self._conf,
            imgsz=self._imgsz,
            device=self._device,
            persist=True,
            verbose=False,
        )

        people = []
        if not results:
            return people

        result = results[0]
        if result.keypoints is None or result.boxes is None:
            return people

        kpts_xy = result.keypoints.xy.cpu().numpy()
        kpts_conf = result.keypoints.conf
        kpts_conf = (
            kpts_conf.cpu().numpy() if kpts_conf is not None
            else np.ones(kpts_xy.shape[:2], dtype=np.float32)
        )
        boxes_xyxy = result.boxes.xyxy.cpu().numpy()
        ids = result.boxes.id
        ids = ids.cpu().numpy() if ids is not None else None

        for i in range(kpts_xy.shape[0]):
            keypoints = np.concatenate(
                [kpts_xy[i], kpts_conf[i][:, None]], axis=1
            ).astype(np.float32)
            # ByteTrack may not assign an id every frame - keep the
            # detection rather than dropping it (STEP 3A hard constraint).
            track_id = int(ids[i]) if ids is not None else -1
            bbox = boxes_xyxy[i].tolist()
            people.append(PosePerson(track_id=track_id, keypoints=keypoints, bbox=bbox))

        return people

    def reset(self) -> None:
        # ByteTrack state lives on the model's predictor; drop it so a new
        # video/camera doesn't inherit stale track IDs from a previous one.
        if hasattr(self._model, "predictor") and self._model.predictor is not None:
            self._model.predictor.trackers = None
