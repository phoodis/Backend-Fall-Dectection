"""Pose-only fall classifier (v3): windowed COCO-17 keypoint sequences -> temporal CNN.

Replaces the v2 DeepSVDD pipeline (RGB ResNet50 + optical flow + a pose feature
branch that always returned zeros -- see FeatureExtractorONNX.extract_pose_features
in v2_fall_detection_onnx.py) with a model trained purely on pose keypoints, which
is both simpler and actually uses the skeleton signal it's supposed to. See
training/model.py and training/train.py for how it was trained (~10,000 windowed
clips pooled from GMDCSA24 + FallVision + CAUCAFall + OmniFall OF-ItW/OOPS).

Pose backend is YOLO-pose (yolo26s-pose), not MediaPipe -- switched SS34/35 after
validating end to end (better raw detection rate on hard "person down" frames,
faster on CPU, and -- with flip + synthetic-occlusion training augmentation added
specifically to close a gap found on a real cane-assisted fall clip -- matching or
exceeding the prior MediaPipe-trained model's numbers on both GMDCSA24 held-out
test sets). Its output is already COCO-17 (index-identical to LEFT_SHOULDER=5/
RIGHT_SHOULDER=6/LEFT_HIP=11/RIGHT_HIP=12 below), unlike MediaPipe's 33-point
BlazePose output which needed the MEDIAPIPE33_TO_COCO17 remap (kept below, no
longer used by this file, but training/extract_poses.py's original MediaPipe-based
extraction scripts still reference it).

Preprocessing here must match training/dataset.py exactly: pose -> COCO-17 subset ->
torso-relative normalization -> per-frame velocity -> WINDOW_SIZE-frame window. The deployed
model uses 15 frames at the 15 fps the camera loop is pinned to, so a window is 1.0s of real
time; tools/check_config_coherence.py fails if those stop agreeing.

Operating point: sigmoid threshold THRESHOLD (0.65 for the deployed 15-frame model), plus
requiring SMOOTH_NEED-of-last-SMOOTH_OF windows to agree before raising an alert
(not strictly consecutive -- a 50-clip end-to-end batch test found several real
falls where confidence spiked above threshold but dipped for a single window in
between, which a strict "N in a row" rule threw away). This still cuts false
alarms for a modest recall cost. This is not accurate enough to alert
autonomously; treat detections as a prompt for staff to check the camera, not a
confirmed event.
"""
import os
from collections import deque

import cv2
import numpy as np
import onnxruntime as ort
from ultralytics import YOLO

NUM_KEYPOINTS = 17
# Overridable so the low-frame-rate experiment (a model trained on frames subsampled to the
# rate a live camera actually achieves -- see training/eval_v3_frame_drop.py) can be evaluated
# through this exact production code path instead of a parallel copy of it.
# 15 frames, matching the deployed model, which is trained on every second frame of 30fps
# footage -- so a window covers 1.0s of real time at the 15 fps V3_TARGET_FPS pins the camera
# loop to. This number and the model are a pair: a 30-frame window with this model, or this
# window with the 30-frame model, is a different detector from the one that was measured.
WINDOW_SIZE = int(os.environ.get("V3_WINDOW_SIZE", 15))
STRIDE = 10
# 0.65, not the previous 0.50, because the shorter window scores differently. Chosen on half
# of URFD (even-numbered clips) plus GMDCSA24, then confirmed on the untouched odd half, where
# it improved both axes (falls 12 -> 13 of 30, clean 14 -> 17 of 20). Against everything never
# trained on it catches 56/75 falls versus the previous 49/75 with identical false alarms
# (41/56 clean either way). Sweep it with training/measure_alert_tier.py-style runs if the
# window or frame rate ever changes; the right value is not independent of those (SS38, SS51).
THRESHOLD = float(os.environ.get("V3_THRESHOLD", 0.65))
LOADED_IDENTITY = None   # set when a detector loads; see V3PoseFallDetector.__init__


