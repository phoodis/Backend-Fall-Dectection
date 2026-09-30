import logging

import numpy as np
from ultralytics import YOLO

from .base import PoseExtractor, PosePerson

logger = logging.getLogger(__name__)


class YoloPoseExtractor(PoseExtractor):
    """COCO-17 pose extraction via an Ultralytics YOLO-pose model, tracked
    with ByteTrack so falls can be attributed to a stable per-person id.

    Defaults (yolo11n-pose.pt, imgsz=480, conf=0.25) match the production
    config confirmed for this deployment's CPU target - see
    docs/superpowers/specs/2026-09-18-pose-extractor-migration-spec.md.
    The model is loaded once in __init__, not per frame (contrast with
    app/detection/bed_exit.py, which constructs a new
    ort.InferenceSession() every frame - do not replicate that pattern).

    Real fall clips have frames with zero detections - not an edge case,
    the normal case (Fall_2.mp4 measured 0% detection rate, Fall_3.mp4
    12.5%, per the Step 2 gate). `extract()` therefore treats ANY failure
    to produce a usable result - .track() itself raising, .boxes or
    .keypoints missing/None, .boxes.id being None because ByteTrack hasn't
    confirmed a track yet, or any other unexpected shape - as "no
    detection this frame" (an empty list), never a crash. That empty list
    flows into collect_track_sequences() as an unobserved frame and
    ultimately becomes status MISSING in pose_extraction.normalization -
    the same "never fabricate, always make the gap explicit" rule as
    everywhere else in this package. A single bad frame must not abort
    extraction of an entire clip.
    """

    def __init__(self, weights_path: str = "yolo11n-pose.pt", conf: float = 0.25,
                 imgsz: int = 480, device: str = "cpu"):
        self._model = YOLO(weights_path)
        self._conf = conf
        self._imgsz = imgsz
        self._device = device

    def extract(self, frame: np.ndarray) -> list:
        try:
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
        except Exception:  # noqa: BLE001 - one bad frame must not crash the whole clip
            logger.warning(
                "YoloPoseExtractor: model.track() raised; treating this frame as no detection",
                exc_info=True,
            )
            return []

        if not results:
            return []

        result = results[0]
        boxes = getattr(result, "boxes", None)
        keypoints = getattr(result, "keypoints", None)
        if boxes is None or keypoints is None:
            return []

        try:
            return self._unpack_result(boxes, keypoints)
        except Exception:  # noqa: BLE001 - same reasoning as above
            logger.warning(
                "YoloPoseExtractor: unexpected result shape while unpacking; "
                "treating this frame as no detection",
                exc_info=True,
            )
            return []

    @staticmethod
    def _unpack_result(boxes, keypoints) -> list:
        kpts_xy_t = getattr(keypoints, "xy", None)
        if kpts_xy_t is None:
            return []
        kpts_xy = kpts_xy_t.cpu().numpy()
        if kpts_xy.shape[0] == 0:
            return []

        kpts_conf_t = getattr(keypoints, "conf", None)
        kpts_conf = (
            kpts_conf_t.cpu().numpy() if kpts_conf_t is not None
            else np.ones(kpts_xy.shape[:2], dtype=np.float32)
        )

        boxes_xyxy_t = getattr(boxes, "xyxy", None)
        if boxes_xyxy_t is None:
            return []
        boxes_xyxy = boxes_xyxy_t.cpu().numpy()

        # ByteTrack has not always confirmed a track for every detection -
        # boxes.id is None whenever no detection in this frame has a
        # confirmed track yet (not an error condition, the normal case for
        # these clips). Never subscript it without this check.
        ids_t = getattr(boxes, "id", None)
        ids = ids_t.cpu().numpy() if ids_t is not None else None

        # Defensive: never assume keypoints/boxes/ids counts line up exactly.
        n = min(kpts_xy.shape[0], boxes_xyxy.shape[0])

        people = []
        for i in range(n):
            kp = np.concatenate([kpts_xy[i], kpts_conf[i][:, None]], axis=1).astype(np.float32)
            track_id = int(ids[i]) if ids is not None and i < len(ids) else -1
            bbox = boxes_xyxy[i].tolist()
            people.append(PosePerson(track_id=track_id, keypoints=kp, bbox=bbox))

        return people

    def reset(self) -> None:
        # ByteTrack state lives on the model's predictor; drop it so a new
        # video/camera doesn't inherit stale track IDs from a previous one.
        if hasattr(self._model, "predictor") and self._model.predictor is not None:
            self._model.predictor.trackers = None
