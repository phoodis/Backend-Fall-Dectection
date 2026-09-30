import numpy as np

from pose_extraction.normalization import MISSING, normalize_sequence
from pose_extraction.smoothing import OneEuroFilter, smooth_sequence


def test_one_euro_filter_reduces_jitter_on_a_still_signal():
    rng = np.random.default_rng(0)
    noisy = 1.0 + rng.normal(scale=0.05, size=100)
    timestamps = np.arange(100) / 30.0

    f = OneEuroFilter(min_cutoff=1.0, beta=0.007)
    filtered = [f.filter(float(x), float(t)) for x, t in zip(noisy, timestamps)]

    assert np.std(filtered[20:]) < np.std(noisy[20:])


def test_one_euro_filter_tracks_a_fast_step_without_large_lag():
    # A step change (simulating the moment of a fall) should be reached
    # quickly, not smeared out over many frames like a moving average would.
    timestamps = np.arange(60) / 30.0
    signal = np.array([0.0] * 30 + [1.0] * 30)

    f = OneEuroFilter(min_cutoff=1.0, beta=0.5)
    filtered = [f.filter(float(x), float(t)) for x, t in zip(signal, timestamps)]

    assert filtered[35] > 0.8  # within ~5 frames of the step


def test_smooth_sequence_preserves_shape_and_skips_nan():
    sequence = np.zeros((10, 17, 3), dtype=np.float32)
    sequence[:, :, 2] = 1.0
    sequence[3, 5, 0] = np.nan

    smoothed = smooth_sequence(sequence, fps=30.0)

    assert smoothed.shape == sequence.shape
    assert np.isnan(smoothed[3, 5, 0])


def test_smooth_sequence_leaves_confidence_channel_untouched():
    sequence = np.zeros((10, 17, 3), dtype=np.float32)
    sequence[:, :, 2] = np.linspace(0.1, 0.9, 10)[:, None]

    smoothed = smooth_sequence(sequence, fps=30.0)

    assert np.array_equal(smoothed[:, :, 2], sequence[:, :, 2])


def test_composes_with_normalize_sequence_output_without_crashing():
    # End-to-end: normalize_sequence's (values, status) tuple -> smooth
    # only the values array; a track missing for its whole length stays
    # NaN through smoothing too, never manufactured into a number.
    base = np.array([
        [0, -3], [-0.2, -3.2], [0.2, -3.2], [-0.4, -3.0], [0.4, -3.0],
        [-1, -2], [1, -2], [-1.2, -1], [1.2, -1], [-1.3, 0], [1.3, 0],
        [-0.7, 0], [0.7, 0], [-0.7, 2], [0.7, 2], [-0.7, 4], [0.7, 4],
    ], dtype=np.float32)
    conf = np.ones((17, 1), dtype=np.float32)
    frame = np.concatenate([base * 50.0, conf], axis=1)
    sequence = np.stack([frame.copy() for _ in range(8)])
    sequence[:, 15, 2] = 0.0  # left ankle never measured in this track

    normalized, status = normalize_sequence(sequence)
    smoothed = smooth_sequence(normalized, fps=30.0)

    assert smoothed.shape == normalized.shape
    assert (status[:, 15] == MISSING).all()
    assert np.isnan(smoothed[:, 15, :2]).all()
    assert not np.isnan(smoothed[:, 11, :2]).any()  # a measured keypoint stayed real