def _sha12(path):
    """First 12 hex chars of the sha256 of a file (or of a directory's files, e.g. an OpenVINO export)."""
    import hashlib
    h = hashlib.sha256()
    try:
        files = [path] if os.path.isfile(path) else sorted(
            os.path.join(r, f) for r, _, fs in os.walk(path) for f in fs)
        for f in files:
            with open(f, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
        return h.hexdigest()[:12] if files else None
    except OSError:
        return None
# Env-overridable alongside V3_WINDOW_SIZE: at a live camera'''s real frame rate each window
# advances by a whole 1/5 s, so "2 positive windows out of 3" is a much longer wait than it
# was at 30fps -- worth measuring rather than assuming (training/eval_v3_frame_drop.py).
# 1, measured on URFD -- the only dataset here nothing has ever been tuned against. Requiring
# two positive windows discards falls the classifier already scored above threshold: URFD
# recall 38/60 -> 43/60, with no fall lost on any set. The cost is three extra alerts
# (URFD adl-28, train50 s2_ADL_08 and s3_ADL_20), each verified individually -- adl-28 is a man
# bending to tie his shoes, confirmed by eye and by Gemini on the clip, and all three score
# 0.50-0.52, so every one of them lands in the "check" tier, never the confirmed/emergency
# wording. Trading three "please look" alerts for five caught falls is the right direction for
# a system whose failure mode is a person lying on the floor unnoticed.
SMOOTH_NEED = int(os.environ.get("V3_SMOOTH_NEED", 1))   # need this many...
SMOOTH_OF = int(os.environ.get("V3_SMOOTH_OF", 3))   # ...positive windows out of the last this many (not strictly consecutive)
# Max people the FALL path keeps per frame (highest box confidence first) -- see
# detect_v3_fall_multi. The people COUNT for alone detection is not capped (count_people).
# A person lying on the floor tends to have the lowest box confidence, so in a crowd larger
# than this the faller is the one dropped; the cap saves little CPU (the pose pass costs the
# same whatever it is). Env so 4 vs 8 can be measured: plan_v4_cliptest.md, item 1.
NUM_POSES = int(os.environ.get("V3_NUM_POSES", 4))

MEDIAPIPE33_TO_COCO17 = [0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]
LEFT_SHOULDER, RIGHT_SHOULDER = 5, 6
LEFT_HIP, RIGHT_HIP = 11, 12


SMOOTH_KERNEL = 3
# MediaPipe's PoseLandmarker runs in IMAGE mode (each frame estimated independently,
# no temporal tracking -- see extract_poses.py), which is fine for a static photo but
# means keypoints can jitter frame-to-frame even when the person hasn't moved: on a
# real test clip, a standing-still person's shoulder-hip tilt angle was measured
# swinging 5deg -> 87deg -> 12deg -> 83deg across consecutive frames (SKILL.md SS18).
# Since velocity (frame-to-frame keypoint displacement) is a direct input feature,
# that jitter reads as fast motion and produced 3/3 confirmed false "fall" alerts on
# real test footage, independently confirmed by Gemini reviewing the same frames.
# A short trailing/centered moving average on x,y (not visibility) damps single-frame
# jitter while a genuine fall -- large, multi-frame, sustained displacement -- still
# comes through. Applied only here (inference), not in training/dataset.py's
# preprocessing, which is a real train/inference mismatch; validated empirically
# instead (SS18) rather than assumed safe -- see there before changing this further.
def _smooth_keypoints(raw_window, kernel=SMOOTH_KERNEL):
    """raw_window: (T, 17, 3) -> same shape, x,y smoothed with a centered moving
    average (visibility left untouched)."""
    T = raw_window.shape[0]
    half = kernel // 2
    smoothed = raw_window.copy()
    for t in range(T):
        lo, hi = max(0, t - half), min(T, t + half + 1)
        smoothed[t, :, :2] = raw_window[lo:hi, :, :2].mean(axis=0)
    return smoothed


# V3_FRAME_POSITION: feed the classifier where the person is in the frame, as two extra
# channels per joint -- the hip centre's height and the apparent torso size, both before
# normalisation removes them.
#
# It must match the classifier file. The two layouts differ only in the width of the
# classifier's input, so a mismatch is not a crash but a silently wrong number; __init__
# reads the width out of the ONNX and refuses to load a model that disagrees with this flag.
# The training-side flag of the same purpose is USE_FRAME_POSITION in training/dataset.py,
# where the reasoning is written out in full.
FRAME_POSITION = os.environ.get("V3_FRAME_POSITION", "0") == "1"
FEATURES_PER_FRAME = NUM_KEYPOINTS * (5 + (2 if FRAME_POSITION else 0))


def _normalize_and_velocity(raw_window):
    """raw_window: (WINDOW_SIZE, 17, 3) raw [x, y, visibility] -> (WINDOW_SIZE, 17, 5)
    [x, y, confidence, vx, vy], torso-relative and scale-normalized per frame.

    With FRAME_POSITION, (WINDOW_SIZE, 17, 7): the hip centre's height in the frame and the
    apparent torso size are appended, repeated across every joint. They are read here, before
    the hip-centring below throws them away -- which is the whole point, since a body lying on
    a bed and a body lying on the floor are the same picture once centred.
    """
    raw_window = _smooth_keypoints(raw_window)
    xy = raw_window[:, :, :2]
    vis = raw_window[:, :, 2:3]

    hip_center = (xy[:, LEFT_HIP] + xy[:, RIGHT_HIP]) / 2.0
    shoulder_center = (xy[:, LEFT_SHOULDER] + xy[:, RIGHT_SHOULDER]) / 2.0
    torso_size = np.clip(np.linalg.norm(shoulder_center - hip_center, axis=1), 1e-3, None)

    xy_norm = (xy - hip_center[:, None, :]) / torso_size[:, None, None]
    norm_seq = np.concatenate([xy_norm, vis], axis=-1)

    vel = np.diff(xy_norm, axis=0, prepend=xy_norm[:1])
    out = np.concatenate([norm_seq, vel], axis=-1)
    if FRAME_POSITION:
        fp = np.stack([hip_center[:, 1], torso_size], axis=1)[:, None, :]   # (T, 1, 2)
        out = np.concatenate([out, np.repeat(fp, out.shape[1], axis=1)], axis=-1)
    return out


def _check_feature_width(session, path):
    """Refuse a classifier whose input width disagrees with V3_FRAME_POSITION.

    The failure this prevents is silent. Both layouts are a (1, WINDOW_SIZE, N) float tensor
    and onnxruntime will happily run the wrong N only if it happens to match -- but when the
    flag and the file disagree, the width disagrees too, and the alternative to this check is
    an exception from deep inside onnxruntime naming no cause. Worse, a future model trained
    with hip motion instead would have the SAME width as this one and run without complaint,
    so the message says which flag produced the expectation.
    """
    shape = session.get_inputs()[0].shape
    width = shape[-1]
    if isinstance(width, int) and width != FEATURES_PER_FRAME:
        raise ValueError(
            f"{os.path.basename(path)} takes {width} features per frame but "
            f"V3_FRAME_POSITION={'1' if FRAME_POSITION else '0'} produces {FEATURES_PER_FRAME}"
            f" ({NUM_KEYPOINTS} joints x {FEATURES_PER_FRAME // NUM_KEYPOINTS}). The flag and "
            f"the model file have to be set together.")


# Input resolution handed to YOLO-pose. Ultralytics' default is 640, which downsamples a
# 1080p camera frame ~3x and is measured to be where recall is lost: a fall composited into a
# 2x-wide frame (same person, half the pixels) drops from 15/15 to 10/15 with nobody else in
# shot (training/eval_multiperson_composite.py), matching SS6's finding that errors cluster
# where the person is far from the camera. Raising it costs GPU time, which the GPU now has
# (53 fps standalone versus the ~25 fps a camera needs).
# 960, not ultralytics' default 640. Measured across every ground-truth surface this project
# uses, 960 is better or equal on all of them and worse on none -- val 15/15 falls with
# ADL-clean 9/16 -> 10/16, train50 unchanged at 22/25 and 22/25, and on the two-person
# composites the fall is caught 13/15 instead of 12/15 (14/15 vs 10/15 in the blank-half
# control that isolates resolution from the second person). 1280 trades differently: far
# fewer false alarms (val ADL-clean 14/16) but it starts losing falls (14/15 val, 20/25
# train50), so it is not taken. Costs 18.8 -> 21.8 ms/frame on the GPU, which still leaves
# roughly twice the throughput a 25 fps camera needs.
IMGSZ = int(os.environ.get("V3_IMGSZ", 960))

# Input size for the people-counting pass that answers alone-detection, which is a different
# question from "is this person falling" and wants more pixels than the CPU profile can afford
# to spend on every frame. It runs once every ALONE_DETECTION_CHECK_INTERVAL_S, not per frame.
# Scored against Gemini-verified counts on the 77-frame ground-truth set, "is exactly one
# person present" is right 74.0% of the time at 320, 81.8% at 480 and 640, and 83.1% at 800 and
# above -- against 80.5% for the yolo26l detector this replaces. 640 is the cheapest size that
# is already better than what it replaces; the last 1.3 points cost 25% more work for a check
# that runs three times a minute.
COUNT_IMGSZ = int(os.environ.get("V3_COUNT_IMGSZ", 640))

# Which tracker assigns a person their identity across frames. "hip" is the original
# nearest-hip-centre matcher in PersonTracker below; "bytetrack" uses ultralytics' own
# tracker (Kalman motion prediction + IoU), which exists because the hip matcher loses
# people constantly: measured on Test/1,12,16,17, between 68% and 91% of the track ids it
# creates are re-detections of someone it already had, not new people. Each of those resets
# that person's 30-frame window, so the classifier keeps scoring half-filled windows.
TRACKER = os.environ.get("V3_TRACKER", "hip")

# Confidence YOLO-pose must have in a person before their pose is used. Ultralytics' own
# default is 0.25; 0.5 was chosen here before any of it was measured. It decides detection
# CONTINUITY, which is what actually breaks multi-person tracking: on Test/1 the detector
# averages 0.83 people per frame, so tracks keep expiring and restarting their 30-frame
# window regardless of which tracker is used.
# 0.3, measured. Raising detection continuity is what actually helps multi-person accuracy:
# at 0.5 the held-out train50 set catches 22/25 falls, at 0.3 it catches 24/25, with ADL-clean
# unchanged on both sets (val 10/16, train50 22/25) and the two-person composites identical
# (13/15, 4/4 clean). 0.25 measures the same as 0.3 but keeps more marginal detections, so 0.3
# is taken as the smaller change from the previous 0.5.
POSE_CONF = float(os.environ.get("V3_POSE_CONF", 0.3))


# V3_PREPROCESS: clean up the frame before the pose model sees it. Comma-separated, applied in
# the order given. **Default "auto"**, which was earned rather than assumed -- it shipped off
# until both profiles had been measured on alerts, because a default that alters frames makes
# every published number describe a detector nobody measured.
#
# MEASURED ON ALERTS, both profiles, the full 220-clip set:
#
#                    URFD falls   held-out clean   URFD half A clean   half B clean
#     CPU  off          45/60         41/56             17/20            16/20
#     CPU  auto         45/60         43/56             18/20            17/20
#     GPU  off          56/60         40/56             17/20            16/20
#     GPU  auto         56/60         41/56             18/20            16/20
#
# **Not one fall lost on either profile, and three false alarms gone between them.** On the CPU
# profile the gain shows on both halves of URFD including the half reserved for confirming,
# which is what a real effect looks like rather than noise. The clips are adl-22 and adl-23,
# the two darkest in the corpus at luminance 29 and 31.
#
#   off        hand the frame through untouched.
#   clahe      CLAHE on the L channel of LAB -- local contrast, which is what a backlit or
#              dim room actually lacks. Global histogram equalisation was not used: it drags
#              the whole frame and wrecks a well-exposed background to fix a dark subject.
#   gamma      gamma < 1 lifts the shadows without clipping the highlights, unlike adding a
#              constant.
#   auto       clahe + gamma, but ONLY on a frame whose mean luminance is below
#              PREPROCESS_DARK_BELOW. A well-exposed frame is passed through untouched.
#
# WHY "auto" RATHER THAN PLAIN "clahe" WHEN IT IS TURNED ON. Nothing in training/ was preprocessed, so
# altering a frame the pose model would have handled fine is a train/inference mismatch with
# nothing to show for it -- the same kind of mismatch _smooth_keypoints is, except that one was
# measured to earn its place. Gating on measured darkness means the mismatch only exists on
# frames the model was going to struggle with anyway.
#
# WHAT THE AVAILABLE DATA CAN AND CANNOT SAY ABOUT THIS. Mean luminance across every clip here
# (scratchpad brightness survey, 12 frames per clip):
#
#     URFD falls    60 clips   min 76    median 104    0 clips below 70
#     URFD ADL      40 clips   min 28    median 117   12 clips below 70
#     GMDCSA24      95 clips   min 108   median 123    0 clips below 70
#     Test/         17 clips   min 62    median 101    1 clip  below 70
#
# **No fall clip in any dataset here is dark.** So this cannot improve fall recall on the
# available data, and any claim that it does would be noise. The only measurable upside is
# false alarms on the twelve dark URFD ADL clips. It is in the pipeline because the deployment
# target is an elderly person's home at night, which is darker than anything in this corpus --
# a capability the data cannot score, stated as such rather than dressed up as an accuracy win.
PREPROCESS = [p.strip() for p in os.environ.get("V3_PREPROCESS", "auto").split(",") if p.strip()]
# Below this mean luminance (0-255) "auto" considers a frame dark enough to be worth altering.
#
# 70. It started at 70, was moved to 32 on a person-found measurement, and came back when that
# measurement turned out to be the wrong question -- which is worth spelling out, because the
# same mistake is easy to repeat.
#
# Person-found said 70 was four frames worse than doing nothing across 7067 frames. On ALERTS,
# the measurement that decides anything, gates of 32, 50 and 70 are **bit-identical at full
# light on both profiles**: CPU 45/60 falls and 43/56 held-out clean, GPU 56/60 and 41/56, every
# surface the same. The cost of 70 in a lit room is nothing at all.
#
# And in a dim one it is the difference (CPU profile, URFD, footage dimmed with sensor noise by
# SIMULATE_DARK):
#
#     light      falls: off / 32 / 70      held-out clean: off / 32 / 70
#     full           45 / 45 / 45                43 / 43 / 43
#     50%            40 / 40 / **43**            41 / 43 / **45**
#     30%            35 / 34 / 34                43 / 44 / **47**
#
# At half light 70 recovers three of the five falls the dark costs AND gains four clean clips,
# on both axes at once, with both halves of URFD agreeing. 32 does nothing there for a reason
# that is arithmetic: **zero of the sixty fall clips fall below 32 at half light.** It was
# chosen as provably harmless on a corpus that has almost nothing between luminance 30 and 70,
# which is the exact band a dimly lit room occupies -- so "harmless" was established on a range
# that excludes the case the setting exists for.
#
# What stays true from the 32 era: enhancing a frame that is already bright costs more than it
# earns. "clahe always" gains the most on dark frames of any setting and still finishes twenty
# frames behind doing nothing. The gate is the point; where it sits is what was wrong.
PREPROCESS_DARK_BELOW = float(os.environ.get("V3_PREPROCESS_DARK_BELOW", 70))
# V3_PREPROCESS_GREY_BELOW: also clean up when the frame is GREYSCALE, not only when it is dark.
#
# A CCTV camera at night switches to its infrared sensor and sends grey, and grey is not dim:
# simulated IR frames measured luminance 59-100, so the dark gate above fired on some and not
# others, for a reason unrelated to why the cleanup helps. Measured on URFD with the deployed
# classifier, paired noise seeds 0 and 7, cleanup forced on for IR frames against the shipped
# gate: false alarms 4 -> 2 on BOTH seeds, falls 15 -> 16 and 20 -> 20
# (compare_caches.py 48d0f13b6cd5/e56b5d094084 and 10b792cedd97/01317e7862b2). Small, but in the
# same direction on both draws.
#
# Chroma is read the cheap way, like luminance: every 8th pixel, the spread between a pixel's
# largest and smallest channel. A real IR frame replicates one channel, so it reads ~0.
#
# **Off by default, because the check that was meant to justify turning it on failed.** Scanned
# every sampled frame of the 220 lab clips and the 17 Test clips: URFD falls reach chroma 10, and
# Test/14 -- real indoor daytime CCTV of an elderly woman, exactly the deployment's footage --
# reads 9.1 because CCTV colour is washed out. A real night-vision doorbell frame in Test/8 reads
# 4.4. So at 12 the gate would also clean up bright daytime CCTV, which was never measured; the
# margin between real IR (4.4) and washed daytime (8.1-9.1) is too thin to pick a number by eye.
# Then measured on real footage at the CPU profile (126 compilation segments, 7 of them genuine
# night-vision): no net change -- one fall gained, one REAL IR fall lost (Test/9 segment 5).
# The simulated gain did not survive contact with real IR. Closed; kept only as a switch. 0 = off.
PREPROCESS_GREY_BELOW = float(os.environ.get("V3_PREPROCESS_GREY_BELOW", 0))
PREPROCESS_GAMMA = float(os.environ.get("V3_PREPROCESS_GAMMA", 0.65))
PREPROCESS_CLIP_LIMIT = float(os.environ.get("V3_PREPROCESS_CLIP_LIMIT", 2.0))
PREPROCESS_TILE = int(os.environ.get("V3_PREPROCESS_TILE", 8))

# Built once: cv2.createCLAHE allocates, and this runs on every frame of every camera.
_CLAHE = None
# 256-entry lookup table, so gamma costs one cv2.LUT instead of a pow over every pixel.
_GAMMA_LUT = None


def _clahe():
    global _CLAHE
    if _CLAHE is None:
        _CLAHE = cv2.createCLAHE(clipLimit=PREPROCESS_CLIP_LIMIT,
                                 tileGridSize=(PREPROCESS_TILE, PREPROCESS_TILE))
    return _CLAHE


def _gamma_lut():
    """out = (in/255) ** gamma, so gamma < 1 LIFTS shadows.

    Not ** (1/gamma), which is the form in most OpenCV snippets and expects gamma > 1 to
    brighten. Written that way with this default it took a mean luminance of 27 down to 8 --
    the first version of this shipped that, and because CLAHE runs first and brightens, the two
    cancelled and the whole setting measured as doing nothing at all on the dark clips. The
    exponent and the default have to agree about which direction "gamma" means.
    """
    global _GAMMA_LUT
    if _GAMMA_LUT is None:
        g = max(PREPROCESS_GAMMA, 1e-3)
        _GAMMA_LUT = np.array([((i / 255.0) ** g) * 255 for i in range(256)], dtype=np.uint8)
    return _GAMMA_LUT


def _apply_clahe(frame_bgr):
    """Local contrast on luminance only, so colour is left alone."""
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = _clahe().apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def frame_luminance(frame_bgr, step=8):
    """Mean luminance 0-255, read from every 8th pixel in each direction.

    The full-frame version costs 2.5 ms at 1080p and runs on every frame of every camera even
    when nothing is going to be done with the answer. Every 8th pixel is 1/64 of the work and
    the two agree to well under a digit on a real frame -- this decides a threshold at 70
    against a corpus sitting at 27 or 100+, so a fraction of a level cannot change the answer.
    """
    small = frame_bgr[::step, ::step]
    # BGR to luma with the same weights cv2.COLOR_BGR2GRAY uses, without allocating a
    # converted copy of the frame.
    return float(small[:, :, 0].mean() * 0.114
                 + small[:, :, 1].mean() * 0.587
                 + small[:, :, 2].mean() * 0.299)


def frame_chroma(frame_bgr, step=8):
    """Mean colourfulness 0-255: max minus min channel, from every 8th pixel. ~0 for greyscale."""
    small = frame_bgr[::step, ::step].astype(np.int16)
    return float((small.max(axis=2) - small.min(axis=2)).mean())


def preprocess_frame(frame_bgr):
    """-> (frame, what_was_applied). The frame is returned unchanged when nothing applies.

    Every entry point that hands a frame to the pose model goes through here, so a setting
    cannot end up applied to detection but not to people-counting.
    """
    if not PREPROCESS or PREPROCESS == ["off"]:
        return frame_bgr, ()
    ops = PREPROCESS
    if "auto" in ops:
        # The gate reads the ORIGINAL frame and opens or closes the whole list. "auto" expands in
        # place to clahe+gamma, so "bilateral,auto" denoises first and "auto,unsharp" sharpens
        # after (NIGHT-NOISE-v1 arms); a lone "auto" is exactly what it always was.
        dark = frame_luminance(frame_bgr) < PREPROCESS_DARK_BELOW
        grey = PREPROCESS_GREY_BELOW > 0 and frame_chroma(frame_bgr) < PREPROCESS_GREY_BELOW
        if not (dark or grey):
            return frame_bgr, ()
        i = ops.index("auto")
        ops = ops[:i] + ["clahe", "gamma"] + [o for o in ops[i + 1:] if o != "auto"]
    applied = []
    out = frame_bgr
    for op in ops:
        if op == "clahe":
            out = _apply_clahe(out)
        elif op == "gamma":
            out = cv2.LUT(out, _gamma_lut())
        elif op in _LUMA_OPS:
            out = _on_luma(out, _LUMA_OPS[op])
        else:
            continue
        applied.append(op)
    return out, tuple(applied)


# NIGHT-NOISE-v1 (Codex design 2026-10-01, training/data/multi_diag_v2/codex_night_noise_final.md):
# candidate clean-ups for noisy night frames, each on luminance only, parameters fixed before any
# measurement. Unmeasured: none is on unless V3_PREPROCESS names it. PREPROCESS_PARAMS goes into
# every cache key that uses one, so a changed constant can never answer for an old cache.
PREPROCESS_PARAMS = ("vflat:64/16/0.8-1.25/floor16;unsharp:s1/0.25/clip8;bilateral:5/15/3;"
                     "guided:r4/eps(8/255)^2;nlmeans:h5/t7/s15")


def _on_luma(frame_bgr, fn):
    ycc = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2YCrCb)
    ycc[:, :, 0] = fn(ycc[:, :, 0])
    return cv2.cvtColor(ycc, cv2.COLOR_YCrCb2BGR)


