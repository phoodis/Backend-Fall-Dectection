import numpy as np

from pose_extraction.normalization import (
    HIP_L,
    HIP_R,
    MIN_TORSO_LENGTH,
    SHOULDER_L,
    SHOULDER_R,
    interpolate_missing,
    normalize_sequence,
    translate_and_scale_frame,
)

# A simple standing COCO-17 figure in local units, before scale/offset.
# index: 0 nose,1-2 eyes,3-4 ears,5-6 shoulders,7-8 elbows,9-10 wrists,
# 11-12 hips,13-14 knees,15-16 ankles
_BASE_POSE = np.array([
    [0, -3], [-0.2, -3.2], [0.2, -3.2], [-0.4, -3.0], [0.4, -3.0],
    [-1, -2], [1, -2], [-1.2, -1], [1.2, -1], [-1.3, 0], [1.3, 0],
    [-0.7, 0], [0.7, 0], [-0.7, 2], [0.7, 2], [-0.7, 4], [0.7, 4],
], dtype=np.float32)


def _make_pose(scale: float, offset=(0.0, 0.0), conf: float = 1.0):
    pixels = _BASE_POSE * scale + np.array(offset, dtype=np.float32)
    conf_col = np.full((17, 1), conf, dtype=np.float32)
    return np.concatenate([pixels, conf_col], axis=1)


# --- acceptance test 1: near/far invariance, exact expected output ---

def test_near_and_far_camera_yield_identical_normalized_pose():
    near = _make_pose(scale=120.0, offset=(300.0, 200.0))
    far = _make_pose(scale=30.0, offset=(600.0, 400.0))

    normalized_near = translate_and_scale_frame(near)
    normalized_far = translate_and_scale_frame(far)

    # Scale is a pure linear factor here (same base pose, different
    # multiplier) so this must match to float32 precision, not just
    # "near-identical" - exact expected output, per the acceptance test.
    assert np.allclose(normalized_near[:, :2], normalized_far[:, :2], atol=1e-4)


# --- acceptance test 2: translation invariance, exact expected output ---

def test_same_pose_at_different_frame_positions_yields_identical_normalized_pose():
    top_left = _make_pose(scale=60.0, offset=(50.0, 50.0))
    bottom_right = _make_pose(scale=60.0, offset=(900.0, 700.0))

    normalized_a = translate_and_scale_frame(top_left)
    normalized_b = translate_and_scale_frame(bottom_right)

    assert np.allclose(normalized_a[:, :2], normalized_b[:, :2], atol=1e-5)


def test_translate_sets_hip_midpoint_to_origin():
    pose = _make_pose(scale=50.0, offset=(400.0, 300.0))
    normalized = translate_and_scale_frame(pose)
    hip_mid = (normalized[HIP_L, :2] + normalized[HIP_R, :2]) / 2.0
    assert np.allclose(hip_mid, [0.0, 0.0], atol=1e-4)


# --- acceptance test 3: no zero-fill ---

def test_missing_keypoint_is_interpolated_not_zero_filled():
    sequence = np.stack([_make_pose(scale=50.0) for _ in range(5)])
    sequence[2, 15, 2] = 0.0  # left ankle: zero confidence on frame 2 only

    normalized = normalize_sequence(sequence)
    ankle_across_time = normalized[:, 15, :2]

    assert not np.allclose(ankle_across_time[2], [0.0, 0.0], atol=1e-2)
    assert np.allclose(
        ankle_across_time[2], (ankle_across_time[1] + ankle_across_time[3]) / 2, atol=1e-2
    )


def test_no_non_hip_joint_is_ever_exactly_zero_zero_with_gaps():
    rng = np.random.default_rng(0)
    sequence = np.stack([_make_pose(scale=50.0) for _ in range(20)])
    # scatter missing confidence across random (frame, keypoint) pairs,
    # excluding the anchors themselves so normalization can still run
    non_anchor_kps = [i for i in range(17) if i not in (HIP_L, HIP_R, SHOULDER_L, SHOULDER_R)]
    for frame_idx in rng.choice(20, size=8, replace=False):
        kp = rng.choice(non_anchor_kps)
        sequence[frame_idx, kp, 2] = 0.05  # below default threshold

    normalized = normalize_sequence(sequence)

    for kp in non_anchor_kps:
        for frame_idx in range(20):
            xy = normalized[frame_idx, kp, :2]
            assert not (abs(xy[0]) < 1e-9 and abs(xy[1]) < 1e-9), (
                f"keypoint {kp} frame {frame_idx} landed exactly on the hip - looks zero-filled"
            )


