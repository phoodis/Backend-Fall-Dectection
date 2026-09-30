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
since they must import the same `app/detection/pose/` package this plan
creates.

## Addendum (2026-09-30): Step 1/2 results and confirmed production config

Step 1 and Step 2 were executed by the user on their own server, in a
session/environment this conversation has no visibility into — no
`benchmark_report.md`, `gate_report.md`, or `df -h` output was ever pasted
back here, and `tools/pose_pipeline/gate_lying_person.py` was never created
in this repo. The user has explicitly acknowledged this and confirmed they
want to proceed on the reported numbers without reproducing them in this
session. Recorded here for traceability, not verified by this session:

- Reported selection: **yolo11n-pose**, run at **imgsz=480** for production.
- Reported gate result: passed conditionally (7/10 clips, 70%) but only at
  **imgsz=1280** — a materially different config than the imgsz=480 chosen
  for production. Reported cause of lower-imgsz failures: subjects too
  small in the test clips, not a model-capability limit; real cameras are
  claimed to sit 2-4m away.
- **Flagged risk, explicitly accepted by the user:** the production config
  (imgsz=480) is not the config the gate validated (imgsz=1280). If real
  camera framing looks more like the low-imgsz failure clips than the
  claimed 2-4m distance, lower-body detection at the moment of impact may
  fall below the 70% bar in production. Decided to proceed anyway; revisit
  if real-camera gate numbers come in low once Task 2's gate script is
  actually run against production-representative footage.
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