def _vflat(y):
    """Blind illumination flattening: no knowledge of any simulated vignette."""
    small = cv2.resize(y, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32)
    illum = cv2.resize(cv2.GaussianBlur(small, (0, 0), 16), (y.shape[1], y.shape[0]),
                       interpolation=cv2.INTER_LINEAR)
    gain = np.clip(float(np.median(illum)) / np.maximum(illum, 16.0), 0.8, 1.25)
    return np.clip(y.astype(np.float32) * gain, 0, 255).astype(np.uint8)


def _unsharp(y):
    yf = y.astype(np.float32)
    corr = np.clip(0.25 * (yf - cv2.GaussianBlur(yf, (0, 0), 1.0)), -8, 8)
    return np.clip(yf + corr, 0, 255).astype(np.uint8)


def _guided(y, r=4, eps=(8 / 255.0) ** 2):
    """Self-guided filter (He et al.), box filters only -- no opencv-contrib needed."""
    i = y.astype(np.float32) / 255.0
    k = (2 * r + 1, 2 * r + 1)
    mean = cv2.boxFilter(i, -1, k)
    var = cv2.boxFilter(i * i, -1, k) - mean * mean
    a = var / (var + eps)
    b = mean - a * mean
    q = cv2.boxFilter(a, -1, k) * i + cv2.boxFilter(b, -1, k)
    return np.clip(q * 255.0, 0, 255).astype(np.uint8)


_LUMA_OPS = {
    "vflat": _vflat,
    "unsharp": _unsharp,
    "bilateral": lambda y: cv2.bilateralFilter(y, 5, 15, 3),
    "guided": _guided,
    "nlmeans": lambda y: cv2.fastNlMeansDenoising(y, None, 5, 7, 15),
}


# Set by V3PoseFallDetector.__init__ once a detector exists in this process.
LOADED_DEVICE = None


