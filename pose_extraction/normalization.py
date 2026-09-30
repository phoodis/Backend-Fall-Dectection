"""Normalize COCO-17 keypoint sequences so the representation encodes
POSTURE, not the subject's position in frame or distance from camera.

Order matters and is fixed: TRANSLATE -> SCALE -> INTERPOLATE MISSING. See
docs/superpowers/specs/2026-09-18-pose-extractor-migration-spec.md (STEP 3B)
for the full rationale. Interpolating LAST, in already-normalized space,
means we never write 0.0 for a missing keypoint: after translation, (0,0)
IS the hip position, so a zero-fill would assert "the ankle is at the hip"
- an anatomically impossible pose the classifier would learn as real. This
is the same class of silent corruption as the extract_pose_features() ->
np.zeros(136) defect already present in app/detection/v2_fall_detection_onnx.py.

Missing-data handling, made explicit (spec requires each case documented,
not merely handled):
  - keypoint missing at the START of a sequence: held constant at the
    first valid value going forward (np.interp's default extrapolation
    behavior - not an accident, this IS the chosen policy).
  - keypoint missing at the END of a sequence: held constant at the last
    valid value going backward, same mechanism.
  - keypoint missing for the ENTIRE sequence: left as NaN, not
    interpolated (there is nothing to interpolate FROM) and never
    zero-filled. Callers must check for NaN and drop/mask that
    track/keypoint rather than feed it to a model as if it were real.
  - hips or shoulders themselves missing on a frame (normalization anchors
    unavailable): the WHOLE frame is marked invalid (NaN for every
    keypoint, not just the anchor), then recovered by time-interpolation
    from neighbouring frames where the anchors WERE available - same as
    any other missing keypoint. If anchors are never available for the
    entire sequence, the entire sequence stays NaN (see previous point).
  - degenerate/near-zero torso length (subject viewed from directly
    above, or a detection collapsed to a point): the frame is marked
    invalid, NOT divided by a clamped minimum. A fabricated scale is worse
    than a missing frame.

Dependency-light by design: numpy only. Runs standalone in the Step 6
extraction script and later in a Colab training notebook - no cv2,
mediapipe, or ultralytics import here, ever.
"""
import numpy as np

HIP_L, HIP_R = 11, 12
SHOULDER_L, SHOULDER_R = 5, 6
CONF_THRESHOLD_DEFAULT = 0.3
# Below this, hip-shoulder distance is treated as a degenerate detection,
# not a genuinely small torso (a small torso from camera distance is a
# large-magnitude case, not a near-zero one - those are different failure
# modes). This is a floating-point-safety epsilon, not a soft clamp.
MIN_TORSO_LENGTH = 1e-3


def _hip_midpoint(keypoints: np.ndarray, conf_threshold: float):
    l, r = keypoints[HIP_L], keypoints[HIP_R]
    if l[2] < conf_threshold or r[2] < conf_threshold:
        return None
    return (l[:2] + r[:2]) / 2.0


def _shoulder_midpoint(keypoints: np.ndarray, conf_threshold: float):
    l, r = keypoints[SHOULDER_L], keypoints[SHOULDER_R]
    if l[2] < conf_threshold or r[2] < conf_threshold:
        return None
    return (l[:2] + r[:2]) / 2.0


def translate_and_scale_frame(keypoints: np.ndarray,
                               conf_threshold: float = CONF_THRESHOLD_DEFAULT) -> np.ndarray:
    """One frame, one person: (17,3) pixel keypoints -> (17,3) normalized.

    NaN in x/y for the WHOLE frame when hip and/or shoulder midpoint is
    unavailable (missing anchor) or torso length is near zero (degenerate
    detection) - never a fabricated/clamped value. NaN in x/y for an
    individual keypoint when its own confidence is below threshold. The
    confidence channel always passes through unchanged, even on an
    otherwise-invalid frame, since it is not being normalized.
    """
    out = np.full_like(keypoints, np.nan, dtype=np.float32)
    out[:, 2] = keypoints[:, 2]

    hip = _hip_midpoint(keypoints, conf_threshold)
    shoulder = _shoulder_midpoint(keypoints, conf_threshold)
    if hip is None or shoulder is None:
        return out  # anchors unavailable - whole frame invalid, see module docstring

    torso_length = float(np.linalg.norm(shoulder - hip))
    if torso_length < MIN_TORSO_LENGTH:
        return out  # degenerate detection - invalid, never divide by a clamped value

    scaled = (keypoints[:, :2] - hip) / torso_length
    low_conf = keypoints[:, 2] < conf_threshold
    scaled[low_conf] = np.nan
    out[:, :2] = scaled
    return out


def interpolate_missing(sequence: np.ndarray) -> np.ndarray:
    """(T,17,3) normalized sequence, NaN where missing -> same shape with
    every NaN linearly interpolated across time, per (keypoint, coordinate)
    independently.

    Uses np.interp, whose extrapolation behavior IS the chosen policy for
    the start/end-of-sequence cases (see module docstring): values before
    the first valid frame are held at that first valid value; values after
    the last valid frame are held at the last valid value. A (keypoint,
    coordinate) column that is NaN for every frame (missing for the entire
    sequence) is left as NaN - there is nothing to interpolate from, and it
    must never be zero-filled. Callers must check for and handle NaN.
    """
    result = sequence.copy()
    t = np.arange(sequence.shape[0])

    for kp in range(sequence.shape[1]):
        for coord in (0, 1):
            values = sequence[:, kp, coord]
            valid = ~np.isnan(values)
            if not valid.any() or valid.all():
                continue
            result[:, kp, coord] = np.interp(t, t[valid], values[valid])

    return result


def normalize_sequence(keypoints_sequence: np.ndarray,
                        conf_threshold: float = CONF_THRESHOLD_DEFAULT) -> np.ndarray:
    """Full pipeline for one track: (T,17,3) raw pixel keypoints -> (T,17,3)
    translated + scaled + interpolated, in that fixed order.
    """
    normalized = np.stack([
        translate_and_scale_frame(keypoints_sequence[t], conf_threshold)
        for t in range(keypoints_sequence.shape[0])
    ])
    return interpolate_missing(normalized)
