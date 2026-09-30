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

Every function here returns a validity/status mask alongside the values,
so callers never have to guess which numbers are real measurements versus
filled. Status codes (see MEASURED/INTERPOLATED/HELD/MISSING below).

Missing-data handling, made explicit (spec requires each case documented,
not merely handled):
  - keypoint missing at the START or END of a sequence: policy is
    controlled by `hold_edges` (default True, matching STEP 3B's original
    behavior) - see the OPEN QUESTION below, this is not settled.
  - keypoint missing for the ENTIRE sequence: left as NaN, status MISSING
    (there is nothing to interpolate FROM) and never zero-filled. Callers
    must check status and drop/mask that track/keypoint rather than feed
    it to a model as if it were real.
  - hips or shoulders themselves missing on a frame (normalization anchors
    unavailable): the WHOLE frame is marked unmeasured (NaN for every
    keypoint, not just the anchor), then recovered by time-interpolation
    from neighbouring frames where the anchors WERE available - same as
    any other missing keypoint. If anchors are never available for the
    entire sequence, the entire sequence stays NaN/MISSING.
  - degenerate/near-zero torso length (subject viewed from directly
    above, or a detection collapsed to a point): the frame is marked
    unmeasured, NOT divided by a clamped minimum. A fabricated scale is
    worse than a missing frame.

OPEN QUESTION (2026-09-30, flagged during STEP 3B review, unresolved -
W3 must ablate before picking a default to train on): should edge gaps
be HELD (constant-extrapolated) or left as NaN/MISSING? The gate run
showed pose detection drops out most often exactly when the subject is
lying flat on the floor - which, for a clip window centered on a fall, is
usually the END of the window. `hold_edges=True` (the current default,
kept for continuity with the first STEP 3B draft) makes that look like
"the pose froze in place," which is a real, if coincidental, signal for
"the person stopped moving." `hold_edges=False` makes it look like "we
lost the subject," a different and arguably more honest signal, but one
the classifier has no training data for yet. Nothing in this codebase
decides which is right - that's an empirical question for the W3 training
notebook, not something to settle by reasoning here. `normalize_sequence`
exposes `hold_edges` precisely so both can be produced and compared.

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

# Validity/status codes returned alongside every normalized value.
MEASURED = 0      # real detection: confidence >= threshold, anchors available
INTERPOLATED = 1  # filled by linear interpolation between two MEASURED frames
HELD = 2          # filled by holding the nearest MEASURED value past a sequence
                   # edge (only produced when hold_edges=True)
MISSING = 3       # never measured and not filled - stays NaN, see module docstring


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
                               conf_threshold: float = CONF_THRESHOLD_DEFAULT) -> tuple:
    """One frame, one person: (17,3) pixel keypoints -> ((17,3) normalized,
    (17,) bool "measured this frame").

    NaN in x/y (and measured=False) for the WHOLE frame when hip and/or
    shoulder midpoint is unavailable (missing anchor) or torso length is
    near zero (degenerate detection) - never a fabricated/clamped value.
    NaN in x/y (and measured=False) for an individual keypoint when its
    own confidence is below threshold. The confidence channel always
    passes through unchanged, even on an otherwise-unmeasured frame, since
    it is not being normalized.
    """
    out = np.full_like(keypoints, np.nan, dtype=np.float32)
    out[:, 2] = keypoints[:, 2]
    measured = np.zeros(17, dtype=bool)

    hip = _hip_midpoint(keypoints, conf_threshold)
    shoulder = _shoulder_midpoint(keypoints, conf_threshold)
    if hip is None or shoulder is None:
        return out, measured  # anchors unavailable - whole frame unmeasured

    torso_length = float(np.linalg.norm(shoulder - hip))
    if torso_length < MIN_TORSO_LENGTH:
        return out, measured  # degenerate detection - never divide by a clamped value

    scaled = (keypoints[:, :2] - hip) / torso_length
    low_conf = keypoints[:, 2] < conf_threshold
    scaled[low_conf] = np.nan
    out[:, :2] = scaled
    measured = ~low_conf
    return out, measured


def interpolate_missing(sequence: np.ndarray, measured: np.ndarray,
                         hold_edges: bool = True) -> tuple:
    """(T,17,3) normalized sequence (NaN where unmeasured) + (T,17) bool
    measured mask -> ((T,17,3) filled, (T,17) int8 status).

    Interior gaps (unmeasured frames strictly between two measured frames
    for that keypoint) are always linearly interpolated - status
    INTERPOLATED. Gaps at the start/end of the sequence (before the first
    or after the last measured frame) follow `hold_edges`:
      - True (default): held constant at the nearest measured value
        (np.interp's natural extrapolation behavior) - status HELD.
      - False: left as NaN - status stays MISSING.
    A (keypoint) column with NO measured frame at all is left entirely NaN
    regardless of `hold_edges` - status MISSING throughout. Never
    zero-filled in any case.
    """
    result = sequence.copy()
    status = np.where(measured, MEASURED, MISSING).astype(np.int8)
    t = np.arange(sequence.shape[0])

    for kp in range(sequence.shape[1]):
        valid = measured[:, kp]
        if not valid.any() or valid.all():
            continue

        first_valid = int(np.argmax(valid))
        last_valid = len(valid) - 1 - int(np.argmax(valid[::-1]))

        for coord in (0, 1):
            values = sequence[:, kp, coord]
            filled = np.interp(t, t[valid], values[valid])
            if not hold_edges:
                filled[:first_valid] = np.nan
                filled[last_valid + 1:] = np.nan
            result[:, kp, coord] = filled

        interior_gap = ~valid.copy()
        interior_gap[:first_valid] = False
        interior_gap[last_valid + 1:] = False
        status[interior_gap, kp] = INTERPOLATED

        if hold_edges:
            edge_gap = ~valid.copy()
            edge_gap[first_valid:last_valid + 1] = False
            status[edge_gap, kp] = HELD
        # else: edge frames stay MISSING (already set above) and values are NaN

    return result, status


def normalize_sequence(keypoints_sequence: np.ndarray,
                        conf_threshold: float = CONF_THRESHOLD_DEFAULT,
                        hold_edges: bool = True) -> tuple:
    """Full pipeline for one track: (T,17,3) raw pixel keypoints ->
    ((T,17,3) translated+scaled+interpolated, (T,17) int8 status). See
    module docstring for the status codes and the open `hold_edges`
    question.
    """
    frames = []
    measured_frames = []
    for t in range(keypoints_sequence.shape[0]):
        frame, measured = translate_and_scale_frame(keypoints_sequence[t], conf_threshold)
        frames.append(frame)
        measured_frames.append(measured)

    normalized = np.stack(frames)
    measured = np.stack(measured_frames)
    return interpolate_missing(normalized, measured, hold_edges=hold_edges)