# V3_ROI_IMGSZ: run the pose pass on a crop around where the people were last seen, at a
# smaller input size, instead of on the whole frame at the full one.
#
# The idea, and why it is not just "make the input smaller": ultralytics resizes whatever it is
# given to `imgsz`, so cropping alone saves nothing -- it only raises the effective resolution
# on the person. Cropping AND lowering imgsz together is what trades area for compute: if the
# people occupy a quarter of the frame, a quarter-sized crop at half the input size puts the
# same number of pixels on the body for a quarter of the work. On four CPU cores the pose pass
# is 63% of the frame budget and frame rate is recall, so that is the trade worth measuring.
#
# The failure it must not have is losing somebody who was never in the crop. So:
#   - the crop is the union of the last seen boxes, padded, never one person's box;
#   - a full-frame pass runs every V3_ROI_FULL_EVERY frames regardless, which is what finds
#     anyone new, and after any frame where nobody was found;
#   - a crop is only used when the last full pass actually found someone.
# Whether that cadence is enough is a question for measurement, not for this comment.
#
# Off by default until measured. 0 disables it.
ROI_IMGSZ = int(os.environ.get("V3_ROI_IMGSZ", 0))
# How often to look at the whole frame anyway. 8, one second at the CPU profile's rate.
ROI_FULL_EVERY = int(os.environ.get("V3_ROI_FULL_EVERY", 8))
# Fraction of the crop's own size added on each side. Generous: a person who falls moves fast
# and horizontally, and a body leaving the crop mid-fall is the whole event leaving.
ROI_PAD = float(os.environ.get("V3_ROI_PAD", 0.6))


def _roi_from_boxes(boxes, w, h):
    """boxes: list of (x1, y1, x2, y2) in pixels -> a padded, clamped crop covering them all."""
    if not boxes:
        return None
    x1 = min(b[0] for b in boxes)
    y1 = min(b[1] for b in boxes)
    x2 = max(b[2] for b in boxes)
    y2 = max(b[3] for b in boxes)
    pad_x = (x2 - x1) * ROI_PAD
    pad_y = (y2 - y1) * ROI_PAD
    x1 = int(max(0, x1 - pad_x))
    y1 = int(max(0, y1 - pad_y))
    x2 = int(min(w, x2 + pad_x))
    y2 = int(min(h, y2 + pad_y))
    if x2 - x1 < 32 or y2 - y1 < 32:
        return None
    return x1, y1, x2, y2


def _autodetect_device():
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"



def _ort_options():
    """onnxruntime SessionOptions sized to this container's CPU quota, or None outside the app."""
    try:
        from app.services.cpu_tuning import ort_session_options
        return ort_session_options()
    except Exception:
        return None




def _openvino_threads(model):
    """-> the thread count the compiled OpenVINO model is actually using, or None.

    Reported in the startup line because the whole point of the patch in cpu_tuning is a number
    no log would otherwise show, and getting it wrong is a 2.4x difference.
    """
    try:
        compiled = model.predictor.model.ov_compiled_model
        return compiled.get_property("INFERENCE_NUM_THREADS")
    except Exception:
        return None


def _tune_openvino():
    """Give OpenVINO the container's CPU quota before anything compiles a model."""
    try:
        from app.services.cpu_tuning import tune_openvino
        return tune_openvino()
    except Exception:
        return False


def _tune_threads():
    """-> the CPU thread count actually set, or whatever torch is already using."""
    try:
        from app.services.cpu_tuning import tune_threads
        return tune_threads()
    except Exception:
        try:
            import torch
            return torch.get_num_threads()
        except Exception:
            return 0