# --- acceptance test 4: degenerate input marked invalid, not divided ---

def test_zero_torso_length_marks_frame_invalid_not_divided():
    pose = _make_pose(scale=50.0)
    # collapse shoulders onto the hip midpoint -> torso length 0
    hip_mid = (pose[HIP_L, :2] + pose[HIP_R, :2]) / 2.0
    pose[SHOULDER_L, :2] = hip_mid
    pose[SHOULDER_R, :2] = hip_mid

    normalized = translate_and_scale_frame(pose)

    assert np.isnan(normalized[:, :2]).all()


def test_near_zero_torso_length_below_epsilon_is_also_invalid():
    pose = _make_pose(scale=50.0)
    hip_mid = (pose[HIP_L, :2] + pose[HIP_R, :2]) / 2.0
    pose[SHOULDER_L, :2] = hip_mid + np.array([MIN_TORSO_LENGTH / 4, 0], dtype=np.float32)
    pose[SHOULDER_R, :2] = hip_mid - np.array([MIN_TORSO_LENGTH / 4, 0], dtype=np.float32)

    normalized = translate_and_scale_frame(pose)

    assert np.isnan(normalized[:, :2]).all()


# --- acceptance test 5: missing anchors handled without crashing/garbage ---

def test_missing_hip_confidence_invalidates_whole_frame_not_just_the_hip():
    pose = _make_pose(scale=50.0)
    pose[HIP_L, 2] = 0.0

    normalized = translate_and_scale_frame(pose)

    assert np.isnan(normalized[:, :2]).all()
    assert not np.array_equal(normalized[:, :2], np.zeros((17, 2)))  # never silently zero


def test_missing_shoulder_confidence_invalidates_whole_frame():
    pose = _make_pose(scale=50.0)
    pose[SHOULDER_R, 2] = 0.0

    normalized = translate_and_scale_frame(pose)

    assert np.isnan(normalized[:, :2]).all()


def test_anchors_missing_for_a_few_frames_are_recovered_by_time_interpolation():
    sequence = np.stack([_make_pose(scale=50.0) for _ in range(5)])
    sequence[2, HIP_L, 2] = 0.0  # hip anchor missing on frame 2 only

    normalized = normalize_sequence(sequence)

    assert not np.isnan(normalized[2]).any()
    assert np.allclose(normalized[2, :, :2], normalized[1, :, :2], atol=1e-2)


def test_anchors_missing_for_the_entire_sequence_stays_nan_never_zero():
    sequence = np.stack([_make_pose(scale=50.0) for _ in range(5)])
    sequence[:, HIP_L, 2] = 0.0  # hip anchor never available in this track

    normalized = normalize_sequence(sequence)

    assert np.isnan(normalized[:, :, :2]).all()  # explicit "unknown", not fabricated zero


# --- explicit start/end-of-sequence missing-value policy ---

def test_keypoint_missing_at_start_of_sequence_holds_first_valid_value():
    sequence = np.stack([_make_pose(scale=50.0) for _ in range(4)])
    sequence[0, 9, 2] = 0.0  # right wrist missing on the very first frame

    normalized = normalize_sequence(sequence)

    assert np.allclose(normalized[0, 9, :2], normalized[1, 9, :2], atol=1e-4)


def test_keypoint_missing_at_end_of_sequence_holds_last_valid_value():
    sequence = np.stack([_make_pose(scale=50.0) for _ in range(4)])
    sequence[3, 9, 2] = 0.0  # right wrist missing on the very last frame

    normalized = normalize_sequence(sequence)

    assert np.allclose(normalized[3, 9, :2], normalized[2, 9, :2], atol=1e-4)


def test_interpolate_missing_leaves_all_nan_column_untouched():
    sequence = np.full((4, 1, 3), np.nan, dtype=np.float32)
    result = interpolate_missing(sequence)
    assert np.isnan(result[:, 0, 0]).all()
    assert np.isnan(result[:, 0, 1]).all()
