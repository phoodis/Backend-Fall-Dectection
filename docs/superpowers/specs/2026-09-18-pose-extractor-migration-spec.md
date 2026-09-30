# Spec: Replace pose estimation backend (COCO-17, switchable, offline dataset prep)

Captured verbatim from user request + clarifications, 2026-09-18.

## Context

Flask + Celery + PostgreSQL elderly fall-detection system. Current pipeline:

```
frame -> YOLOv10x (person count)
      -> MediaPipe Pose (keypoints, sliced as landmark[:17])
      -> Farneback optical flow (236-dim)
      -> ResNet50 (RGB 2048-dim)
      -> concat 2420-dim -> DeepSVDD anomaly score -> threshold 0.285
```

## Known defect

MediaPipe returns 33 landmarks ordered as:
`0 nose | 1-6 eyes | 7-8 ears | 9-10 mouth | 11-12 shoulders | 13-14 elbows |
15-16 wrists | 17-22 hands | 23-24 HIPS | 25-26 KNEES | 27-28 ANKLES | 29-32 feet`

`app/detection/v2_fall_detection_onnx.py::extract_pose_v2` slices
`landmark[:17]`, yielding face (11 pts) + arms (6 pts) and **zero lower-body
joints**. The fall classifier has never seen legs.

COCO-17 (YOLO-pose output) order:
`0 nose | 1-2 eyes | 3-4 ears | 5-6 shoulders | 7-8 elbows | 9-10 wrists |
11-12 HIPS | 13-14 KNEES | 15-16 ANKLES` — same count, so downstream feature
dims stay identical.

**Codebase finding (confirmed by reading the file, not in the original
brief):** in the current inference path, `V2ONNXFallDetector.predict()` calls
`FeatureExtractorONNX.extract_pose_features(frames)`, which **ignores its
input and unconditionally returns `np.zeros(136)`**. The `pose_queue` built by
`extract_pose_v2` is computed but never consumed by the live classifier. So
today's `fall_v2` inference already runs on an all-zero pose vector,
independent of the landmark-slicing bug. This task's output (COCO-17,
normalized, smoothed keypoint sequences) is **not** wired into that live path
— it is offline dataset-prep for a future classifier-retraining work package.
This is consistent with the hard constraints below (classifier and
camera_manager are out of scope).

## Objective

Produce a pose extraction layer that outputs COCO-17 keypoints with
per-person track IDs, normalized and temporally smoothed, ready to feed a
(future, out-of-scope) classifier.

## Hard constraints

- Do NOT modify or retrain the classifier.
- Do NOT modify decision logic, alerting, or `camera_manager`.
- Do NOT delete the MediaPipe code path — must stay switchable for a later
  "with legs vs without legs" ablation study.
- Do NOT merge alone-detection into the pose pass yet.
- Time-box: if YOLO26 weights fail to load/export or break tracking, spend
  no more than half a day debugging, then switch to YOLO11-pose (API is
  near-identical; only the weight filename changes).

## Pipeline (execute in order)

1. **Benchmark candidate models** — yolo11s-pose, yolo11m-pose, yolo26s-pose,
   yolo26m-pose, same test video, CPU. Record fps, per-frame latency (ms),
   detection rate. Acceptance: a model hits >= 10 fps/camera on target CPU.
2. **GATE (blocking): lying-person detection.** For every fall clip in the
   test set: locate impact frame + following 2-3s, run pose inference, render
   skeleton overlays. Acceptance: keypoints detected in post-impact frames of
   >= 70% of fall clips. Remedies in order if it fails: conf 0.25->0.1, imgsz
   640->960, model size s->m. If all three fail: STOP, report, do not proceed
   to step 3.
3. **Switchable extraction layer** — abstract `PoseExtractor` base class with
   `MediaPipePoseExtractor` (wraps existing behaviour unchanged, including
   the slicing defect — needed for the ablation study) and `YoloPoseExtractor`
   (new, ByteTrack for track IDs). Select via `POSE_BACKEND=mediapipe|yolo`.
   Both return: `list of { track_id: int, keypoints: ndarray(17,3), bbox:
   [x1,y1,x2,y2] }`. MediaPipe has no tracking -> `track_id = 0`,
   single-person. Acceptance: switching the env var changes backend with no
   other code changes.
4. **Normalization, in this exact order:**
   1. Translation — origin = hip midpoint (mean of COCO indices 11, 12).
   2. Scale — divide by torso length = distance(hip midpoint, shoulder
      midpoint (mean of indices 5, 6)).
   3. Missing keypoints — where confidence < threshold, interpolate from
      neighbouring frames. **Never zero-fill** — after translation, (0,0) is
      the hip, so zero-filling asserts "ankle at hip", an anatomically
      impossible pose the model would learn as real.
   Acceptance: same person, same pose, near vs far from camera, yields
   near-identical normalized vectors.