class V3PoseFallDetector:
    """Loads the pose extractor + ONNX classifier. One instance shared across all cameras.

    Pose backend is YOLO-pose (yolo26s-pose, native COCO-17 keypoint output -- index-
    identical to LEFT_SHOULDER/RIGHT_SHOULDER/LEFT_HIP/RIGHT_HIP below, no 33->17
    remapping needed), not MediaPipe -- see SKILL.md SS34/35. Replaced MediaPipe after
    validating end to end: better raw detection rate on hard "person down" frames
    (81% vs 72%), ~40% faster on CPU, and -- after adding flip + synthetic-occlusion
    training augmentation (SS35) specifically to close a gap found on a real clip
    involving a mobility cane and torso rotation -- matching or exceeding the prior
    MediaPipe-trained model's numbers on both GMDCSA24 held-out test sets."""

    def __init__(self, model_dir, device=None):
        """device: "cuda", "cpu", or None to auto-detect.

        Pose extraction is the whole cost of this pipeline and it runs on every frame with
        no stride, so the device choice decides whether the loop keeps up with a camera at
        all: measured ~2 fps on 2 CPU cores versus ~26 fps on this machine's GPU
        (training/bench_deployed_v3.py). At ~2 fps a live camera's frames are dropped faster
        than the 30-frame window can span a fall and recall collapses -- see
        training/eval_v3_frame_drop.py. Auto-detect rather than defaulting to CPU so a host
        that has a GPU actually uses it; V3_DEVICE overrides when that is not wanted."""
        # V3_CLASSIFIER names the classifier file inside model_dir (default: the deployed one), so
        # a candidate can ship next to production and be switched on or off from .env alone --
        # rollback is deleting one line, no files moved (9 Oct system test plan, F4).
        onnx_path = os.path.join(model_dir, os.environ.get("V3_CLASSIFIER", "fall_classifier_v3.onnx"))
        # V3_POSE_MODEL names a different pose checkpoint in the same directory. It exists for
        # the CPU-only production server, where the pose pass is the entire frame budget:
        # yolo26n-pose runs in about half the time of yolo26s-pose at every input size, so the
        # real choice there is not "which size" but "which model at which size" -- n at 640
        # costs the same as s at 384. Accuracy has to decide that, not speed alone.
        yolopose_path = os.path.join(model_dir, os.environ.get("V3_POSE_MODEL", "yolo26s-pose.pt"))

        if device is None:
            device = os.environ.get("V3_DEVICE") or _autodetect_device()
        self.device = device
        # Module level too, so the status endpoint can report the device the detector really
        # loaded on rather than the string someone may or may not have set in the environment.
        global LOADED_DEVICE
        LOADED_DEVICE = device

        providers = ["CPUExecutionProvider"]
        if device == "cuda" and "CUDAExecutionProvider" in ort.get_available_providers():
            # The classifier is tiny, so this is a nice-to-have; the CPU-only onnxruntime
            # build has no CUDA provider and asking for it anyway is a hard error.
            providers.insert(0, "CUDAExecutionProvider")
        # Sized to the container's CPU quota, not the host's core count -- see
        # app/services/cpu_tuning. Left alone, onnxruntime opens twenty threads inside a
        # four-CPU container for a 560 KB model and takes 1.59 ms per window instead of 0.19.
        sess_opts = _ort_options()
        self.session = ort.InferenceSession(onnx_path, sess_options=sess_opts,
                                            providers=providers)
        _check_feature_width(self.session, onnx_path)
        # Which model is actually running, provably: file names + content hashes + threshold in
        # the log at start, and on the module for the status endpoint. A switch that silently
        # did not take effect is otherwise indistinguishable from one that did.
        global LOADED_IDENTITY
        LOADED_IDENTITY = {"classifier": os.path.basename(onnx_path), "classifier_sha": _sha12(onnx_path),
                           "pose": os.path.basename(yolopose_path.rstrip("/\\")),
                           "pose_sha": _sha12(yolopose_path), "threshold": THRESHOLD,
                           "num_poses": NUM_POSES}
        print("[V3] model identity: %s" % LOADED_IDENTITY, flush=True)

        # V3_ENSEMBLE: comma-separated extra classifier files (paths, or bare names inside
        # model_dir) whose sigmoid outputs are averaged with the main one. Training the same
        # recipe with different seeds moves results by 1-3 clips on every surface (SS49), which
        # is pure variance rather than any seed knowing something; averaging them is the
        # standard way to spend that variance instead of gambling on one draw. Off by default:
        # it changes the detector, so it only ships if both the accuracy and the per-window
        # cost are measured -- the classifier is small but it runs once per tracked person per
        # frame, so three of them is not automatically free.
        self.extra_sessions = []
        for name in filter(None, (n.strip() for n in os.environ.get("V3_ENSEMBLE", "").split(","))):
            path = name if os.path.isabs(name) or os.sep in name else os.path.join(model_dir, name)
            extra = ort.InferenceSession(path, sess_options=sess_opts, providers=providers)
            _check_feature_width(extra, path)
            self.extra_sessions.append(extra)

        # An OpenVINO export is a directory, and ultralytics cannot infer the task from one, so
        # it has to be told. OpenVINO is 1.3-1.5x faster than PyTorch on CPU for the identical
        # model -- 50.7 ms against 69.9 at input size 320 -- and its output matches: over the
        # same frames, person-found agreed 12/12 and the keypoints differed by 0.00054 frame
        # widths, which is ten times closer than the gap between two different pose models.
        # The export bakes in its input size, so the directory and V3_IMGSZ must agree;
        # tools/check_config_coherence.py checks that.
        ov_threads = None
        if os.path.isdir(yolopose_path):
            _tune_openvino()
            self.pose_model = YOLO(yolopose_path, task="pose")
            ov_threads = _openvino_threads(self.pose_model)
        else:
            self.pose_model = YOLO(yolopose_path)
        # After YOLO(), never before: ultralytics sets torch's thread count itself while
        # building a model, from the host's core count, which inside a container is a number
        # of threads that cannot all run. Measured at 100 ms per detection against 68 ms with
        # the quota, on the four-CPU configuration the production server has, and it took the
        # live camera loop there from 3.4 to 6.9 fps.
        #
        # Only on CPU. On a GPU machine torch's threads do preprocessing rather than the model
        # itself, the tuning there was measured with the thread count as it stood, and there is
        # nothing to win by changing a configuration whose numbers are already published.
        threads = _tune_threads() if device == "cpu" else 0
        members = 1 + len(self.extra_sessions)
        print(f"[V3] pose backend on {device}"
              + (f", {threads} CPU thread(s)" if threads else "")
              + (f", OpenVINO using {ov_threads} thread(s)" if ov_threads else "")
              + (f", classifier ensemble of {members}" if members > 1 else ""))

    def extract_keypoints(self, frame_bgr):
        """-> ((17, 3) COCO17 [x, y, confidence], person_found: bool) for the FIRST
        detected person only. Zeros + False if nobody detected. Single-person callers
        (training/eval scripts, all validated against this exact signature -- see
        SKILL.md) keep using this; camera_manager.py uses extract_all_keypoints /
        detect_v3_fall_multi below for multi-person tracking instead."""
        people = self.extract_all_keypoints(frame_bgr)
        if not people:
            return np.zeros((NUM_KEYPOINTS, 3), dtype=np.float32), False
        return people[0][0], True

    def reset_roi_state(self, phase=0):
        """Forget where people were: call at the start of every new video source.

        With V3_ROI_IMGSZ set, extract_all_keypoints remembers the last boxes and counts frames
        to schedule its full-frame pass. That memory belongs to ONE source. Carried into the
        next -- the next camera task in the same worker process, or the next clip in an
        evaluation -- the first frame is cropped at another scene's boxes and the full-pass
        schedule starts mid-cycle. Measured: an evaluation that reused one detector across
        segments scored 8.mp4#1 as caught; the same segment alone peaks at 0.645 and is not.
        `phase` (0 .. V3_ROI_FULL_EVERY-1) shifts the full-pass schedule, so an evaluation can
        report the spread over phases instead of whichever phase it happened to get."""
        self._roi_frame = int(phase)
        self._roi_boxes = None

    def extract_all_keypoints(self, frame_bgr):
        """-> list of (kpts17 (17,3) [x, y, confidence], hip_center (2,)) for every
        person detected this frame, up to NUM_POSES, sorted by detection confidence
        (highest first). Empty list if nobody detected.

        With V3_ROI_IMGSZ set, most frames are a crop around where the people were, run at a
        smaller input size -- see ROI_IMGSZ. Keypoints are mapped back to the whole frame
        before they are returned, so nothing downstream can tell the difference.
        """
        # Known inefficiency, left alone deliberately: with a crop configured this still
        # preprocesses the WHOLE frame and then uses a part of it. Preprocessing a dark 1080p
        # frame is 47 ms, so anyone enabling V3_ROI_IMGSZ on CPU should move this below the
        # crop -- which also changes what "dark" means, from the room's average to the
        # person's own lighting, and that is a different setting needing its own measurement.
        # Not done here because the crop measured as not worth deploying (docs/next_steps 15).
        frame_bgr, _ops = preprocess_frame(frame_bgr)   # V3_PREPROCESS; a no-op unless it is configured
        h, w = frame_bgr.shape[:2]

        roi, imgsz = None, IMGSZ
        if ROI_IMGSZ:
            self._roi_frame = getattr(self, '_roi_frame', 0) + 1
            due_full = (self._roi_frame % max(ROI_FULL_EVERY, 1)) == 0
            if not due_full:
                roi = _roi_from_boxes(getattr(self, '_roi_boxes', None), w, h)
            if roi is not None:
                imgsz = ROI_IMGSZ

        source = frame_bgr[roi[1]:roi[3], roi[0]:roi[2]] if roi is not None else frame_bgr
        result = self.pose_model.predict(source, verbose=False, conf=POSE_CONF, classes=[0],
                                         device=self.device, imgsz=imgsz)[0]
        people = []
        if result.keypoints is None or len(result.keypoints.xy) == 0:
            # Nobody in the crop is not nobody in the room. Drop the crop so the next frame
            # looks at everything: holding a stale one here is how a person who walked out of
            # it would stay invisible indefinitely.
            if ROI_IMGSZ:
                self._roi_boxes = None
            return people
        box_confs = result.boxes.conf.cpu().numpy()
        order = np.argsort(-box_confs)[:NUM_POSES]
        # Where to look next time, in whole-frame pixels. Taken from every detection rather
        # than the best one, so a second person keeps the crop open for both.
        if ROI_IMGSZ:
            xyxy = result.boxes.xyxy.cpu().numpy()
            off_x, off_y = (roi[0], roi[1]) if roi is not None else (0, 0)
            self._roi_boxes = [(b[0] + off_x, b[1] + off_y, b[2] + off_x, b[3] + off_y)
                               for b in xyxy]
        for i in order:
            kxy = result.keypoints.xy[i].cpu().numpy()
            kconf = (result.keypoints.conf[i].cpu().numpy()
                     if result.keypoints.conf is not None else np.ones(NUM_KEYPOINTS, dtype=np.float32))
            kpts17 = np.zeros((NUM_KEYPOINTS, 3), dtype=np.float32)
            # Back to whole-frame coordinates before normalising, so a crop never changes what
            # anything downstream sees -- the classifier is trained on frame-relative values.
            kpts17[:, 0] = (kxy[:, 0] + (roi[0] if roi is not None else 0)) / w
            kpts17[:, 1] = (kxy[:, 1] + (roi[1] if roi is not None else 0)) / h
            kpts17[:, 2] = kconf
            hip_center = (kpts17[LEFT_HIP, :2] + kpts17[RIGHT_HIP, :2]) / 2.0
            people.append((kpts17, hip_center))
        return people

    def count_people(self, frame_bgr, imgsz=None):
        """-> how many people are in this frame, for the alone-detection question.

        Separate from the detection path on purpose, and run at its own input size. Alone
        detection asks "is exactly one person present", and the pose model answers that far
        better with more pixels: scored against Gemini-verified counts on the 77-frame
        ground-truth set (`training/gt_compare_binary.py`),

            yolo26l detect, the model this replaces   80.5%
            yolo26s-pose at 320 (the CPU profile)     74.0%
            yolo26s-pose at 960                       83.1%

        So the counting pass uses 960 regardless of what detection runs at. It costs about
        184 ms on four CPU cores, which at one check every twenty seconds is under one per
        cent of the budget -- against a whole second model, a second video stream and a second
        Celery slot per camera, which is what it replaces.

        Not capped to NUM_POSES: that cap exists to bound tracking work, and here a crowd of
        thirteen needs to read as "not one person", not as "NUM_POSES people".
        """
        frame_bgr, _ops = preprocess_frame(frame_bgr)   # V3_PREPROCESS; a no-op unless it is configured
        result = self.pose_model.predict(
            frame_bgr, verbose=False, conf=POSE_CONF, classes=[0],
            device=self.device, imgsz=imgsz or COUNT_IMGSZ)[0]
        if result.keypoints is None or result.keypoints.xy is None:
            return 0
        return int(len(result.keypoints.xy))

    def extract_tracked_keypoints(self, frame_bgr):
        """-> list of (track_id, kpts17, hip_center), ids assigned by ultralytics' tracker.

        persist=True keeps the tracker's state between calls, which means this detector
        instance is tied to ONE video stream -- model_manager hands out a detector per camera
        for exactly that reason. Detections without an id (ByteTrack emits those on the first
        frames of a new track) are skipped rather than given a synthetic id, so a person only
        enters a window once their identity is stable.
        """
        frame_bgr, _ops = preprocess_frame(frame_bgr)   # V3_PREPROCESS; a no-op unless it is configured
        h, w = frame_bgr.shape[:2]
        result = self.pose_model.track(
            frame_bgr, persist=True, tracker="bytetrack.yaml", verbose=False,
            conf=POSE_CONF, classes=[0], device=self.device, imgsz=IMGSZ)[0]
        people = []
        if result.keypoints is None or result.boxes is None or result.boxes.id is None:
            return people
        ids = result.boxes.id.int().cpu().numpy()
        for i, track_id in enumerate(ids[:NUM_POSES]):
            kxy = result.keypoints.xy[i].cpu().numpy()
            kconf = (result.keypoints.conf[i].cpu().numpy()
                     if result.keypoints.conf is not None else np.ones(NUM_KEYPOINTS, dtype=np.float32))
            kpts17 = np.zeros((NUM_KEYPOINTS, 3), dtype=np.float32)
            kpts17[:, 0] = kxy[:, 0] / w
            kpts17[:, 1] = kxy[:, 1] / h
            kpts17[:, 2] = kconf
            hip = (kpts17[LEFT_HIP, :2] + kpts17[RIGHT_HIP, :2]) / 2.0
            people.append((int(track_id), kpts17, hip))
        return people

    def predict_window(self, raw_window):
        """raw_window: (WINDOW_SIZE, 17, 3) -> fall probability in [0, 1].

        With V3_ENSEMBLE set, the probabilities are averaged rather than the logits: the
        threshold is calibrated against a probability, and averaging logits would shift what
        0.65 means."""
        feat = _normalize_and_velocity(raw_window).reshape(1, WINDOW_SIZE, -1).astype(np.float32)

        def prob(session):
            logit = session.run(["logit"], {"input": feat})[0]
            return float(1.0 / (1.0 + np.exp(-logit.reshape(-1)[0])))

        p = prob(self.session)
        if not self.extra_sessions:
            return p
        return (p + sum(prob(s) for s in self.extra_sessions)) / (1 + len(self.extra_sessions))


