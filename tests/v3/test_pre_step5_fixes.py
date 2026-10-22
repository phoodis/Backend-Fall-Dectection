"""Fixes made between step 4 and step 5: the score stored with a v3 alert."""
import numpy as np

from app.detection import v3_fall_detection as v3


class FakeDetector:
    """predict_window returns the scripted scores one by one."""

    def __init__(self, scores):
        self.scores = list(scores)

    def predict_window(self, window):
        return self.scores.pop(0)


def _feed(state, detector, count, threshold=0.65):
    out = []
    for _ in range(count):
        kpts = np.random.default_rng(0).random((v3.NUM_KEYPOINTS, 3)).astype(np.float32)
        out.append(v3._step_person(kpts, True, state, detector, threshold))
    return out


def test_alert_score_is_the_window_that_crossed_the_threshold(monkeypatch):
    """0.80 flags the person; the next window scores 0.44 but the 1-of-3 smoothing keeps the alert up.
    The stored score must be 0.80, not the 0.44 of the current window."""
    monkeypatch.setattr(v3, "SMOOTH_NEED", 1)
    monkeypatch.setattr(v3, "STRIDE", 1)
    monkeypatch.setattr(v3, "PARTIAL_MIN", 1)
    state = v3.V3FallDetectionState()
    results = _feed(state, FakeDetector([0.80, 0.44]), 2)

    detected, probability, _ = results[-1]
    assert detected is True               # decision unchanged by the fix
    assert probability == 0.44            # what the detector returns for this window, unchanged
    assert state.trigger_probability(probability) == 0.80


def test_trigger_probability_falls_back_when_no_window_crossed():
    state = v3.V3FallDetectionState()
    assert state.trigger_probability(0.31) == 0.31


def test_runner_alert_confidence_uses_the_tracked_person():
    from app.services.camera_manager import V3FallRunner

    runner = V3FallRunner.__new__(V3FallRunner)
    runner.state = v3.V3MultiPersonFallState()
    person = runner.state.person_states.setdefault(7, v3.V3FallDetectionState())
    person.recent_probs.extend([(0.91, True), (0.40, False)])

    assert runner.alert_confidence((7, True, 0.40, "fall", None)) == 0.91
    # a track that no longer exists keeps the score it was given
    assert runner.alert_confidence((99, True, 0.52, "fall", None)) == 0.52
