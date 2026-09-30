"""One Euro Filter (Casiez, Roussel, Vogel 2012), applied per keypoint
coordinate trajectory. Chosen over a moving average because it adapts to
velocity: stable when the subject is still, responsive when the subject
moves fast - a moving average would smear the fall itself and make it
appear slower than it was, which is exactly the signal the classifier
depends on.

Operates on the output of pose_extraction.normalization.normalize_sequence
(already translated, scaled, and gap-filled - NaN only remains where a
keypoint's status is MISSING for the whole track). Smoothing never changes
which values are real; it only adjusts already-present numbers, so no
status mask is produced or needed here - reuse the one normalize_sequence
already returned.

Dependency-light by design: numpy only.
"""
import math

import numpy as np


class _LowPassFilter:
    def __init__(self):
        self.initialized = False
        self._y = 0.0

    def filter(self, x: float, alpha: float) -> float:
        if not self.initialized:
            self._y = x
            self.initialized = True
        else:
            self._y = alpha * x + (1.0 - alpha) * self._y
        return self._y


class OneEuroFilter:
    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.007, d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x_filter = _LowPassFilter()
        self._dx_filter = _LowPassFilter()
        self._last_t = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def filter(self, x: float, t: float) -> float:
        dt = 1.0 / 30.0 if self._last_t is None else max(t - self._last_t, 1e-6)
        self._last_t = t

        dx = 0.0 if not self._x_filter.initialized else (x - self._x_filter._y) / dt
        edx = self._dx_filter.filter(dx, self._alpha(self.d_cutoff, dt))

        cutoff = self.min_cutoff + self.beta * abs(edx)
        return self._x_filter.filter(x, self._alpha(cutoff, dt))


def smooth_sequence(sequence: np.ndarray, fps: float,
                     min_cutoff: float = 1.0, beta: float = 0.007) -> np.ndarray:
    """(T,17,3) normalized sequence -> same shape, x/y trajectories smoothed
    independently per keypoint. Confidence channel passes through unchanged.
    NaN values (a keypoint MISSING for the whole track, per
    pose_extraction.normalization) are skipped, not smoothed - smoothing
    never manufactures a value where normalize_sequence explicitly left
    one absent.
    """
    smoothed = sequence.copy()
    timestamps = np.arange(sequence.shape[0]) / fps

    for kp in range(sequence.shape[1]):
        for coord in (0, 1):
            f = OneEuroFilter(min_cutoff=min_cutoff, beta=beta)
            for frame_idx in range(sequence.shape[0]):
                value = sequence[frame_idx, kp, coord]
                if np.isnan(value):
                    continue
                smoothed[frame_idx, kp, coord] = f.filter(float(value), float(timestamps[frame_idx]))

    return smoothed