# Env-overridable so the multi-person false-positive sweep can A/B it (see
# training/diagnose_multi_person.py: most multi-person alerts fire from windows that are
# mostly held copies rather than genuinely observed frames).
# How many real frames a window must hold before the classifier will score it at all.
# 0 disables this and restores the original behaviour: wait for a completely full window.
#
# The problem it exists for: the classifier produces no number whatsoever until the buffer
# holds WINDOW_SIZE frames with a person in them, which at the CPU profile's 8 fps is nearly
# two seconds of continuously visible person. Sixteen of URFD's sixty fall clips never get
# one, and that is not only a dataset artefact -- somebody walking into a room and falling
# within the first second is exactly the case the window cannot see, and it gets worse as the
# machine gets slower.
#
# A padded window is a weaker piece of evidence than a full one, so this is a real trade and
# the value is measured, not assumed. On a camera that has been running the window is always
# full, so nothing here changes steady-state behaviour -- only the first seconds after a
# person appears.
#
# MEASURED, both profiles, on the 220-clip lab set with the reserved URFD half confirming:
#
#   CPU  320 @ 8 fps    URFD falls 32/60 -> 45/60, held-out clean 44/56 -> 41/56
#   GPU  960 @ 20 fps   URFD falls 45/60 -> 56/60, held-out clean 41/56 -> 40/56
#
# On the GPU profile URFD clean does not move at all (33/40 either way) and exactly one
# held-out clip newly false-alarms. The clips it gains are the ones the window could never
# fill: the ceiling camera and the falls from standing.
#
# 4 is the peak of the curve, not the lowest value that works -- 6 gives 38/60 and 2 gives
# 41/60, both worse than 4 on the CPU profile.
#
# What it changes in kind, and the reason it costs a false alarm on someone lying down: with a
# padded window the detector can alert on a person who is ALREADY on the floor when it first
# sees them, not only on the transition. For a fall detector that is right -- somebody who
# fell before the camera could see them still needs help -- and it is why `fall-20-cam1`,
# where the ceiling camera opens on someone already down, now alerts three frames in.
PARTIAL_MIN = int(os.environ.get("V3_PARTIAL_MIN", 4))

MIN_PERSON_FRACTION = float(os.environ.get("V3_MIN_PERSON_FRACTION", 0.2))
# Fraction of frames in a window that must have a detected person before trusting the
# classifier's output. Deliberately low: MediaPipe's per-frame pose detection is much
# less reliable once someone is on the ground (prone/occluded bodies aren't what it was
# mostly trained on) -- a real CAUCAFall forward-fall clip only had a person detected in
# 40% of frames, concentrated in bursts, not a steady rate. 0.7 was tuned only against an
# empty-room case (which sits at ~0% detected) and ended up suppressing genuine falls too.
RESET_PERSON_FRACTION = 0.05
# Below this, treat it as a genuinely empty scene and fully reset state. Between this and
# MIN_PERSON_FRACTION, hold the last known state instead of resetting -- see below.
COLLAPSE_CONFIDENCE = 0.6
# Whether the collapse rule fires at all. It was added for MediaPipe, which lost people
# entirely once they were prone; YOLO-pose detects prone frames far more reliably (81.2% vs
# 71.7%, SS34), so the rule may now cost more than it earns -- it reports probability 1.0 on
# a person VANISHING, which is also what a night scene or a spurious detection looks like.
# Env-overridable so that is measured rather than argued.
COLLAPSE_ENABLED = os.environ.get("V3_COLLAPSE_ENABLED", "1") != "0"
# If the model was this confident right before person-detection collapsed to ~zero,
# treat the collapse itself as a fall signal (see detect_v3_fall).
# 0.2 still rejects the empty-room case while letting spotty-but-real detections through.
# Env-overridable so its effect can be measured by A/B rather than assumed (set very high
# to reproduce the pre-guard behaviour of holding the last pose indefinitely).
MAX_HELD_RUN = int(os.environ.get("V3_MAX_HELD_RUN", 5))
# How many CONSECUTIVE undetected frames may be back-filled with the last real keypoints
# before this stops writing to the window entirely. Holding is what SS18 validated as the
# fix for short (1-2 frame) dropouts, but SS24 traced two high-confidence false alerts
# (0.92-0.96 with person_found=False) to the opposite extreme: person_found flickering for
# ~1-2s fills the 30-frame window with mostly repeated copies of one earlier pose, and the
# classifier scores that frozen-then-jump pattern as fall-like. A plain person_fraction
# gate can't separate those cases -- a genuine CAUCAFall forward fall sits at 40% detected,
# inside the same band -- so this caps the RUN LENGTH instead of the total fraction. Past
# the cap the window is frozen (nothing appended) rather than padded further, so the
# classifier keeps re-scoring the last genuinely observed frames instead of a synthetic
# pattern, which also preserves a real fall's pre-dropout signal (the case
# MIN_PERSON_FRACTION exists to protect). person_flags still records every miss, so the
# fraction gates above keep responding normally.
#
# MEASURED EFFECT ON CURRENT DATA: none, on any clip available here. GMDCSA24 held-out is
# bit-identical with and without it (15/15 falls, 9/16 ADL clean, eval_v3_on_gmdcsa24_val.py),
# and on the Test/ clips with the worst dropouts -- 10/11/6.mp4, where check_held_run.py
# measures runs of 122-359 consecutive misses -- both settings fire zero alerts, because the
# person_fraction gates already suppress everything there (ab_held_run_on_test.py). SS24's
# mechanism was observed under MediaPipe; YOLO-pose detects the hard prone frames far more
# reliably (81.2% vs 71.7%, SS34), so the flicker pattern that produced it no longer appears
# in this data. Kept as a cheap guard against that documented failure mode returning, NOT
# because it was shown to fix anything -- do not cite it as an accuracy improvement.


# UPRIGHT_COS: how close to vertical a torso has to be to count as standing, as the cosine of
# its angle from vertical -- 0.70 is about 45 degrees. Read straight from the keypoints, so it
# needs no calibration, no reference height and no knowledge of where the camera is.
#
# It exists so the alerting side can use the one piece of evidence a human uses and the
# classifier cannot see: **is the person STILL on the floor, some seconds after the alert.**
# A window is one second long; this is about the ten that follow it.
#
# MEASURED, on the cached pose stream (training/measure/recovery_after_alert.py), counting only
# alerts with at least sixteen scored frames afterwards:
#
#     real falls, GMDCSA24        35 usable    2 got back up  ( 6%)
#     false alarms, val ADL        6 usable    3 got back up  (50%)
#     false alarms, train50        2 usable    1 got back up  (50%)
#     real falls, URFD wall cam    5 usable    2 got back up
#     real falls, URFD ceiling     0 usable    the clips end too soon to ask
#
# **This must never cancel an alert.** It separates, but six per cent of real falls would be
# suppressed by it, silently, by a rule nobody sees -- and a suppressed fall is the exact
# failure this system exists to prevent. Used the other way round it costs nothing and asserts
# nothing false: "still on the floor after ten seconds" is a fact, it holds for 94% of real
# falls, and it can only raise urgency. That is the same footing the tier already stands on --
# escalate because nobody answered, not because the model was confident.
UPRIGHT_COS = float(os.environ.get("V3_UPRIGHT_COS", 0.70))


def torso_cos(kpts):
    """cos of the torso's angle from vertical, or None when the torso is not measurable."""
    hip = (kpts[LEFT_HIP, :2] + kpts[RIGHT_HIP, :2]) / 2.0
    shoulder = (kpts[LEFT_SHOULDER, :2] + kpts[RIGHT_SHOULDER, :2]) / 2.0
    vec = shoulder - hip
    length = float(np.linalg.norm(vec))
    if length < 1e-3:
        return None
    return abs(float(vec[1])) / length


def is_upright(kpts):
    """-> True / False / None (not measurable this frame)."""
    cos = torso_cos(kpts)
    return None if cos is None else cos >= UPRIGHT_COS


class V3FallDetectionState:
    """Per-camera state: rolling keypoint buffer + smoothing history."""

    def __init__(self):
        self.raw_buffer = deque(maxlen=WINDOW_SIZE)
        self.person_flags = deque(maxlen=WINDOW_SIZE)
        self.frames_since_infer = 0
        self.recent_flags = deque(maxlen=SMOOTH_OF)
        self.has_run_once = False
        self.last_probability = 0.0
        self.last_detected = False
        self.collapse_fired = False
        self.last_good_kpts = None
        self.held_run = 0
        # Frames since this person was last seen upright, and whether they ever have been.
        # Counted only on frames where the torso was actually measurable, so a tracking
        # dropout does not accumulate evidence that the person is still down -- see
        # UPRIGHT_COS. frames_since_upright is what the alerting side reads; it is a count of
        # observations, and the camera loop knows its own frame rate to turn it into seconds.
        self.frames_since_upright = 0
        # Frames since last seen upright in which the person was actually SEEN lying down.
        # frames_since_upright alone cannot tell "on the floor, partly hidden" from "walked
        # out of view"; this is the positive evidence the still-down rule also requires.
        self.frames_seen_down = 0
        self.ever_upright = False

    def is_ready(self):
        return len(self.raw_buffer) == WINDOW_SIZE


