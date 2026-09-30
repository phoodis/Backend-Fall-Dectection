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

    CONFIRMED root cause of the train4 real-clip crash (2026-09-30, see
    spec addendum): `model.track()` was called with `source=[frame]` (a
    list). Ultralytics treats a list as a batch of independent sources,
    not one frame, and takes a different internal init path where
    `predictor.trackers` never gets created for that source - the
    `on_predict_postprocess_end` callback then indexes `trackers[0]` and
    crashes. `source=frame` (the bare ndarray) uses the correct
    single-source path. Do not re-wrap this in a list.

    Real fall clips still have frames with zero detections - not an edge
    case, the normal case (Fall_2.mp4 measured 0% detection rate,
    Fall_3.mp4 12.5%, per the Step 2 gate) - and `boxes.id` is legitimately
    `None` exactly then (ByteTrack has nothing to confirm a track for).
    `extract()` treats that, and any other unexpected result shape, as "no
    detection this frame" (an empty list), which flows into
    collect_track_sequences() as an unobserved frame and becomes status
    MISSING in pose_extraction.normalization - never fabricated, always an
    explicit gap. This is now understood to be a genuine edge-case
    safety net, not a workaround for the source=[frame] bug (that bug is
    fixed at its actual source above) - see the consecutive-error guard
    below for why blanket exception-swallowing alone would be dangerous.
    """

    #: If extract() fails this many frames in a row, extract_video() (in
    #: tools/pose_pipeline/extract_dataset.py) aborts the whole video
    #: instead of silently producing a near-empty dataset. A handful of
    #: bad frames is expected and tolerated; a long unbroken run of
    #: failures means something is actually wrong and should surface, not
    #: be swallowed one warning log at a time.
    consecutive_errors: int

    def __init__(self, weights_path: str = "yolo11n-pose.pt", conf: float = 0.25,
                 imgsz: int = 480, device: str = "cpu"):
        self._model = YOLO(weights_path)
        self._conf = conf
        self._imgsz = imgsz
        self._device = device
        self.consecutive_errors = 0

    def extract(self, frame: np.ndarray) -> list:
        try:
            results = self._model.track(
                source=frame,  # NOT [frame] - see class docstring, this was the real bug
                stream=False,
                tracker="bytetrack.yaml",
                conf=self._conf,
                imgsz=self._imgsz,
                device=self._device,
                persist=True,
                verbose=False,
            )
        except Exception:  # noqa: BLE001 - logged and counted, see consecutive_errors
            logger.warning(
                "YoloPoseExtractor: model.track() raised; treating this frame as no detection",
                exc_info=True,
            )
            self.consecutive_errors += 1
            return []

        if not results:
            self.consecutive_errors = 0
            return []

        result = results[0]
        boxes = getattr(result, "boxes", None)
        keypoints = getattr(result, "keypoints", None)
        if boxes is None or keypoints is None:
            self.consecutive_errors = 0
            return []

        try:
            people = self._unpack_result(boxes, keypoints)
        except Exception:  # noqa: BLE001 - same reasoning as above
            logger.warning(
                "YoloPoseExtractor: unexpected result shape while unpacking; "
                "treating this frame as no detection",
                exc_info=True,
            )
            self.consecutive_errors += 1
            return []

        self.consecutive_errors = 0
        return people

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
        # ByteTrack state lives on the model's predictor. CONFIRMED BUG
        # (2026-09-30, real train4 crash, see spec addendum): setting
        # `predictor.trackers = None` here does NOT force re-init on the
        # next call. Ultralytics' own on_predict_start() does:
        #     if hasattr(predictor, "trackers") and persist: return
        # The attribute still exists (it's just None), so with
        # persist=True (required for track_id continuity within a video)
        # this returns immediately WITHOUT rebuilding trackers, leaving
        # predictor.trackers = None. The very next frame's
        # on_predict_postprocess_end does `type(predictor.trackers[0])`,
        # i.e. `None[0]` -> exactly "TypeError: 'NoneType' object is not
        # subscriptable". `del` the attribute instead, so `hasattr(...)`
        # is False and on_predict_start rebuilds it properly regardless of
        # `persist`. Callers processing multiple videos/streams should
        # still prefer a fresh YoloPoseExtractor per video over relying on
        # reset() + reuse (see tools/pose_pipeline/extract_dataset.py) -
        # this fix makes reset() itself no longer a landmine for whoever
        # does call it, it is not an argument for relying on it.
        predictor = getattr(self._model, "predictor", None)
        if predictor is not None and hasattr(predictor, "trackers"):
            del predictor.trackers
        self.consecutive_errors = 0
