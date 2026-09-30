import cv2
import mediapipe as mp
import numpy as np

from .base import PoseExtractor, PosePerson


class MediaPipePoseExtractor(PoseExtractor):
    """Wraps the existing MediaPipe pose path unchanged, INCLUDING the
    landmark[:17] slicing defect (face + arms, no legs - see spec). Kept
    for the 'with legs vs without legs' ablation study. Do not fix the
    slicing here; that is the whole point of keeping this class around.
    """

    def __init__(self, min_detection_confidence: float = 0.5, model_complexity: int = 1):
        self._pose = mp.solutions.pose.Pose(
            static_image_mode=False,
            model_complexity=model_complexity,
            enable_segmentation=False,
            min_detection_confidence=min_detection_confidence,
        )

    def extract(self, frame: np.ndarray) -> list:
        h, w = frame.shape[:2]
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._pose.process(frame_rgb)

        if not results.pose_landmarks:
            return []

        landmarks = results.pose_landmarks.landmark[:17]
        keypoints = np.zeros((17, 3), dtype=np.float32)
        xs, ys = [], []
        for i, lm in enumerate(landmarks):
            px, py = lm.x * w, lm.y * h
            keypoints[i] = (px, py, lm.visibility)
            xs.append(px)
            ys.append(py)

        bbox = [min(xs), min(ys), max(xs), max(ys)]
        return [PosePerson(track_id=0, keypoints=keypoints, bbox=bbox)]