def _step_person(kpts, person_found, state: V3FallDetectionState,
                  fall_detector: V3PoseFallDetector, threshold):
    """One person's rolling-window update + classification for this frame -- the
    exact state machine detect_v3_fall validated (SS9-SS18), factored out so
    detect_v3_fall (single person) and detect_v3_fall_multi (N people, one of these
    states per tracked person) share identical logic instead of two copies drifting
    apart. Returns (detected, probability, label)."""
    if person_found:
        state.last_good_kpts = kpts
        state.held_run = 0
        state.raw_buffer.append(kpts)
        upright = is_upright(kpts)
        if upright is True:
            state.frames_since_upright = 0
            state.frames_seen_down = 0
            state.ever_upright = True
        else:
            if upright is False:
                state.frames_seen_down += 1
            # Counted whether the torso reads "down" or cannot be read at all (None). The only
            # evidence that somebody got back up is SEEING them upright; an unreadable torso is
            # not that evidence. This used to count only `upright is False`, so the counter ran
            # on a different clock from the camera loop's frame counter it is compared against
            # -- see the matching increment in the not-found branch below.
            state.frames_since_upright += 1
    else:
        # Not seen this frame. Still a frame in which they were not seen getting up, so it
        # counts. Before this, a person lying on the floor and partly hidden -- by a bed edge,
        # by their own position, or simply lost in a night-vision frame, which happens in ~12%
        # of frames on simulated IR (training/measure/ir_keypoint_degradation.py) -- stopped
        # accumulating, and once more than a fifth of the follow-up window went unseen the
        # still-down rule (notification_service.still_down_confirmed, 0.8 of the window)
        # concluded they had got up. Found by Gemini's R5/R6 review, 2026-09-30: it guessed the
        # two counters shared a clock, and checking the guess showed they did not.
        state.frames_since_upright += 1
        # A momentary tracking dropout (1-2 frames, common mid-fall/near occlusion --
        # see MIN_PERSON_FRACTION above) makes extract_keypoints return an all-zero
        # vector. Feeding that raw into the window creates a real->zero->real jump
        # that reads as a huge velocity spike -- confirmed as part of the false-alarm
        # mechanism in SKILL.md SS18 (alongside plain frame-to-frame jitter, which
        # _smooth_keypoints handles separately). Hold the last real detection instead
        # of zero-filling; person_flags still records the true miss for MIN_PERSON_FRACTION.
        state.held_run += 1
        if state.last_good_kpts is None:
            state.raw_buffer.append(kpts)  # nothing real seen yet -- zeros are all there is
        elif state.held_run <= MAX_HELD_RUN:
            state.raw_buffer.append(state.last_good_kpts)
        # Past MAX_HELD_RUN: append nothing, freezing the window on the last genuinely
        # observed frames instead of packing it with more copies of one pose (SS24).
    state.person_flags.append(person_found)
    state.frames_since_infer += 1

    if not state.is_ready():
        if PARTIAL_MIN <= 0 or len(state.raw_buffer) < PARTIAL_MIN:
            return False, 0.0, "Analyzing..."
        # Otherwise fall through and score a padded window -- see PARTIAL_MIN.

    person_fraction = sum(state.person_flags) / len(state.person_flags)
    if person_fraction < RESET_PERSON_FRACTION:
        # Essentially nobody detected across the whole window -- normally a genuinely
        # empty room/person off-camera, safe to fully reset. BUT: if confidence was high
        # right before detection collapsed to ~zero, that transition itself (visible and
        # apparently falling -> suddenly untrackable) is consistent with a real collapse,
        # not someone calmly walking off -- confirmed via batch testing, where two real
        # falls peaked at 0.73/0.69 then MediaPipe lost the person entirely for the rest
        # of the clip. Fire one alert on that transition instead of silently discarding it.
        was_collapse = (COLLAPSE_ENABLED and state.last_probability > COLLAPSE_CONFIDENCE
                        and not state.collapse_fired)
        collapse_probability = state.last_probability
        state.recent_flags.clear()
        state.last_probability = 0.0
        state.last_detected = False
        if was_collapse:
            state.collapse_fired = True
            # The score reported is the last one the classifier actually produced, NOT 1.0.
            # This branch fires because the person stopped being detectable, which is the
            # weakest evidence in the whole pipeline -- a night scene and a spurious detection
            # look the same -- and reporting maximum confidence for it put the highest number
            # the system can produce on the thinnest thing it knows. The number reaches a
            # human: the dashboard prints it as "score 100".
            #
            # MEASURED, both profiles with the rule on and off: bit-identical on CPU, and on
            # GPU identical on every held-out surface (URFD 56/60 falls, 41/56 held-out clean,
            # val 7/16, train50 21/25) with one GMDCSA24 fall the difference -- and most
            # GMDCSA24 clips are training clips. So the rule is neither earning nor costing
            # anything measurable here, which is why it is kept as a safety net rather than
            # removed, and why the misleading part of it is the part that was changed.
            return True, collapse_probability, "fall"
        return False, 0.0, "no_person"

    if person_fraction < MIN_PERSON_FRACTION:
        # Some detections, but too few to trust a fresh prediction from this window --
        # don't run the classifier on effectively-degraded input. Importantly, do NOT
        # clear prior state here: a person who just fell is lying down, which MediaPipe
        # often fails to track for a stretch right after the fall -- clearing on every
        # low-detection window was wiping out the fall signal at exactly the moment it
        # mattered (confirmed via batch testing: probability climbed to 0.73 right
        # before the person went down, then got erased by this gate). Hold the last
        # known state instead of erasing it.
        label = "fall" if state.last_detected else "no_person"
        return state.last_detected, state.last_probability, label

    # Only re-run the classifier every STRIDE frames -- matches the window stride the
    # model was validated on, and keeps this affordable at real camera frame rates.
    if state.has_run_once and state.frames_since_infer < STRIDE:
        label = "fall" if state.last_detected else "no_fall"
        return state.last_detected, state.last_probability, label

    state.frames_since_infer = 0
    state.has_run_once = True
    state.collapse_fired = False  # person is reliably visible again -- a future collapse is a new event
    raw_window = np.stack(state.raw_buffer, axis=0)
    if len(raw_window) < WINDOW_SIZE:
        # Pad at the FRONT by repeating the earliest observed frame: "the person was
        # standing as they are now, before we first saw them". That keeps whatever motion
        # exists in the real frames at the end of the window, where a fall's signature
        # lives, and adds no velocity of its own (repeated frames differ by zero).
        pad = np.repeat(raw_window[:1], WINDOW_SIZE - len(raw_window), axis=0)
        raw_window = np.concatenate([pad, raw_window], axis=0)
    probability = fall_detector.predict_window(raw_window)
    state.recent_flags.append(probability > threshold)
    state.last_probability = probability
    state.last_detected = sum(state.recent_flags) >= SMOOTH_NEED

    label = "fall" if state.last_detected else "no_fall"
    return state.last_detected, probability, label


def alert_result(results):
    """The one (track_id, detected, probability, label, centroid) an alert is credited to.

    A person the detector has FLAGGED wins over a higher-scoring bystander. `detected` comes
    from smoothing over recent frames, so the flagged person's score this frame can sit below
    somebody else's; taking the plain maximum then named the wrong person, and the still-down
    follow-up watches whoever is named here. Only when nobody is flagged does the plain maximum
    stand, and that is for logging, not alerting. Empty input -> a no-person placeholder.

    Single definition: the camera loop and every measurement script call this, because four
    copies of the old one-liner were found after the loop alone had been fixed (R5; Gemini's
    review, 2026-09-30).
    """
    if not results:
        return (None, False, 0.0, "no_person", None)
    flagged = [r for r in results if r[1]]
    return max(flagged or results, key=lambda r: r[2])


def detect_v3_fall(frame, state: V3FallDetectionState, fall_detector: V3PoseFallDetector,
                    config, camera=None, threshold=None):
    """Single-person entry point -- same signature/return shape as the old
    detect_v2_fall_only_onnx, so it's a drop-in replacement: returns
    (detected, probability, label, frame). Used by all the training/eval scripts;
    camera_manager.py uses detect_v3_fall_multi instead."""
    threshold = threshold if threshold is not None else THRESHOLD
    kpts, person_found = fall_detector.extract_keypoints(frame)
    detected, probability, label = _step_person(kpts, person_found, state, fall_detector, threshold)
    return detected, probability, label, frame


MAX_TRACK_DISTANCE = 0.15
# Max normalized hip-center movement (as a fraction of frame width/height) between
# consecutive frames for a detection to count as "the same person" -- chosen as a
# generous-but-not-unlimited gate: a person walking normally moves much less than
# this between frames at real camera fps, but it's loose enough to survive MediaPipe's
# own per-frame jitter (SS18) without needing a real motion model.
MAX_MISSED_FRAMES = WINDOW_SIZE
# How many consecutive frames a track can go undetected (occluded, briefly off-camera)
# before being dropped -- one full window's worth, so a track surviving a gap this
# long still has stale-but-recent history rather than restarting cold.
# V3_TRACK_REASSOC: let a recently lost track reclaim a person over a wider, unambiguous gate --
# see PersonTracker._match_reassoc. Off by default; FAILED MULTI-REASSOC-v1's gates (2026-10-01,
# owner segments x 8 phases, cache replay): caught 33.8 -> 33.6 /75, FA 1.8 -> 2.0 /13 (a new false
# alarm on 4.mp4#3), multi 10.9 -> 10.6 /25. On 1.mp4#15, the case it was built for, the fallers
# are undetected for the whole 1.3 s descent and come back 0.38 away: there is no descent in any
# window to keep continuous. Kept as a switch only; the lever is detection during the fall.
REASSOC = os.environ.get("V3_TRACK_REASSOC", "0") == "1"
# V3_HELD_ALERT_MAX=k (P3, overnight exploration 8 Oct; OFF by default = 0 = unchanged behaviour): a track that has
# not been SEEN for more than k consecutive frames may not START an alert -- a held pose is a copy of an old frame,
# and 14 of 22 first wrong-person/far alerts in the 7 Oct diagnosis came from such held tracks. The collapse rule
# (a visible, high-scoring person who then vanishes) is exempt, and an alert already running is not cut.
HELD_ALERT_MAX = int(os.environ.get("V3_HELD_ALERT_MAX", 0))
REASSOC_GATE_STEP = 0.01   # gate grows by this per frame missed ...
REASSOC_GATE_MAX = 0.30    # ... up to twice the one-frame gate
REASSOC_MARGIN = 0.05      # runner-up must be at least this much farther, both ways
# V3_TRACK_TRACE: record every association decision on tracker.trace (diagnostics only).
TRACK_TRACE = os.environ.get("V3_TRACK_TRACE", "0") == "1"