5. **Temporal smoothing** — One Euro Filter per keypoint trajectory (adapts
   to velocity; a moving average would smear the fall itself).
6. **Extraction script** — folder of videos -> per-video `.npy` files,
   normalized + smoothed + track-separated keypoint sequences. Consumed by
   the next (out-of-scope) work package: classifier training.
7. **Evidence collection** — benchmark table, side-by-side MediaPipe[:17] vs
   YOLO-pose skeleton renders on identical frames, gate results.

## Definition of done

- [ ] Benchmark table exists; a model is selected with justification
- [ ] Lying-person gate passed and documented
- [ ] `POSE_BACKEND` switches cleanly in both directions
- [ ] Normalization passes the near/far camera test
- [ ] Extraction script produces `.npy` files
- [ ] Comparison images saved

## Clarifications obtained from user (2026-09-18)

**Test video source:** none exists in the repo (`videos/` doesn't even exist,
confirmed against `CONTEXT.md` §3.5). User will place `.mp4` fall clips into
`videos/` themselves before step 1/2 can run.

**Execution environment:** this session has no local Python interpreter and
no running Docker daemon (Docker Desktop is not started) on the Windows
working machine — nothing here can execute the pipeline. User will run
scripts on their own infrastructure. For the Step 1 benchmark specifically,
user gave explicit constraints, verbatim requirements:

- Do NOT use `docker compose exec` against the already-running
  backend/celery/db containers.
- Create either a fresh venv or a separate container under `~/apps/bench`.
- `pip install torch` must pin `--index-url https://download.pytorch.org/whl/cpu`.
- Limit to 2 CPU cores: `--cpus 2.0` (if containerized) or `taskset -c 0,1`
  (if venv on bare host).
- Print `df -h` both before and after dependency installation.
- Run 3 rounds per model.
- Deliver ONE single script the user runs top-to-bottom to get the complete
  benchmark table — not a sequence of separate commands.

Step 2 (gate) and step 6 (extraction script) also require an environment
with `ultralytics`, `mediapipe`, `opencv`, `numpy`, `torch` installed and a
GPU-less CPU target — same `~/apps/bench` environment is reused for those,
since they must import the same `pose_extraction/` package this plan
creates. (Note, 2026-09-30: this package was later relocated out of
`app/detection/pose/` to top-level `pose_extraction/` — see the Task 3
addendum below for why.)

## Addendum (2026-09-30): Step 1/2 results and confirmed production config

Step 1 and Step 2 were executed by the user on their own server, in a
session/environment this conversation has no visibility into — no
`benchmark_report.md`, `gate_report.md`, or `df -h` output was ever pasted
back here, and `tools/pose_pipeline/gate_lying_person.py` was never created
in this repo. The user has explicitly acknowledged this and confirmed they
want to proceed on the reported numbers without reproducing them in this
session. Recorded here for traceability, not verified by this session:

- Reported selection: **yolo11n-pose**, run at **imgsz=480** for production.
- Gate validated at imgsz=1280 (7/10 clips, 69.5% lower-body visibility).
  Production uses imgsz=480 because the clips requiring 1280 are
  out-of-domain social-media footage shot at long range; deployment
  cameras sit 2-4m from the subject. imgsz=1280 yields 1.15 fps,
  insufficient for even a single camera, so it was never a production
  candidate. Re-run the gate at 480 once real camera footage is available.
  (Correction, 2026-09-30: an earlier draft of this addendum described the
  480-vs-1280 gap as a risk the user was "accepting" — that mischaracterized
  it. 1280 was never a viable production config on fps grounds alone, gate
  result or not; the open item is validating 480 against real (not
  long-range social-media) camera footage, not weighing a speed/safety
  trade-off between two viable configs.)
- Reported hardware note: host CPU is virtualized (QEMU Virtual CPU 2.5+,
  no SIMD), ONNX Runtime measured ~6x slower than plain PyTorch there — so
  **no ONNX export** for this backend (also promoted to a hard constraint
  below).

## Addendum (2026-09-30): refined Step 3 requirements (STEP 3A-3E)

A follow-up task prompt refined steps 3-6 into named sub-steps and added
constraints not in the original spec above. These supersede/extend the
matching sections above and are what Tasks 3-9 in the plan now implement:

- `POSE_BACKEND` **defaults to `mediapipe`** (not left unset) so no existing
  caller's behavior changes.
