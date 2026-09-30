from abc import ABC, abstractmethod

import numpy as np


class PosePerson:
    """One detected person in one frame.

    keypoints: ndarray shape (17, 3) -> (x, y, confidence), pixel coords.
    bbox: [x1, y1, x2, y2], pixel coords.
    """

    __slots__ = ("track_id", "keypoints", "bbox")

    def __init__(self, track_id: int, keypoints: np.ndarray, bbox: list):
        self.track_id = track_id
        self.keypoints = keypoints
        self.bbox = bbox

    def __repr__(self) -> str:
        return f"PosePerson(track_id={self.track_id}, bbox={self.bbox})"


class PoseExtractor(ABC):
    @abstractmethod
    def extract(self, frame: np.ndarray) -> list:
        """Return a list of PosePerson found in this frame."""
        raise NotImplementedError

    def reset(self) -> None:
        """Clear any per-track state (tracker history, smoothing filters).
        Default no-op; override where relevant (e.g. YoloPoseExtractor).
        """
        return None