class PersonTracker:
    """Nearest-hip-center tracker so each person's rolling window doesn't get
    contaminated by a different person's keypoints frame to frame. Not a real
    multi-object tracker -- no motion model, no re-identification after a track is
    dropped. Fine for the same-room, few-people, mostly-static-camera case this is
    built for; people crossing paths closely enough to swap positions within one
    MAX_TRACK_DISTANCE step could swap track IDs. That's a state-continuity glitch,
    not a missed detection -- both people are still tracked and classified."""

    def __init__(self, reassoc=None):
        self.next_id = 0
        self.tracks = {}  # track_id -> {"centroid": (x, y), "missed": int}
        self.reassoc = REASSOC if reassoc is None else reassoc
        self.trace = [] if TRACK_TRACE else None

    def update(self, detections):
        """detections: list of (kpts, hip_center) from extract_all_keypoints.
        Returns list of (track_id, kpts_or_None, seen: bool) for every currently
        active track, including ones not matched this frame (kpts=None, seen=False)."""
        unmatched = list(range(len(detections)))
        matched = {}

        if self.reassoc:
            matched, unmatched = self._match_reassoc(detections)
        else:
            for track_id, t in sorted(self.tracks.items()):
                if not unmatched:
                    break
                dists = sorted(
                    ((float(np.linalg.norm(t["centroid"] - detections[i][1])), i) for i in unmatched),
                    key=lambda x: x[0],
                )
                best_dist, best_i = dists[0]
                if best_dist < MAX_TRACK_DISTANCE:
                    matched[track_id] = best_i
                    unmatched.remove(best_i)

        results = []
        for track_id, t in self.tracks.items():
            if track_id in matched:
                kpts, centroid = detections[matched[track_id]]
                t["centroid"] = centroid
                t["missed"] = 0
                results.append((track_id, kpts, True))
            else:
                t["missed"] += 1
                results.append((track_id, None, False))

        for i in unmatched:
            kpts, centroid = detections[i]
            track_id = self.next_id
            self.next_id += 1
            self.tracks[track_id] = {"centroid": centroid, "missed": 0}
            results.append((track_id, kpts, True))
            if self.trace is not None:
                self.trace.append({"event": "birth", "det": i, "id": track_id,
                                   "at": [round(float(c), 4) for c in centroid]})

        self.tracks = {tid: t for tid, t in self.tracks.items() if t["missed"] <= MAX_MISSED_FRAMES}
        return [r for r in results if r[0] in self.tracks]

    def _match_reassoc(self, detections):
        """V3_TRACK_REASSOC (Codex design MULTI-REASSOC-v1, AI_HANDOFF 2026-10-01).

        A person who falls is often not detected while going down and comes back a second later
        on the floor, further from where they were than one frame's 0.15 gate -- so the plain
        tracker gives them a NEW id with an empty window and the fall motion is split in two
        (owner segment 1.mp4#15). Here a recently lost track may reclaim a detection over a gate
        that widens with how long it has been missing, but only when the pairing is unambiguous:
        mutual nearest neighbours, a clear runner-up margin both ways, and never a detection that
        sits where a still-visible person just was. Ambiguity makes a new id, as before: a missed
        re-link costs one fall's continuity, a wrong one feeds two people into one window.
        Constants are design choices fixed before any replay, not fitted.
        Returns (matched {track_id: det_index}, unmatched [det_index])."""
        unmatched = list(range(len(detections)))
        matched = {}
        active = {tid: t for tid, t in self.tracks.items() if t["missed"] == 0}
        prev_active = [t["centroid"] for t in active.values()]
        # 1. Tracks seen last frame: exactly the plain tracker's rule, restricted to them.
        for track_id, t in sorted(active.items()):
            if not unmatched:
                break
            best_dist, best_i = min(
                (float(np.linalg.norm(t["centroid"] - detections[i][1])), i) for i in unmatched)
            if best_dist < MAX_TRACK_DISTANCE:
                matched[track_id] = best_i
                unmatched.remove(best_i)
                if self.trace is not None:
                    self.trace.append({"event": "active", "id": track_id, "det": best_i,
                                       "dist": round(best_dist, 4)})
        # 2. Lost tracks (1 <= missed <= MAX_MISSED_FRAMES, counted before this update).
        lost = sorted(tid for tid, t in self.tracks.items() if 1 <= t["missed"] <= MAX_MISSED_FRAMES)
        cand = [i for i in unmatched
                if all(float(np.linalg.norm(c - detections[i][1])) >= MAX_TRACK_DISTANCE
                       for c in prev_active)]
        if self.trace is not None:
            for i in unmatched:
                if i not in cand:
                    self.trace.append({"event": "reject_near_active", "det": i})
        if not lost or not cand:
            return matched, unmatched
        D = {(tid, i): float(np.linalg.norm(self.tracks[tid]["centroid"] - detections[i][1]))
             for tid in lost for i in cand}
        accepted = []
        for tid in lost:
            m = self.tracks[tid]["missed"]
            gate = min(REASSOC_GATE_MAX, MAX_TRACK_DISTANCE + REASSOC_GATE_STEP * m)
            row = sorted((D[(tid, i)], i) for i in cand)
            d, i = row[0]
            col = sorted((D[(t2, i)], t2) for t2 in lost)
            row_next = row[1][0] if len(row) > 1 else float("inf")
            col_next = col[1][0] if len(col) > 1 else float("inf")
            why = None
            if d >= gate:
                why = "gate"
            elif col[0][1] != tid:
                why = "not_mutual"
            elif row_next < d + REASSOC_MARGIN or col_next < d + REASSOC_MARGIN:
                why = "ambiguous"
            if self.trace is not None:
                self.trace.append({"event": "lost_try", "id": tid, "missed": m, "det": i,
                                   "dist": round(d, 4), "gate": round(gate, 4),
                                   "result": why or "accept"})
            if why is None:
                accepted.append((d, tid, i))
        for d, tid, i in sorted(accepted):
            if tid in matched or i not in unmatched:
                continue
            matched[tid] = i
            unmatched.remove(i)
        return matched, unmatched


class V3MultiPersonFallState:
    """Per-camera state for multi-person detection: a PersonTracker plus one
    V3FallDetectionState per tracked person, so each person's rolling window/alert
    smoothing is independent of every other person in frame."""

    def __init__(self):
        self.tracker = PersonTracker()
        self.person_states = {}  # track_id -> V3FallDetectionState
        # Used only by the bytetrack path: ByteTrack keeps its own identities, so this
        # side only has to remember where each id was last seen and for how long it has
        # been missing.
        self.missed = {}
        self.last_centroid = {}
        # People actually detected in the most recent frame, as opposed to tracks being held
        # through a dropout -- the number to report to a human.
        self.seen_count = 0


def detect_v3_fall_multi(frame, multi_state: V3MultiPersonFallState,
                          fall_detector: V3PoseFallDetector, config, camera=None, threshold=None):
    """Multi-person entry point. Returns a list of
    (track_id, detected, probability, label, hip_center) -- one entry per person
    currently tracked in this camera's frame (including ones not seen this exact
    frame but still within MAX_MISSED_FRAMES, matching single-person's tolerance for
    momentary tracking dropouts)."""
    threshold = threshold if threshold is not None else THRESHOLD

    if TRACKER == "bytetrack":
        # ByteTrack owns the identities, so there is no separate matching step to fail. It
        # reports only people it can see this frame; tracks it is holding through an
        # occlusion are stepped as "not seen" below, the same way the hip tracker's misses
        # are, so _step_person's hold/freeze behaviour is unchanged.
        seen_people = fall_detector.extract_tracked_keypoints(frame)
        seen_now = {tid: (kpts, hip) for tid, kpts, hip in seen_people}
        for tid, (_, hip) in seen_now.items():
            multi_state.last_centroid[tid] = hip
            multi_state.missed[tid] = 0
        for tid in list(multi_state.person_states):
            if tid not in seen_now:
                multi_state.missed[tid] = multi_state.missed.get(tid, 0) + 1
        tracked = [(tid, seen_now[tid][0], True) for tid in seen_now]
        tracked += [(tid, None, False) for tid in multi_state.person_states
                    if tid not in seen_now
                    and multi_state.missed.get(tid, 0) <= MAX_MISSED_FRAMES]
    else:
        detections = fall_detector.extract_all_keypoints(frame)
        tracked = multi_state.tracker.update(detections)

    multi_state.seen_count = sum(1 for _, _, seen in tracked if seen)

    results = []
    for track_id, kpts, seen in tracked:
        state = multi_state.person_states.setdefault(track_id, V3FallDetectionState())
        step_kpts = kpts if seen else np.zeros((NUM_KEYPOINTS, 3), dtype=np.float32)
        was_detected, collapse_before = state.last_detected, state.collapse_fired
        detected, probability, label = _step_person(step_kpts, seen, state, fall_detector, threshold)
        if (HELD_ALERT_MAX > 0 and detected and not seen and not was_detected
                and state.held_run > HELD_ALERT_MAX
                and not (state.collapse_fired and not collapse_before)):
            state.last_detected = False      # not started; it may start once the person is seen again
            detected, label = False, "held"
        if TRACKER == "bytetrack":
            centroid = multi_state.last_centroid.get(track_id, np.zeros(2, dtype=np.float32))
        else:
            centroid = multi_state.tracker.tracks[track_id]["centroid"]
        results.append((track_id, detected, probability, label, centroid))

    if TRACKER == "bytetrack":
        for track_id in list(multi_state.person_states):
            if multi_state.missed.get(track_id, 0) > MAX_MISSED_FRAMES:
                multi_state.person_states.pop(track_id, None)
                multi_state.missed.pop(track_id, None)
                multi_state.last_centroid.pop(track_id, None)
        return results

    # Drop state for any track the tracker has expired, so memory doesn't grow
    # unbounded over a long-running camera session.
    for track_id in list(multi_state.person_states):
        if track_id not in multi_state.tracker.tracks:
            del multi_state.person_states[track_id]

    return results