- YOLO backend must not construct a model per frame — load once per
  extractor instance (contrast with `app/detection/bed_exit.py`, which
  constructs a new `ort.InferenceSession()` every frame; do not replicate
  that pattern).
- `YoloPoseExtractor` defaults: `model=yolo11n-pose.pt`, `imgsz=480`,
  `conf=0.25`, all overridable via constructor arguments (matches the
  confirmed production config above).
- When ByteTrack returns no ID for a detection, still return it with
  `track_id=-1` rather than dropping it (already true of the Task 5 design).
- **No ONNX export for this backend** — measured 6x slower on the target
  host (see addendum above).
- Do not install anything into the running `backend`/`celery_worker`/`db`
  containers — same `~/apps/bench` isolation as Step 1/2.
- Smoothing (One Euro Filter) must be toggle-able so the ablation study can
  compare smoothed vs. raw sequences — implemented as a CLI flag on the
  Step 6 extraction script (`--no-smoothing`), since smoothing operates on
  a whole trajectory/sequence, not a single `extract()` call, so it does
  not belong on `PoseExtractor` itself.
- The Step 6 extraction script must also emit a sidecar JSON per video:
  model name, imgsz, conf, whether smoothing was on, frame count, fps, and
  the track IDs present — without this, training runs in the next work
  package are not reproducible.
- Step 3E verification (side-by-side renders + `.npy` shape check) maps to
  existing Task 10 (`render_comparison.py`) and the Task 9 verification
  step — no new task needed.

## Addendum (2026-09-30): Finding — `app/detection/pose/` inherited the Flask app's import cost

STEP 3A was first built at `app/detection/pose/`. Real pytest run in the
user's local venv failed a chain of `ModuleNotFoundError` (flask, then
flask_sqlalchemy, ...) tracing back to `tests/pose/test_factory.py` →
`app.detection.pose.factory` → **`app/__init__.py`**. Confirmed by reading
`app/__init__.py` directly: it does top-level (not lazily inside
`create_app()`) `import flask`, `from flask_sqlalchemy import SQLAlchemy`,
`from celery import Celery`, and `import app.services.camera_manager` —
and `camera_manager.py` itself does `from app import celery`, `from app
import db`, plus the full detector/model import chain. Importing *any*
submodule under `app.*` unavoidably executes `app/__init__.py` first —
that's Python's package import model, not a bug isolated to one file — so
nesting `pose_extraction` under `app/` meant it could never be pure
computation regardless of how it was written internally.

**Fix:** relocated the whole package, `git mv app/detection/pose/* →
pose_extraction/` (top-level, sibling of `app/`). `app/__init__.py` was
never touched (zero risk to the live Flask app — satisfies the hard
constraint against modifying it). Added `pose_extraction/requirements.txt`
(numpy, opencv, mediapipe, ultralytics only) and
`tests/pose/test_no_flask_dependency.py`, which imports
`pose_extraction.factory` in a real subprocess and asserts `'flask' not in
sys.modules` and no `app`/`app.*` module got imported — meaningful even in
a venv that happens to have Flask installed, since it checks what actually
got imported, not what's merely available.

**Follow-up finding, same day:** `pose_extraction/factory.py` initially
imported both `MediaPipePoseExtractor` and `YoloPoseExtractor` at module
level, so selecting one backend still required both backends' dependencies
installed (mediapipe+cv2 AND ultralytics+torch) — the same class of
problem one level down. Fixed by moving each backend's import inside its
own `if backend == ...` branch in `get_pose_extractor()`. Verified for real
in the user's venv (which had neither mediapipe nor ultralytics installed):
`test_importing_factory_module_alone_imports_neither_backend` passes with
zero extra dependencies; the other factory tests fail with plain
`ModuleNotFoundError` for whichever library the test intentionally
exercises, not any Flask-related error.

Repo-wide grep after the move confirms no remaining `import
app.detection.pose` / `from app.detection.pose import ...` anywhere in
`app/`, `tools/`, or `tests/` — the only two textual hits left are prose
(this file and a docstring) explaining the history, not live imports.

## Addendum (2026-09-30): Finding — `requirements.txt` `mediapipe` line is unpinned; current PyPI mediapipe breaks the three legacy detectors

Verified directly (`Select-String`/grep, not inferred): `requirements.txt`
line 17 is bare `mediapipe`, no version constraint. All three legacy
detection modules use the legacy `solutions` API:

```
app/detection/fall_detection.py:4        import mediapipe as mp
app/detection/fall_detection.py:26       mp.solutions.pose.Pose(static_image_mode=False,
                                            min_detection_confidence=0.5, min_tracking_confidence=0.3)
app/detection/v2_fall_detection.py:11    import mediapipe as mp
app/detection/v2_fall_detection.py:30    self.pose_estimator = mp.solutions.pose.Pose(
app/detection/v2_fall_detection_onnx.py:9   import mediapipe as mp
app/detection/v2_fall_detection_onnx.py:28  self.pose_estimator = mp.solutions.pose.Pose(
```

Reported (by the user, from a real `docker compose build` attempt): current
PyPI `mediapipe` (0.10.35) dropped the legacy `solutions` namespace
(`dir(mp)` left with only `Image`, `ImageFormat`, `tasks`), so a fresh
`docker compose build --no-cache` today would fail to import all three
detectors at container start. The currently-running deployment is
unaffected only because it's on an image built before this drift — a
**rebuild, not the running system, is what's broken**. `mediapipe==0.10.14`
is the last version confirmed to still work with `mp.solutions.pose.Pose`.

**Fix (hotfix only, no detector code touched):** pin
`requirements.txt:17` to `mediapipe==0.10.14`. `app/detection/*.py` is
explicitly NOT modified — its current (buggy, legless) behavior must stay
reproducible as the ablation study's control arm; this pin is scoped to
keeping the existing system *buildable*, nothing else.

**Follow-up, same day:** `requirements.txt:19` (`ultralytics`, also
unpinned) was pinned too, to `ultralytics==8.4.165` — the exact version
used for the Step 1/2 benchmark and gate runs. Same reasoning as the
mediapipe pin: ultralytics changes its API often enough that an unpinned
rebuild months from now risks the identical class of silent breakage.
`pose_extraction/requirements.txt` was updated to match both pins, so the
bench venv and the main Docker image never drift apart on these two.

**Reported separately, unpinned-dependency audit of `requirements.txt`**
(report only, not fixed — now 17 of 22 lines carry no version constraint
at all, after the two pins above): `Flask`, `Flask-SQLAlchemy`,
`Flask-JWT-Extended`, `psycopg2-binary`, `mysql-connector-python`,
`celery`, `flower`, `redis`, `python-dotenv`, `requests`, `opencv-python`,
`Pillow`, `scikit-image`, `onnxruntime`, `Flask-CORS`, `pytz`, `tqdm`. One
line is range-constrained, not exact-pinned: `numpy<2.0.0`. Four lines are
exact-pinned: `torch==2.0.1`, `torchvision==0.15.2`, `mediapipe==0.10.14`,
`ultralytics==8.4.165`. Any of the
17 unpinned lines could reproduce this same class of failure (a build that
worked yesterday breaking today with no code change) — out of scope to fix
here beyond the two lines actually observed to be broken.

## Addendum (2026-09-30): Open question — hold vs. leave-NaN at sequence edges

Raised during STEP 3B review, deliberately left unresolved here — this is
an empirical question for W3 (classifier training), not something to
settle by reasoning in this spec.

`normalize_sequence`'s time-interpolation step must decide what to do when
a keypoint is unmeasured at the very start or end of a track's sequence
(no earlier/later measured frame on that side to interpolate between).
Two options, both implemented and selectable via `hold_edges`:

- `hold_edges=True` (current default): hold the nearest measured value
  constant past the edge — status `HELD`. Matches the general convention
  of "no information beyond the edge, assume it didn't change."
- `hold_edges=False`: leave those frames as `NaN` — status stays
  `MISSING`. The gap is explicit; nothing is asserted about what the pose
  was doing there.

**Why this specifically matters for fall detection, not just as a general
modeling nicety:** the Step 2 gate's own results showed pose detection
drops out most often exactly when the subject is lying flat on the floor —
for a clip window centered on a fall, that failure mode lands most often
at the END of the window, not scattered randomly through it. `HELD` makes
a post-impact detection dropout look identical to "the pose froze in a
held position," which is a real but different signal from "we stopped
seeing the subject." A classifier trained only on `HELD` sequences has no
way to distinguish "person is lying still" from "extractor lost the
person," and those two situations plausibly warrant different confidence
in a fall call.

**Resolution:** none yet. `pose_extraction/normalization.py` now returns a
per-(frame, keypoint) status mask (`MEASURED` / `INTERPOLATED` / `HELD` /
`MISSING`) alongside every normalized sequence specifically so W3 can:
(a) train separate variants with `hold_edges=True` vs `False` and compare,
and/or (b) use the mask itself as an auxiliary input or a window-filtering
rule (e.g. drop or downweight windows where `HELD` frames exceed some
fraction near the point of impact). Do not default this to a "final"
answer before that ablation runs.
