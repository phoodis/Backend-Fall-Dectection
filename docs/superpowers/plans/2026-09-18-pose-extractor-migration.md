# COCO-17 Pose Extractor Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> to implement this plan task-by-task (inline execution, per-task checkpoints
> with the user — this plan has two hard, spec-mandated blocking gates before
> Task 3 may start). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a switchable (`POSE_BACKEND=mediapipe|yolo`) COCO-17 pose
extraction layer with per-person tracking, correct normalization, and
temporal smoothing, plus an offline `.npy` extraction script — all without
touching the live classifier, alerting, or `camera_manager`.

**Architecture:** New, self-contained package `pose_extraction/` (an
abstract `PoseExtractor` base class with two implementations) that nothing
in the live request path imports yet. Two standalone CLI tools under
`tools/pose_pipeline/` run *before* that package exists at all, because the
spec makes model selection (Step 1) and a lying-person detection gate
(Step 2) hard blockers on building the abstraction (Step 3) — building it
early would be wasted work if the gate fails.

**Tech Stack:** ultralytics (YOLO11/YOLO26-pose + ByteTrack), mediapipe
(existing dependency, wrapped unchanged), OpenCV, numpy. All already in
`requirements.txt` — no dependency changes to the Docker image.

**Spec:** `docs/superpowers/specs/2026-09-18-pose-extractor-migration-spec.md`

## Global Constraints

- Never modify `app/detection/v2_fall_detection_onnx.py`,
  `app/services/camera_manager.py`, or anything under `app/detection/` that
  the live `fall_v2` request path imports. This plan only *adds* files.
- Never merge alone-detection into the pose pass.
- `MediaPipePoseExtractor` must reproduce the existing `landmark[:17]`
  slicing defect byte-for-byte (same missing joints) — it is the ablation
  study's control arm, not a bug to fix.
- `POSE_BACKEND` env var selects the backend; switching it must never require
  a code change (Step 3 acceptance test).
- Normalization order is fixed: translate (hip-midpoint origin) → scale
  (divide by torso length) → interpolate missing keypoints. Never
  zero-fill a missing keypoint at any stage — after translation, (0,0) is
  the hip, so a zero-fill asserts an anatomically impossible pose.
- Nothing in this plan runs inside the project's `docker-compose.yml`
  services, and never via `docker compose exec` against the running
  `backend`/`celery_worker`/`db` containers (explicit user instruction, so
  a benchmark measuring CPU performance isn't contending with, or
  contaminating, a live service). The user runs everything themselves,
  outside this session, in whichever isolated environment matches the task:
  Step 1/2 (benchmark, gate) ran in an isolated venv on a separate Linux
  box (`~/apps/bench` on an LXD container called `train4`). Task 3 onward
  is verified in a local Windows venv at `.venv/` in the repo root,
  activated with `.venv\Scripts\Activate.ps1` (PowerShell) — **not**
  `source .../bin/activate`, which is Linux-only syntax and does not apply
  here. Don't assume one or the other; ask if unclear which applies to a
  given verify step.
- `pose_extraction/` is a **top-level package, not nested under `app/`**
  precisely so it never triggers `app/__init__.py` — which does top-level
  `import flask`, `from flask_sqlalchemy import SQLAlchemy`,
  `from celery import Celery`, and `import app.services.camera_manager`
  (itself importing the DB models, detectors, and the rest of the Flask
  stack). Importing anything under `app.*` unavoidably executes
  `app/__init__.py` first — that's Python's package import model, not a
  bug in any one file — so the only real fix is keeping `pose_extraction/`
  structurally outside `app/`, not a lazy-import workaround inside it.
  `tests/pose/test_no_flask_dependency.py` guards against regressing this.
  Its own dependencies are minimal and explicit in
  `pose_extraction/requirements.txt` (numpy, opencv, mediapipe, ultralytics
  — no Flask/SQLAlchemy/Celery).
- Task 1 (Step 1 benchmark) and Task 2 (Step 2 gate) are **hard blockers**:
  do not start Task 3 until the user confirms Task 2's gate passed (directly,
  or after applying the three in-spec remedies). If all three remedies fail
  the gate, stop and report — do not write any file under `pose_extraction/`.
- Every task that touches `pose_extraction/` ships a pytest file under
  `tests/pose/`. Since nothing can run in this session, every task's
  "verify" step is a command block for the user to run in their bench venv
  and paste output back — not something to self-certify as passing.

---

## File structure

```
pose_extraction/            # top-level, NOT under app/ - see Global Constraints
  __init__.py
  base.py                  # PoseExtractor ABC, PosePerson dataclass
  mediapipe_extractor.py   # wraps existing MediaPipe path, defect intact
  yolo_extractor.py        # YOLO-pose + ByteTrack, COCO-17, per-track id
  factory.py                # POSE_BACKEND env var -> extractor instance
  normalization.py         # translate -> scale -> interpolate (in order)
  smoothing.py              # One Euro Filter
  requirements.txt          # numpy, opencv, mediapipe, ultralytics only

tools/pose_pipeline/
  benchmark_models.py       # Step 1: fps/latency/detection-rate, 4 models
  run_benchmark.sh          # Step 1: single entry point (venv+install+run)
  gate_lying_person.py      # Step 2: blocking gate, standalone (no app.* import)
  skeleton_draw.py          # shared by gate + comparison renders
  extract_dataset.py        # Step 6: folder of videos -> per-video .npy
  render_comparison.py      # Step 7: MediaPipe[:17] vs YOLO-pose side-by-side

tests/pose/
  __init__.py
  test_base.py
  test_mediapipe_extractor.py
  test_yolo_extractor.py
  test_factory.py
  test_no_flask_dependency.py   # guards the app/ separation, subprocess-based
  test_normalization.py
  test_smoothing.py
  test_extract_dataset.py
```

---

## Task 1: Step 1 — benchmark script (standalone, no dependency on Task 3+)

**Files:**
- Create: `tools/pose_pipeline/benchmark_models.py`
- Create: `tools/pose_pipeline/run_benchmark.sh`

**Interfaces:**
- Produces: a markdown table + JSON at
  `~/apps/bench/results/benchmark_report.{md,json}`, one row per model with
  `fps_mean`, `ms_per_frame_mean`, `detection_rate_mean`, and a `>=10fps?`
  column — this is what Task 2 reads to pick the gate-check model.

- [ ] **Step 1: Write `benchmark_models.py`**

```python
#!/usr/bin/env python3
"""Step 1 benchmark: yolo11s-pose / yolo11m-pose / yolo26s-pose / yolo26m-pose
on one CPU, same test video, 3 rounds each. See
docs/superpowers/specs/2026-09-18-pose-extractor-migration-spec.md for the
acceptance criterion (>= 10 fps/camera). A model that fails to load (e.g.
yolo26-pose weights don't exist yet) is recorded as LOAD_FAILED and the run
continues with the remaining models — never let one bad weight name kill
the whole benchmark.

Usage:
    python benchmark_models.py --video /path/to/test_fall.mp4 \
        --out results/benchmark_report.md --json-out results/benchmark_report.json
"""
import argparse
import json
import statistics
import time
import traceback
from pathlib import Path

import cv2

DEFAULT_MODELS = [
    "yolo11s-pose.pt",
    "yolo11m-pose.pt",
    "yolo26s-pose.pt",
    "yolo26m-pose.pt",
]


def _load_frames(video_path: str) -> list:
    cap = cv2.VideoCapture(video_path)
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    if not frames:
        raise RuntimeError(f"No frames read from {video_path}")
    return frames


def _run_one_round(model, frames: list, conf: float, imgsz: int) -> dict:
    detected = 0
    start = time.perf_counter()
    for frame in frames:
        results = model.predict(
            source=frame, conf=conf, imgsz=imgsz, device="cpu", verbose=False
        )
        if results and results[0].keypoints is not None and len(results[0].keypoints) > 0:
            detected += 1
    elapsed = time.perf_counter() - start

    n = len(frames)
    fps = n / elapsed if elapsed > 0 else 0.0
    return {
        "fps": fps,
        "ms_per_frame": (elapsed / n) * 1000.0 if n else 0.0,
        "detection_rate": detected / n if n else 0.0,
    }


def benchmark_model(weights: str, frames: list, conf: float, imgsz: int, runs: int) -> dict:
    from ultralytics import YOLO

    try:
        model = YOLO(weights)
    except Exception as exc:  # noqa: BLE001 - report and move on, don't crash the batch
        return {"weights": weights, "status": "LOAD_FAILED", "error": str(exc)}

    round_results = []
    for round_idx in range(runs):
        try:
            round_results.append(_run_one_round(model, frames, conf, imgsz))
        except Exception as exc:  # noqa: BLE001
            return {
                "weights": weights,
                "status": "INFERENCE_FAILED",
                "error": f"round {round_idx + 1}: {exc}",
            }

    fps_values = [r["fps"] for r in round_results]
    ms_values = [r["ms_per_frame"] for r in round_results]
    det_values = [r["detection_rate"] for r in round_results]

    return {
        "weights": weights,
        "status": "OK",
        "runs": round_results,
        "fps_mean": statistics.mean(fps_values),
        "fps_stdev": statistics.pstdev(fps_values) if len(fps_values) > 1 else 0.0,
        "ms_per_frame_mean": statistics.mean(ms_values),
        "detection_rate_mean": statistics.mean(det_values),
    }


def render_markdown_table(results: list) -> str:
    header = [
        "| model | status | fps (mean) | ms/frame (mean) | detection rate | >=10fps? | note |",
        "|---|---|---|---|---|---|---|",
    ]
    rows = []
    for r in results:
        if r["status"] != "OK":
            rows.append(
                f"| {r['weights']} | {r['status']} | - | - | - | - | {r.get('error', '')} |"
            )
            continue
        gate = "YES" if r["fps_mean"] >= 10.0 else "no"
        rows.append(
            f"| {r['weights']} | OK | {r['fps_mean']:.2f} | "
            f"{r['ms_per_frame_mean']:.1f} | {r['detection_rate_mean']*100:.1f}% | {gate} | |"
        )
    return "\n".join(header + rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out", default="results/benchmark_report.md")
    parser.add_argument("--json-out", default="results/benchmark_report.json")
    args = parser.parse_args()

    frames = _load_frames(args.video)
    print(f"Loaded {len(frames)} frames from {args.video}")

    results = []
    for weights in args.models:
        print(f"Benchmarking {weights} ({args.runs} rounds)...")
        try:
            result = benchmark_model(weights, frames, args.conf, args.imgsz, args.runs)
        except Exception:  # noqa: BLE001 - never let one model crash the whole run
            result = {
                "weights": weights,
                "status": "UNEXPECTED_ERROR",
                "error": traceback.format_exc(),
            }
        results.append(result)
        print(f"  -> {result['status']}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table = render_markdown_table(results)
    out_path.write_text(table + "\n", encoding="utf-8")

    json_path = Path(args.json_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("\n" + table)
    print(f"\nSaved: {out_path}  and  {json_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write `run_benchmark.sh`** — the single entry point the user
      runs; matches every constraint they gave verbatim (isolated venv under
      `~/apps/bench`, CPU-only torch wheel, `df -h` before/after install,
      2-core pin via `taskset`, one script, 3 rounds/model handled inside
      `benchmark_models.py`).

```bash
#!/usr/bin/env bash
# Step 1 benchmark runner - single entry point.
#   - never touches the running backend/celery/db containers
#   - isolated venv under ~/apps/bench (created if missing)
#   - torch pinned to the CPU wheel index (no CUDA download)
#   - pinned to 2 cores via taskset
#   - df -h before AND after dependency install
#   - 3 rounds per model, all in this one script
set -euo pipefail

VIDEO_PATH="${1:?Usage: run_benchmark.sh /path/to/test_fall.mp4 [bench_dir]}"
BENCH_DIR="${2:-$HOME/apps/bench}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== disk space BEFORE install ==="
df -h

mkdir -p "$BENCH_DIR"
if [ ! -d "$BENCH_DIR/venv" ]; then
    python3 -m venv "$BENCH_DIR/venv"
fi
# shellcheck disable=SC1091
source "$BENCH_DIR/venv/bin/activate"

pip install --upgrade pip
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
# mediapipe + pytest installed now too: Step 2 (gate) and the test suite
# reuse this same venv, so we only pay the install cost once.
pip install ultralytics opencv-python-headless mediapipe pytest "numpy<2.0.0"

echo "=== disk space AFTER install ==="
df -h

mkdir -p "$BENCH_DIR/results"
cp "$SCRIPT_DIR/benchmark_models.py" "$BENCH_DIR/benchmark_models.py"

echo "=== running benchmark (2 cores pinned via taskset -c 0,1) ==="
taskset -c 0,1 python "$BENCH_DIR/benchmark_models.py" \
    --video "$VIDEO_PATH" \
    --runs 3 \
    --out "$BENCH_DIR/results/benchmark_report.md" \
    --json-out "$BENCH_DIR/results/benchmark_report.json"

echo ""
echo "Report written to: $BENCH_DIR/results/benchmark_report.md"
```

- [ ] **Step 3: User runs it, pastes output back**

```bash
chmod +x tools/pose_pipeline/run_benchmark.sh
./tools/pose_pipeline/run_benchmark.sh /path/to/your/test_fall.mp4
```

Paste back the printed markdown table (and the two `df -h` blocks). Expected
row shape once it succeeds:

```
| model | status | fps (mean) | ms/frame (mean) | detection rate | >=10fps? | note |
|---|---|---|---|---|---|---|
| yolo11s-pose.pt | OK | 14.20 | 70.4 | 98.0% | YES | |
```

**CHECKPOINT 1 (report back, wait for confirmation):** which model(s) hit
`>= 10 fps`, and which one to carry into Task 2 as the gate-check candidate
(fastest one that clears the bar, unless the user wants a different
size/accuracy trade-off). Do not start Task 2 until this is confirmed.

---

## Task 2: Step 2 — lying-person detection GATE (blocking, standalone)

**Files:**
- Create: `tools/pose_pipeline/skeleton_draw.py`
- Create: `tools/pose_pipeline/gate_lying_person.py`

**Interfaces:**
- `skeleton_draw.draw_skeleton(frame, keypoints, edges, conf_threshold=0.3) -> np.ndarray`
- `skeleton_draw.COCO17_EDGES`, `skeleton_draw.MEDIAPIPE_SLICE17_EDGES` — two
  edge sets, because the two backends' 17 points mean different things
  (COCO order vs. the raw `landmark[:17]` slice); reused by Task 10.
- Produces: `results/gate/gate_report.md` (pass/fail + per-clip detection
  rate) and `results/gate/<clip-name>/frame_*.jpg` skeleton renders — this
  is the Definition-of-Done evidence for "Lying-person gate passed and
  documented", and doubles as half of Task 10's evidence.

- [ ] **Step 1: Write `skeleton_draw.py`**

```python
"""Skeleton rendering shared by the Step 2 gate and the Step 7 comparison
script. Two edge sets because the two backends' 17 points are NOT the same
17 joints - see the known defect in the spec.
"""
import cv2

# COCO-17 order: 0 nose,1-2 eyes,3-4 ears,5-6 shoulders,7-8 elbows,
# 9-10 wrists,11-12 hips,13-14 knees,15-16 ankles
COCO17_EDGES = [
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12),
    (11, 13), (13, 15), (12, 14), (14, 16),
    (0, 5), (0, 6),
]

# MediaPipe landmark[:17] raw slice: 0 nose,1-6 eyes,7-8 ears,9-10 mouth,
# 11-12 shoulders,13-14 elbows,15-16 wrists. No hips/knees/ankles exist in
# this slice at all - there is nothing below the wrists to draw.
MEDIAPIPE_SLICE17_EDGES = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (0, 11), (0, 12),
]


def draw_skeleton(frame, keypoints, edges, conf_threshold: float = 0.3):
    out = frame.copy()
    for x, y, c in keypoints:
        if c >= conf_threshold:
            cv2.circle(out, (int(x), int(y)), 4, (0, 255, 0), -1)
    for a, b in edges:
        xa, ya, ca = keypoints[a]
        xb, yb, cb = keypoints[b]
        if ca >= conf_threshold and cb >= conf_threshold:
            cv2.line(out, (int(xa), int(ya)), (int(xb), int(yb)), (0, 200, 255), 2)
    return out
```

- [ ] **Step 2: Write `gate_lying_person.py`** — deliberately does NOT
      import `pose_extraction.*` (that package doesn't exist yet and
      won't until this gate passes). Talks to `ultralytics.YOLO` and
      `mediapipe` directly, same as `benchmark_models.py`.

```python
#!/usr/bin/env python3
"""Step 2 GATE (blocking): for every fall clip, run pose inference on the
impact frame + the following N seconds, render skeleton overlays, and check
whether keypoints were detected in >= 70% of clips post-impact.

Impact times are NOT auto-detected - only a human who watched the clips
knows where impact happens. Supply them via --manifest, a CSV with columns
`filename,impact_seconds`.

If the gate fails, retry in this exact order (spec-mandated), each a flag
change, no code change:
    1. --conf 0.1            (was 0.25)
    2. --imgsz 960            (was 640)
    3. --weights yolo11m-pose.pt   (step up model size)
If all three fail: STOP. Do not build pose_extraction/.

Usage:
    python gate_lying_person.py --clips-dir videos/fall_clips \
        --manifest videos/fall_clips/impact_times.csv \
        --backend yolo --weights yolo11s-pose.pt \
        --out-dir results/gate
"""
import argparse
import csv
import sys
from pathlib import Path

import cv2

from skeleton_draw import COCO17_EDGES, MEDIAPIPE_SLICE17_EDGES, draw_skeleton


def load_manifest(path: str) -> dict:
    manifest = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            manifest[row["filename"]] = float(row["impact_seconds"])
    return manifest


class _MediaPipeAdapter:
    """Turns raw mediapipe output into the same (17,3) shape as YOLO-pose,
    keeping the known landmark[:17] slicing defect intact.
    """

    def __init__(self):
        import mediapipe as mp

        self._pose = mp.solutions.pose.Pose(
            static_image_mode=False, model_complexity=1,
            enable_segmentation=False, min_detection_confidence=0.5,
        )

    def infer(self, frame):
        import numpy as np

        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._pose.process(rgb)
        if not results.pose_landmarks:
            return []
        landmarks = results.pose_landmarks.landmark[:17]
        keypoints = np.array(
            [[lm.x * w, lm.y * h, lm.visibility] for lm in landmarks], dtype="float32"
        )
        return [keypoints]


class _YoloAdapter:
    def __init__(self, weights: str, conf: float, imgsz: int):
        from ultralytics import YOLO

        self._model = YOLO(weights)
        self._conf = conf
        self._imgsz = imgsz

    def infer(self, frame):
        import numpy as np

        results = self._model.track(
            source=[frame], stream=False, tracker="bytetrack.yaml",
            conf=self._conf, imgsz=self._imgsz, device="cpu",
            persist=True, verbose=False,
        )
        if not results or results[0].keypoints is None:
            return []
        result = results[0]
        xy = result.keypoints.xy.cpu().numpy()
        conf = result.keypoints.conf
        conf = conf.cpu().numpy() if conf is not None else np.ones(xy.shape[:2], dtype="float32")
        return [
            np.concatenate([xy[i], conf[i][:, None]], axis=1).astype("float32")
            for i in range(xy.shape[0])
        ]


def build_adapter(backend: str, weights: str, conf: float, imgsz: int):
    if backend == "mediapipe":
        return _MediaPipeAdapter(), MEDIAPIPE_SLICE17_EDGES
    if backend == "yolo":
        return _YoloAdapter(weights, conf, imgsz), COCO17_EDGES
    raise ValueError(f"Unknown backend: {backend}")


def evaluate_clip(video_path: Path, impact_seconds: float, adapter, edges,
                   out_dir: Path, post_impact_seconds: float) -> dict:
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    start_frame = int(impact_seconds * fps)
    end_frame = int((impact_seconds + post_impact_seconds) * fps)

    clip_out_dir = out_dir / video_path.stem
    clip_out_dir.mkdir(parents=True, exist_ok=True)

    frame_idx = 0
    frames_checked = 0
    frames_with_detection = 0

    while True:
        ok, frame = cap.read()
        if not ok or frame_idx > end_frame:
            break
        if frame_idx >= start_frame:
            people = adapter.infer(frame)
            frames_checked += 1
            if people:
                frames_with_detection += 1
                rendered = draw_skeleton(frame, people[0], edges)
                cv2.imwrite(str(clip_out_dir / f"frame_{frame_idx:05d}.jpg"), rendered)
            else:
                cv2.imwrite(str(clip_out_dir / f"frame_{frame_idx:05d}_NODETECT.jpg"), frame)
        frame_idx += 1
    cap.release()

    detection_rate = frames_with_detection / frames_checked if frames_checked else 0.0
    return {
        "clip": video_path.name,
        "frames_checked": frames_checked,
        "frames_with_detection": frames_with_detection,
        "detection_rate": detection_rate,
        "passed": frames_with_detection > 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clips-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--backend", choices=["mediapipe", "yolo"], default="yolo")
    parser.add_argument("--weights", default="yolo11s-pose.pt")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--out-dir", default="results/gate")
    parser.add_argument("--post-impact-seconds", type=float, default=3.0)
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    adapter, edges = build_adapter(args.backend, args.weights, args.conf, args.imgsz)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    clip_results = []
    for filename, impact_seconds in manifest.items():
        video_path = Path(args.clips_dir) / filename
        if not video_path.exists():
            clip_results.append({"clip": filename, "error": "file not found", "passed": False})
            continue
        clip_results.append(
            evaluate_clip(video_path, impact_seconds, adapter, edges, out_dir,
                          args.post_impact_seconds)
        )

    total = len(clip_results)
    passed = sum(1 for r in clip_results if r.get("passed"))
    gate_rate = passed / total if total else 0.0
    gate_passed = gate_rate >= 0.70

    report_lines = [
        f"# Step 2 gate report - backend={args.backend}, weights={args.weights}, "
        f"conf={args.conf}, imgsz={args.imgsz}",
        "",
        f"Clips evaluated: {total}",
        f"Clips with >=1 detected post-impact frame: {passed}",
        f"Gate rate: {gate_rate*100:.1f}% (threshold: 70%)",
        f"GATE: {'PASS' if gate_passed else 'FAIL'}",
        "",
        "| clip | frames checked | frames detected | detection rate | passed |",
        "|---|---|---|---|---|",
    ]
    for r in clip_results:
        if "error" in r:
            report_lines.append(f"| {r['clip']} | - | - | - | ERROR: {r['error']} |")
            continue
        report_lines.append(
            f"| {r['clip']} | {r['frames_checked']} | {r['frames_with_detection']} | "
            f"{r['detection_rate']*100:.1f}% | {'yes' if r['passed'] else 'no'} |"
        )

    report_path = out_dir / "gate_report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print("\n".join(report_lines))
    print(f"\nSaved: {report_path}")
    print(f"Skeleton renders under: {out_dir}/<clip-name>/")

    sys.exit(0 if gate_passed else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: User runs it, pastes output back**

First, the user writes `videos/fall_clips/impact_times.csv` (they are the
only one who knows where impact happens in each clip):

```csv
filename,impact_seconds
fall_01.mp4,4.2
fall_02.mp4,6.8
```

Then, reusing the venv Task 1 already built:

```bash
source ~/apps/bench/venv/bin/activate
cd /path/to/repo/root   # contains app/, tools/
cd tools/pose_pipeline
taskset -c 0,1 python gate_lying_person.py \
    --clips-dir /path/to/videos/fall_clips \
    --manifest /path/to/videos/fall_clips/impact_times.csv \
    --backend yolo --weights <model from checkpoint 1> \
    --out-dir /path/to/results/gate
```

Paste back `gate_report.md`'s content, plus a couple of the rendered
`frame_*.jpg` files (or just describe what they show) so we can eyeball
whether the skeleton actually lands on the fallen person.

**CHECKPOINT 2 (BLOCKING, report back, wait for confirmation):**
- If gate rate `>= 70%`: confirm PASS, then Task 3 may start.
- If `< 70%`: apply remedies **in this order**, one at a time, re-running
  the same command with only the flag changed — do not skip ahead:
  1. `--conf 0.1`
  2. `--imgsz 960`
  3. `--weights yolo11m-pose.pt` (or the next size up from checkpoint 1's pick)
  If a remedy gets the gate to `>= 70%`, stop there and report which one
  worked. **If all three fail, STOP entirely** — report the failure and do
  not proceed to Task 3; a classifier trained on data where pose is absent
  at the moment of impact is worthless (spec, verbatim).

---

## Task 3: `PoseExtractor` abstract base + `PosePerson`

*(Do not start this task until Task 2's checkpoint is confirmed PASS.)*

**Files:**
- Create: `pose_extraction/__init__.py`
- Create: `pose_extraction/base.py`
- Test: `tests/pose/__init__.py`
- Test: `tests/pose/test_base.py`

**Interfaces:**
- Produces: `PosePerson(track_id: int, keypoints: np.ndarray[17,3], bbox: list[float,4])`,
  `PoseExtractor.extract(frame: np.ndarray) -> list[PosePerson]` (abstract),
  `PoseExtractor.reset() -> None` (default no-op) — every later task depends
  on these exact names and shapes.

- [ ] **Step 1: Write `pose_extraction/__init__.py`** (empty package marker)

```python
```

- [ ] **Step 2: Write `pose_extraction/base.py`**

```python
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
```

- [ ] **Step 3: Write `tests/pose/test_base.py`**

```python
import numpy as np
import pytest

from pose_extraction.base import PoseExtractor, PosePerson


def test_pose_extractor_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        PoseExtractor()


def test_pose_person_holds_expected_shapes():
    keypoints = np.zeros((17, 3), dtype=np.float32)
    person = PosePerson(track_id=3, keypoints=keypoints, bbox=[0, 0, 10, 10])
    assert person.track_id == 3
    assert person.keypoints.shape == (17, 3)
    assert person.bbox == [0, 0, 10, 10]
```

- [ ] **Step 4: User verifies**

```bash
source ~/apps/bench/venv/bin/activate
cd /path/to/repo/root
PYTHONPATH=. pytest tests/pose/test_base.py -v
```

Paste back the output. Expected: `2 passed`.

---

## Task 4: `MediaPipePoseExtractor` (wraps existing behaviour, defect intact)

**Files:**
- Create: `pose_extraction/mediapipe_extractor.py`
- Test: `tests/pose/test_mediapipe_extractor.py`

**Interfaces:**
- Consumes: `PoseExtractor`, `PosePerson` from `pose_extraction.base`.
- Produces: `MediaPipePoseExtractor()`, `.extract(frame) -> list[PosePerson]`
  always `track_id=0` (single-person, no tracking) or `[]`.

- [ ] **Step 1: Write `pose_extraction/mediapipe_extractor.py`**

```python
import cv2
import mediapipe as mp
import numpy as np

from .base import PoseExtractor, PosePerson


class MediaPipePoseExtractor(PoseExtractor):
    """Wraps the existing MediaPipe pose path unchanged, INCLUDING the
    landmark[:17] slicing defect (face + arms, no legs - see spec). Kept
    for the 'with legs vs without legs' ablation study. Do not fix the
    slicing here; that is the whole point of keeping this class around.
    """

    def __init__(self, min_detection_confidence: float = 0.5, model_complexity: int = 1):
        self._pose = mp.solutions.pose.Pose(
            static_image_mode=False,
            model_complexity=model_complexity,
            enable_segmentation=False,
            min_detection_confidence=min_detection_confidence,
        )

    def extract(self, frame: np.ndarray) -> list:
        h, w = frame.shape[:2]
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._pose.process(frame_rgb)

        if not results.pose_landmarks:
            return []

        landmarks = results.pose_landmarks.landmark[:17]
        keypoints = np.zeros((17, 3), dtype=np.float32)
        xs, ys = [], []
        for i, lm in enumerate(landmarks):
            px, py = lm.x * w, lm.y * h
            keypoints[i] = (px, py, lm.visibility)
            xs.append(px)
            ys.append(py)

        bbox = [min(xs), min(ys), max(xs), max(ys)]
        return [PosePerson(track_id=0, keypoints=keypoints, bbox=bbox)]
```

- [ ] **Step 2: Write `tests/pose/test_mediapipe_extractor.py`**

```python
import numpy as np

from pose_extraction.mediapipe_extractor import MediaPipePoseExtractor


class _FakeLandmark:
    def __init__(self, x, y, visibility):
        self.x, self.y, self.visibility = x, y, visibility


class _FakeLandmarks:
    def __init__(self, points):
        self.landmark = points


class _FakeResults:
    def __init__(self, points):
        self.pose_landmarks = _FakeLandmarks(points) if points else None


def test_extract_returns_single_person_track_id_zero(monkeypatch):
    points = [_FakeLandmark(0.5, 0.5, 0.9) for _ in range(33)]
    extractor = MediaPipePoseExtractor()
    monkeypatch.setattr(extractor._pose, "process", lambda frame_rgb: _FakeResults(points))

    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    people = extractor.extract(frame)

    assert len(people) == 1
    assert people[0].track_id == 0
    assert people[0].keypoints.shape == (17, 3)


def test_extract_returns_empty_list_when_no_person_detected(monkeypatch):
    extractor = MediaPipePoseExtractor()
    monkeypatch.setattr(extractor._pose, "process", lambda frame_rgb: _FakeResults(None))

    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    assert extractor.extract(frame) == []


def test_keeps_the_known_slicing_defect_no_remap_to_coco(monkeypatch):
    # Real MediaPipe hip landmarks live at raw indices 23/24, well past the
    # [:17] slice this extractor intentionally preserves. Confirm keypoint
    # 16 in the output equals raw landmark 16 (a wrist), not a remapped
    # ankle - proving no COCO remap happened.
    points = [_FakeLandmark(i / 33.0, i / 33.0, 1.0) for i in range(33)]
    extractor = MediaPipePoseExtractor()
    monkeypatch.setattr(extractor._pose, "process", lambda frame_rgb: _FakeResults(points))

    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    people = extractor.extract(frame)

    expected_x = points[16].x * frame.shape[1]
    assert abs(people[0].keypoints[16, 0] - expected_x) < 1e-3
```

- [ ] **Step 3: User verifies**

```bash
PYTHONPATH=. pytest tests/pose/test_mediapipe_extractor.py -v
```

Paste back output. Expected: `3 passed`.

---

## Task 5: `YoloPoseExtractor` (COCO-17, ByteTrack)

**Files:**
- Create: `pose_extraction/yolo_extractor.py`
- Test: `tests/pose/test_yolo_extractor.py`

**Interfaces:**
- Consumes: `PoseExtractor`, `PosePerson`.
- Produces: `YoloPoseExtractor(weights_path, conf=0.25, imgsz=480, device="cpu")`,
  `.extract(frame) -> list[PosePerson]` with real `track_id` values from
  ByteTrack (or `-1` if untracked).

- [ ] **Step 1: Write `pose_extraction/yolo_extractor.py`**

```python
import numpy as np
from ultralytics import YOLO

from .base import PoseExtractor, PosePerson


class YoloPoseExtractor(PoseExtractor):
    """COCO-17 pose extraction via an Ultralytics YOLO-pose model, tracked
    with ByteTrack so falls can be attributed to a stable per-person id.
    """

    def __init__(self, weights_path: str = "yolo11n-pose.pt", conf: float = 0.25,
                 imgsz: int = 480, device: str = "cpu"):
        self._model = YOLO(weights_path)
        self._conf = conf
        self._imgsz = imgsz
        self._device = device

    def extract(self, frame: np.ndarray) -> list:
        results = self._model.track(
            source=[frame],
            stream=False,
            tracker="bytetrack.yaml",
            conf=self._conf,
            imgsz=self._imgsz,
            device=self._device,
            persist=True,
            verbose=False,
        )

        people = []
        if not results:
            return people

        result = results[0]
        if result.keypoints is None or result.boxes is None:
            return people

        kpts_xy = result.keypoints.xy.cpu().numpy()
        kpts_conf = result.keypoints.conf
        kpts_conf = (
            kpts_conf.cpu().numpy() if kpts_conf is not None
            else np.ones(kpts_xy.shape[:2], dtype=np.float32)
        )
        boxes_xyxy = result.boxes.xyxy.cpu().numpy()
        ids = result.boxes.id
        ids = ids.cpu().numpy() if ids is not None else None

        for i in range(kpts_xy.shape[0]):
            keypoints = np.concatenate(
                [kpts_xy[i], kpts_conf[i][:, None]], axis=1
            ).astype(np.float32)
            track_id = int(ids[i]) if ids is not None else -1
            bbox = boxes_xyxy[i].tolist()
            people.append(PosePerson(track_id=track_id, keypoints=keypoints, bbox=bbox))

        return people

    def reset(self) -> None:
        # ByteTrack state lives on the model's predictor; drop it so a new
        # video/camera doesn't inherit stale track IDs from a previous one.
        if hasattr(self._model, "predictor") and self._model.predictor is not None:
            self._model.predictor.trackers = None
```

- [ ] **Step 2: Write `tests/pose/test_yolo_extractor.py`**

```python
import numpy as np

from pose_extraction.yolo_extractor import YoloPoseExtractor


class _Tensor:
    """Minimal stand-in for a torch.Tensor - only .cpu().numpy() is used."""

    def __init__(self, array):
        self._array = np.asarray(array)

    def cpu(self):
        return self

    def numpy(self):
        return self._array


class _FakeKeypoints:
    def __init__(self, xy, conf):
        self.xy = _Tensor(xy)
        self.conf = _Tensor(conf)


class _FakeBoxes:
    def __init__(self, xyxy, ids):
        self.xyxy = _Tensor(xyxy)
        self.id = _Tensor(ids) if ids is not None else None


class _FakeResult:
    def __init__(self, keypoints, boxes):
        self.keypoints = keypoints
        self.boxes = boxes


def _make_extractor_without_loading_weights():
    extractor = YoloPoseExtractor.__new__(YoloPoseExtractor)  # skip YOLO(weights) load
    extractor._conf = 0.25
    extractor._imgsz = 640
    extractor._device = "cpu"
    return extractor


def test_extract_maps_two_tracked_people():
    xy = np.zeros((2, 17, 2), dtype=np.float32)
    conf = np.ones((2, 17), dtype=np.float32)
    xyxy = np.array([[0, 0, 10, 10], [20, 20, 30, 30]], dtype=np.float32)
    ids = np.array([7, 9], dtype=np.float32)
    fake_result = _FakeResult(_FakeKeypoints(xy, conf), _FakeBoxes(xyxy, ids))

    extractor = _make_extractor_without_loading_weights()
    extractor._model = type("M", (), {"track": lambda self, **kw: [fake_result]})()

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    people = extractor.extract(frame)

    assert [p.track_id for p in people] == [7, 9]
    assert all(p.keypoints.shape == (17, 3) for p in people)
    assert people[1].bbox == [20.0, 20.0, 30.0, 30.0]


def test_extract_keeps_untracked_detections_with_track_id_minus_one():
    xy = np.zeros((1, 17, 2), dtype=np.float32)
    conf = np.ones((1, 17), dtype=np.float32)
    xyxy = np.array([[0, 0, 10, 10]], dtype=np.float32)
    fake_result = _FakeResult(_FakeKeypoints(xy, conf), _FakeBoxes(xyxy, ids=None))

    extractor = _make_extractor_without_loading_weights()
    extractor._model = type("M", (), {"track": lambda self, **kw: [fake_result]})()

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    people = extractor.extract(frame)

    assert len(people) == 1
    assert people[0].track_id == -1


def test_extract_returns_empty_when_no_boxes():
    fake_result = _FakeResult(None, None)
    extractor = _make_extractor_without_loading_weights()
    extractor._model = type("M", (), {"track": lambda self, **kw: [fake_result]})()

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    assert extractor.extract(frame) == []


def test_model_is_loaded_once_per_instance_not_per_frame(monkeypatch):
    # Contrast with app/detection/bed_exit.py, which constructs a new
    # ort.InferenceSession() every frame - YoloPoseExtractor must not
    # replicate that pattern (STEP 3A hard constraint).
    load_count = {"n": 0}

    class _FakeYOLO:
        def __init__(self, weights_path):
            load_count["n"] += 1

        def track(self, **kw):
            return [_FakeResult(None, None)]

    monkeypatch.setattr("pose_extraction.yolo_extractor.YOLO", _FakeYOLO)

    from pose_extraction.yolo_extractor import YoloPoseExtractor
    extractor = YoloPoseExtractor(weights_path="yolo11n-pose.pt")

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    extractor.extract(frame)
    extractor.extract(frame)
    extractor.extract(frame)

    assert load_count["n"] == 1
```

- [ ] **Step 3: User verifies**

```bash
PYTHONPATH=. pytest tests/pose/test_yolo_extractor.py -v
```

Paste back output. Expected: `4 passed`. (No network access or model
download needed - the fake `YOLO` classes never touch the real ultralytics
weight loader.)

---

## Task 6: `factory.py` — `POSE_BACKEND` switch

**Files:**
- Create: `pose_extraction/factory.py`
- Test: `tests/pose/test_factory.py`

**Interfaces:**
- Consumes: `MediaPipePoseExtractor`, `YoloPoseExtractor`.
- Produces: `get_pose_extractor() -> PoseExtractor`, reads `POSE_BACKEND`
  (`"mediapipe"` default, or `"yolo"`) and `POSE_YOLO_WEIGHTS` env vars.

- [ ] **Step 1: Write `pose_extraction/factory.py`** — imports of each
      backend module are LOCAL to their branch, not at module top. This
      isn't a style choice: `mediapipe_extractor.py` imports `cv2` and
      `mediapipe` at its own top level, `yolo_extractor.py` imports
      `ultralytics` at its own top level, so a module-level `from
      .mediapipe_extractor import ...` in `factory.py` would force BOTH
      backends' dependencies to be installed no matter which one is
      selected (caught by real testing, see Task 6 verify step below —
      first shipped version got this wrong).

```python
import os

from .base import PoseExtractor

_YOLO_WEIGHTS_ENV = "POSE_YOLO_WEIGHTS"
_YOLO_CONF_ENV = "POSE_YOLO_CONF"
_YOLO_IMGSZ_ENV = "POSE_YOLO_IMGSZ"

# Confirmed production selection (see spec addendum, 2026-09-30): yolo11n-pose.pt
# at imgsz=480. imgsz=1280 (where the gate was validated) was never a viable
# production config on fps grounds alone (1.15 fps) - re-run the gate at 480
# against real camera footage once available; not a risk trade-off between two
# otherwise-viable configs.
_DEFAULT_YOLO_WEIGHTS = "yolo11n-pose.pt"
_DEFAULT_YOLO_CONF = 0.25
_DEFAULT_YOLO_IMGSZ = 480


def get_pose_extractor() -> PoseExtractor:
    # Defaults to mediapipe so nothing changes for any existing caller
    # until POSE_BACKEND is explicitly set (STEP 3A hard constraint).
    backend = os.environ.get("POSE_BACKEND", "mediapipe").strip().lower()

    if backend == "mediapipe":
        # Imported here, not at module level: POSE_BACKEND=yolo must be
        # usable without mediapipe/cv2 installed at all.
        from .mediapipe_extractor import MediaPipePoseExtractor
        return MediaPipePoseExtractor()

    if backend == "yolo":
        # Imported here, not at module level: POSE_BACKEND=mediapipe must be
        # usable without ultralytics/torch installed at all.
        from .yolo_extractor import YoloPoseExtractor
        weights = os.environ.get(_YOLO_WEIGHTS_ENV, _DEFAULT_YOLO_WEIGHTS)
        conf = float(os.environ.get(_YOLO_CONF_ENV, _DEFAULT_YOLO_CONF))
        imgsz = int(os.environ.get(_YOLO_IMGSZ_ENV, _DEFAULT_YOLO_IMGSZ))
        return YoloPoseExtractor(weights_path=weights, conf=conf, imgsz=imgsz)

    raise ValueError(f"Unknown POSE_BACKEND={backend!r}; expected 'mediapipe' or 'yolo'")
```

- [ ] **Step 2: Write `tests/pose/test_factory.py`** — note the imports of
      `MediaPipePoseExtractor`/`YoloPoseExtractor` moved from module-level
      into the individual test functions that need them, for the same
      reason as above: importing the test *file* must not force both
      backends' dependencies to be present just to collect it.

```python
import subprocess
import sys
from pathlib import Path

import pytest

from pose_extraction.factory import get_pose_extractor


def test_defaults_to_mediapipe(monkeypatch):
    from pose_extraction.mediapipe_extractor import MediaPipePoseExtractor

    monkeypatch.delenv("POSE_BACKEND", raising=False)
    extractor = get_pose_extractor()
    assert isinstance(extractor, MediaPipePoseExtractor)


def test_switches_to_yolo_via_env_var(monkeypatch):
    from pose_extraction.yolo_extractor import YoloPoseExtractor

    class _FakeYOLO:
        def __init__(self, weights_path):
            self.weights_path = weights_path

    monkeypatch.setattr("pose_extraction.yolo_extractor.YOLO", _FakeYOLO)
    monkeypatch.setenv("POSE_BACKEND", "yolo")
    monkeypatch.setenv("POSE_YOLO_WEIGHTS", "yolo11n-pose.pt")

    extractor = get_pose_extractor()
    assert isinstance(extractor, YoloPoseExtractor)


def test_yolo_backend_uses_confirmed_production_defaults(monkeypatch):
    captured = {}

    class _FakeYOLO:
        def __init__(self, weights_path):
            captured["weights_path"] = weights_path

    monkeypatch.setattr("pose_extraction.yolo_extractor.YOLO", _FakeYOLO)
    monkeypatch.setenv("POSE_BACKEND", "yolo")
    monkeypatch.delenv("POSE_YOLO_WEIGHTS", raising=False)
    monkeypatch.delenv("POSE_YOLO_CONF", raising=False)
    monkeypatch.delenv("POSE_YOLO_IMGSZ", raising=False)

    extractor = get_pose_extractor()

    assert captured["weights_path"] == "yolo11n-pose.pt"
    assert extractor._conf == 0.25
    assert extractor._imgsz == 480


def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("POSE_BACKEND", "not-a-backend")
    with pytest.raises(ValueError):
        get_pose_extractor()


# --- lazy-import guarantees (each backend must not require the other's deps) ---

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_importing_factory_module_alone_imports_neither_backend():
    # Needs neither mediapipe/cv2 nor ultralytics/torch installed to run -
    # this is the cheapest possible proof that factory.py's top-level
    # imports stayed lazy. Subprocess so it reflects a fresh import graph.
    script = (
        "import sys\n"
        "import pose_extraction.factory\n"
        "print('pose_extraction.mediapipe_extractor' in sys.modules)\n"
        "print('pose_extraction.yolo_extractor' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd=str(_repo_root()), timeout=30,
    )
    assert result.returncode == 0, f"import failed:\n{result.stdout}\n{result.stderr}"
    assert result.stdout.strip().splitlines() == ["False", "False"], (
        f"importing pose_extraction.factory alone pulled in a backend module:\n{result.stdout}"
    )


def test_mediapipe_backend_does_not_import_yolo_extractor_module(monkeypatch):
    # Needs mediapipe/cv2 installed (we're exercising the real mediapipe
    # path) but must NOT need ultralytics/torch.
    sys.modules.pop("pose_extraction.yolo_extractor", None)
    monkeypatch.setenv("POSE_BACKEND", "mediapipe")

    get_pose_extractor()

    assert "pose_extraction.yolo_extractor" not in sys.modules


def test_yolo_backend_does_not_import_mediapipe_extractor_module(monkeypatch):
    # Needs ultralytics installed (we're exercising the real yolo path, with
    # YOLO() itself faked out) but must NOT need mediapipe/cv2.
    sys.modules.pop("pose_extraction.mediapipe_extractor", None)

    class _FakeYOLO:
        def __init__(self, weights_path):
            pass

    monkeypatch.setattr("pose_extraction.yolo_extractor.YOLO", _FakeYOLO)
    monkeypatch.setenv("POSE_BACKEND", "yolo")

    get_pose_extractor()

    assert "pose_extraction.mediapipe_extractor" not in sys.modules
```

- [ ] **Step 3: User verifies (this is Step 3's acceptance test — env var switches backend, zero code changes)**

Runs with NO extra dependencies installed at all:
```bash
PYTHONPATH=. pytest tests/pose/test_factory.py::test_unknown_backend_raises tests/pose/test_factory.py::test_importing_factory_module_alone_imports_neither_backend -v
```
Expected: `2 passed` — this alone proves the lazy-import fix, no installs needed.

Then, to prove each backend truly doesn't need the other's dependencies,
install and test ONE side at a time (order matters — don't install both
before testing, or you can't tell the fix apart from "everything's
installed anyway"):
```bash
pip install mediapipe opencv-python-headless "numpy<2.0.0"
PYTHONPATH=. pytest tests/pose/test_factory.py::test_defaults_to_mediapipe tests/pose/test_factory.py::test_mediapipe_backend_does_not_import_yolo_extractor_module -v

pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install ultralytics
PYTHONPATH=. pytest tests/pose/test_factory.py -v
POSE_BACKEND=mediapipe PYTHONPATH=. python -c \
  "from pose_extraction.factory import get_pose_extractor; print(type(get_pose_extractor()))"
POSE_BACKEND=yolo POSE_YOLO_WEIGHTS=yolo11n-pose.pt PYTHONPATH=. python -c \
  "from pose_extraction.factory import get_pose_extractor; print(type(get_pose_extractor()))"
```

Paste back all output. Expected, once both are installed: `7 passed`, then
`MediaPipePoseExtractor`, then `YoloPoseExtractor` (the last command also
triggers a one-time weight download - expected and fine).

---

## Task 7: `normalization.py` — translate → scale → interpolate

**Files:**
- Create: `pose_extraction/normalization.py`
- Test: `tests/pose/test_normalization.py`

**Interfaces:**
- Produces: `translate_and_scale_frame(keypoints: ndarray(17,3), conf_threshold=0.3) -> ndarray(17,3)`
  (NaN where un-normalizable), `interpolate_missing(sequence: ndarray(T,17,3)) -> ndarray(T,17,3)`,
  `normalize_sequence(keypoints_sequence: ndarray(T,17,3), conf_threshold=0.3) -> ndarray(T,17,3)`
  (the one Task 9 calls).

**STEP 3B superseded this task's original draft, twice** (first a follow-up
task prompt on 2026-09-30 adding explicit acceptance tests and requiring
each missing-data case documented; then a same-day review round that
changed the function signatures again — see below). What actually
shipped — full source in `pose_extraction/normalization.py`, full tests in
`tests/pose/test_normalization.py`, both already run for real in this
session (`pytest tests/pose/test_normalization.py -v` → **16 passed**):

- Same three function *names* as originally planned
  (`translate_and_scale_frame`, `interpolate_missing`, `normalize_sequence`),
  same fixed order (translate → scale → interpolate), same never-zero-fill
  rule — but **all three now return a tuple**, not a bare array:
  `translate_and_scale_frame(keypoints, conf_threshold=0.3) -> (frame, measured)`,
  `interpolate_missing(sequence, measured, hold_edges=True) -> (filled, status)`,
  `normalize_sequence(seq, conf_threshold=0.3, hold_edges=True) -> (normalized, status)`.
  `status` is a `(T,17)` int8 array of `MEASURED`/`INTERPOLATED`/`HELD`/`MISSING`
  (module-level constants). This is a breaking signature change from the
  original Task 7 draft below — Task 9's `extract_dataset.py` (not yet
  written) must call it as a tuple-unpack, not a bare array.
- Degenerate torso length: explicitly marked unmeasured (whole frame → NaN)
  rather than divided by a clamped minimum — "a fabricated scale is worse
  than a missing frame" (spec, verbatim). `MIN_TORSO_LENGTH = 1e-3` is a
  float-safety epsilon, not a soft floor.
- Missing-anchor case (hip and/or shoulder midpoint unavailable):
  invalidates the WHOLE frame, not just the anchor keypoint — a person's
  wrist position is meaningless without a hip to measure it from. Recovered
  later by time-interpolation like any other missing value, if the anchor
  is available on other frames in the sequence.
- **`hold_edges` flag (added after review, default `True` for continuity):**
  start/end-of-sequence gaps can now be held constant (`HELD`, the original
  behavior) or left as `NaN`/`MISSING` (`hold_edges=False`). Added because
  the Step 2 gate showed pose detection drops out most often exactly when
  the subject is lying flat — for a fall-centered window, that's usually
  the END of the window, so `HELD` risks asserting "the pose froze" when
  the truth is "we lost the subject." **Deliberately left as an open
  question, not resolved here** — see the spec's "Open question — hold vs.
  leave-NaN at sequence edges" addendum; W3 must ablate both before
  training on either as a fixed choice.
- Missing-for-the-ENTIRE-sequence case: left as NaN, status `MISSING`
  throughout — nothing to interpolate from, never zero-filled, caller must
  check the status mask and drop/mask that track/keypoint.
- Test suite covers all 5 of STEP 3B's named acceptance tests: near/far
  invariance (exact, not just "near-identical"), translation invariance
  (exact), no-zero-fill (checked directly: no non-anchor keypoint ever
  lands on exactly (0,0) even with scattered random gaps), degenerate
  input (both exactly-zero and just-below-epsilon torso length), and
  missing anchors (single-frame recovery via interpolation, and
  whole-sequence NaN persistence).

Superseded content below this line kept only for the original function
signatures/interfaces — the file actually shipped is the authoritative
version; don't copy code from here.

```python
"""Order matters: translate -> scale -> interpolate missing (spec-mandated).

Interpolating LAST, in normalized space, means we never write 0.0 for a
missing keypoint - after translation (0,0) IS the hip, so a zero-fill would
assert "ankle at the hip", an anatomically impossible pose the model would
learn as real.
"""
import numpy as np

HIP_L, HIP_R = 11, 12
SHOULDER_L, SHOULDER_R = 5, 6
CONF_THRESHOLD_DEFAULT = 0.3
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
    NaN in x/y where the frame can't be normalized (hip and/or shoulder
    midpoint missing) or where an individual keypoint's own confidence is
    below threshold. The confidence channel passes through unchanged.
    """
    out = np.full_like(keypoints, np.nan, dtype=np.float32)
    out[:, 2] = keypoints[:, 2]

    hip = _hip_midpoint(keypoints, conf_threshold)
    shoulder = _shoulder_midpoint(keypoints, conf_threshold)
    if hip is None or shoulder is None:
        return out

    torso_length = float(np.linalg.norm(shoulder - hip))
    if torso_length < MIN_TORSO_LENGTH:
        return out

    scaled = (keypoints[:, :2] - hip) / torso_length
    low_conf = keypoints[:, 2] < conf_threshold
    scaled[low_conf] = np.nan
    out[:, :2] = scaled
    return out


def interpolate_missing(sequence: np.ndarray) -> np.ndarray:
    """(T,17,3) normalized sequence, NaN where missing -> same shape with
    every NaN linearly interpolated across time per (keypoint, coordinate).
    Leading/trailing NaN runs are held at the nearest valid frame (never
    0.0 - see module docstring). A (keypoint, coord) column that is NaN for
    every frame is left as-is; the caller must drop that track.
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
    translated + scaled + interpolated.
    """
    normalized = np.stack([
        translate_and_scale_frame(keypoints_sequence[t], conf_threshold)
        for t in range(keypoints_sequence.shape[0])
    ])
    return interpolate_missing(normalized)
```

- [ ] **Step 2: Write `tests/pose/test_normalization.py`** — includes the
      spec's Step 4 acceptance test (near vs. far camera).

```python
import numpy as np

from pose_extraction.normalization import interpolate_missing, normalize_sequence, \
    translate_and_scale_frame


def _make_pose(scale: float, offset=(0.0, 0.0)):
    # A simple standing COCO-17 figure in local units, before scale/offset.
    base = np.array([
        [0, -3], [-0.2, -3.2], [0.2, -3.2], [-0.4, -3.0], [0.4, -3.0],
        [-1, -2], [1, -2], [-1.2, -1], [1.2, -1], [-1.3, 0], [1.3, 0],
        [-0.7, 0], [0.7, 0], [-0.7, 2], [0.7, 2], [-0.7, 4], [0.7, 4],
    ], dtype=np.float32)
    pixels = base * scale + np.array(offset, dtype=np.float32)
    conf = np.ones((17, 1), dtype=np.float32)
    return np.concatenate([pixels, conf], axis=1)


def test_translate_sets_hip_midpoint_to_origin():
    pose = _make_pose(scale=50.0, offset=(400.0, 300.0))
    normalized = translate_and_scale_frame(pose)
    hip_mid = (normalized[11, :2] + normalized[12, :2]) / 2.0
    assert np.allclose(hip_mid, [0.0, 0.0], atol=1e-4)


def test_near_and_far_camera_yield_near_identical_normalized_pose():
    near = _make_pose(scale=120.0, offset=(300.0, 200.0))   # close to camera, big
    far = _make_pose(scale=30.0, offset=(600.0, 400.0))     # far from camera, small

    normalized_near = translate_and_scale_frame(near)
    normalized_far = translate_and_scale_frame(far)

    assert np.allclose(normalized_near[:, :2], normalized_far[:, :2], atol=1e-3)


def test_missing_hip_or_shoulder_produces_nan_not_zero():
    pose = _make_pose(scale=50.0)
    pose[HIP_L_INDEX := 11, 2] = 0.0  # zero out hip confidence

    normalized = translate_and_scale_frame(pose)

    assert np.isnan(normalized[:, :2]).all()  # whole frame un-normalizable
    assert not np.array_equal(normalized[:, :2], np.zeros((17, 2)))  # never silently zero


def test_missing_keypoint_is_interpolated_not_zero_filled():
    sequence = np.stack([_make_pose(scale=50.0) for _ in range(5)])
    sequence[2, 15, 2] = 0.0  # left ankle: zero confidence on frame 2 only

    normalized = normalize_sequence(sequence)
    ankle_across_time = normalized[:, 15, :2]

    assert not np.allclose(ankle_across_time[2], [0.0, 0.0], atol=1e-2)
    assert np.allclose(
        ankle_across_time[2], (ankle_across_time[1] + ankle_across_time[3]) / 2, atol=1e-2
    )


def test_interpolate_missing_holds_leading_nan_at_first_valid_value():
    sequence = np.zeros((4, 1, 3), dtype=np.float32)
    sequence[0, 0, 0] = np.nan
    sequence[1:, 0, 0] = 5.0

    result = interpolate_missing(sequence)
    assert result[0, 0, 0] == 5.0
```

(`HIP_L_INDEX := 11` is a self-documenting inline walrus so the magic
number `11` in the test reads as "hip left index" without importing the
module's private constant.)

- [x] **Step 3: Verified** — already run for real in this session, twice
  (before and after the review round that added `hold_edges` + the status
  mask): `pytest tests/pose/test_normalization.py -v` → **16 passed**
  (latest). No action needed; kept as a record. (If re-running after any
  future edit to `normalization.py`, same command, same expected count.)

---

## Task 8: `smoothing.py` — One Euro Filter

**Files:**
- Create: `pose_extraction/smoothing.py`
- Test: `tests/pose/test_smoothing.py`

**Interfaces:**
- Produces: `OneEuroFilter(min_cutoff=1.0, beta=0.007, d_cutoff=1.0)` with
  `.filter(x: float, t: float) -> float`; `smooth_sequence(sequence: ndarray(T,17,3), fps: float, min_cutoff=1.0, beta=0.007) -> ndarray(T,17,3)`
  (the one Task 9 calls, after `normalize_sequence`).

- [ ] **Step 1: Write `pose_extraction/smoothing.py`**

```python
"""One Euro Filter (Casiez, Roussel, Vogel 2012), applied per keypoint
coordinate trajectory. Chosen over a moving average because it adapts to
velocity: stable when the subject is still, responsive when the subject
moves fast - a moving average would smear the fall itself and make it look
slower than it actually was.
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
    independently per keypoint. Confidence channel passes through. NaN
    values (should already be interpolated away by this point) are left
    untouched rather than crashing.
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
```

- [ ] **Step 2: Write `tests/pose/test_smoothing.py`**

```python
import numpy as np

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
```

- [ ] **Step 3: User verifies**

```bash
PYTHONPATH=. pytest tests/pose/test_smoothing.py -v
```

Paste back output. Expected: `3 passed`.

---

## Task 9: `extract_dataset.py` — Step 6 extraction script

**Files:**
- Create: `tools/pose_pipeline/extract_dataset.py`
- Test: `tests/pose/test_extract_dataset.py`

**Interfaces:**
- Consumes: `PosePerson` (`pose_extraction.base`), `get_pose_extractor`
  (`pose_extraction.factory`), `normalize_sequence`
  (`pose_extraction.normalization`), `smooth_sequence`
  (`pose_extraction.smoothing`).
- Produces: `collect_track_sequences(frames_people: list[list[PosePerson]]) -> dict[int, np.ndarray]`
  (pure, tested directly); CLI `extract_dataset.py INPUT_DIR OUTPUT_DIR` ->
  one `.npy` per video, each a pickled `dict[int track_id, ndarray(T,17,3)]`.

- [ ] **Step 1: Write `tools/pose_pipeline/extract_dataset.py`**

```python
#!/usr/bin/env python3
"""Step 6: folder of videos -> per-video .npy files of normalized,
track-separated COCO-17 keypoint sequences (smoothed by default, see
--no-smoothing). Consumed by the (out-of-scope) classifier-retraining work
package.

Output .npy shape/dtype (per video, via np.save(..., allow_pickle=True)):
    dict[int track_id, np.ndarray]
    each array: shape (T, 17, 3), dtype float32, axis -1 = (x, y, confidence)
    x/y are normalized (hip-midpoint origin, torso-length scale - see
    pose_extraction.normalization), NOT pixel coordinates.

Sidecar JSON per video (<stem>.json next to <stem>.npy), for reproducing a
training run later:
    {
      "video": "<filename>", "backend": "yolo"|"mediapipe",
      "model": "<weights path or 'mediapipe'>", "imgsz": int|null,
      "conf": float|null, "smoothing": bool, "fps": float,
      "frame_count": int, "track_ids": [int, ...]
    }

Backend is selected the same way as everywhere else: POSE_BACKEND=yolo|mediapipe.

Usage:
    POSE_BACKEND=yolo POSE_YOLO_WEIGHTS=yolo11n-pose.pt \
        python extract_dataset.py /path/to/videos /path/to/output
    # ablation study: compare against raw (unsmoothed) sequences
    python extract_dataset.py /path/to/videos /path/to/output_raw --no-smoothing
"""
import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from pose_extraction.factory import get_pose_extractor
from pose_extraction.normalization import normalize_sequence
from pose_extraction.smoothing import smooth_sequence

UNOBSERVED_CONFIDENCE = -1.0  # sentinel for "track not detected this frame"


def collect_track_sequences(frames_people: list) -> dict:
    """Pure aggregation step, no I/O: given one list of PosePerson per
    frame, return {track_id: ndarray(T,17,3)} raw pixel-space sequences,
    one row per frame across the track's full [first_seen, last_seen] span.
    Frames within that span where the track wasn't detected are filled with
    confidence=UNOBSERVED_CONFIDENCE (never silently zero-confidence - the
    normalization step treats this as "missing" and interpolates it, same
    as a genuinely low-confidence keypoint).
    """
    per_track_frames = defaultdict(list)
    for frame_idx, people in enumerate(frames_people):
        for person in people:
            per_track_frames[person.track_id].append((frame_idx, person.keypoints))

    sequences = {}
    for track_id, frames in per_track_frames.items():
        if len(frames) < 2:
            continue
        first_idx = frames[0][0]
        last_idx = frames[-1][0]
        length = last_idx - first_idx + 1

        raw = np.zeros((length, 17, 3), dtype=np.float32)
        raw[:, :, 2] = UNOBSERVED_CONFIDENCE
        for idx, keypoints in frames:
            raw[idx - first_idx] = keypoints

        sequences[track_id] = raw

    return sequences


def extract_video(video_path: Path, extractor, apply_smoothing: bool,
                   fps: float = None) -> tuple:
    cap = cv2.VideoCapture(str(video_path))
    if fps is None:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    frames_people = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames_people.append(extractor.extract(frame))
    cap.release()

    raw_sequences = collect_track_sequences(frames_people)

    def _process(raw):
        normalized = normalize_sequence(raw)
        return smooth_sequence(normalized, fps=fps) if apply_smoothing else normalized

    sequences = {track_id: _process(raw) for track_id, raw in raw_sequences.items()}
    return sequences, fps, len(frames_people)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir")
    parser.add_argument("output_dir")
    parser.add_argument("--pattern", default="*.mp4")
    parser.add_argument("--no-smoothing", action="store_true",
                         help="write raw (unsmoothed) normalized sequences, for the "
                              "ablation study comparing smoothed vs raw")
    args = parser.parse_args()

    apply_smoothing = not args.no_smoothing
    backend = os.environ.get("POSE_BACKEND", "mediapipe").strip().lower()
    weights = os.environ.get("POSE_YOLO_WEIGHTS", "yolo11n-pose.pt") if backend == "yolo" else None
    conf = float(os.environ.get("POSE_YOLO_CONF", "0.25")) if backend == "yolo" else None
    imgsz = int(os.environ.get("POSE_YOLO_IMGSZ", "480")) if backend == "yolo" else None

    extractor = get_pose_extractor()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for video_path in sorted(Path(args.input_dir).glob(args.pattern)):
        extractor.reset()
        sequences, fps, frame_count = extract_video(video_path, extractor, apply_smoothing)

        out_path = output_dir / f"{video_path.stem}.npy"
        np.save(out_path, sequences, allow_pickle=True)

        sidecar = {
            "video": video_path.name,
            "backend": backend,
            "model": weights if backend == "yolo" else "mediapipe",
            "imgsz": imgsz,
            "conf": conf,
            "smoothing": apply_smoothing,
            "fps": fps,
            "frame_count": frame_count,
            "track_ids": sorted(sequences.keys()),
        }
        sidecar_path = output_dir / f"{video_path.stem}.json"
        sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

        print(f"{video_path.name}: {len(sequences)} track(s) -> {out_path} (+ {sidecar_path.name})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write `tests/pose/test_extract_dataset.py`** — tests the
      pure aggregation function only; no real video or model needed.

```python
import numpy as np

from pose_extraction.base import PosePerson
from tools.pose_pipeline.extract_dataset import collect_track_sequences


def _person(track_id: int) -> PosePerson:
    return PosePerson(track_id=track_id, keypoints=np.ones((17, 3), dtype=np.float32),
                       bbox=[0, 0, 1, 1])


def test_collects_one_track_spanning_full_clip():
    frames_people = [[_person(0)], [_person(0)], [_person(0)]]
    sequences = collect_track_sequences(frames_people)

    assert set(sequences.keys()) == {0}
    assert sequences[0].shape == (3, 17, 3)


def test_separates_two_simultaneous_tracks():
    frames_people = [[_person(1), _person(2)], [_person(1), _person(2)]]
    sequences = collect_track_sequences(frames_people)

    assert set(sequences.keys()) == {1, 2}
    assert all(seq.shape == (2, 17, 3) for seq in sequences.values())


def test_gap_frame_is_marked_unobserved_not_zero_confidence():
    # track 0 seen on frame 0 and frame 2, missing on frame 1 (occlusion)
    frames_people = [[_person(0)], [], [_person(0)]]
    sequences = collect_track_sequences(frames_people)

    assert sequences[0].shape == (3, 17, 3)
    assert sequences[0][1, 0, 2] == -1.0  # UNOBSERVED_CONFIDENCE, not 0.0


def test_single_frame_track_is_dropped():
    frames_people = [[_person(5)]]
    sequences = collect_track_sequences(frames_people)
    assert sequences == {}
```

- [ ] **Step 3: Add `tools/pose_pipeline/__init__.py`** (empty, so the test
      import `from tools.pose_pipeline.extract_dataset import ...` resolves)

```python
```

- [ ] **Step 4: User verifies**

```bash
PYTHONPATH=. pytest tests/pose/test_extract_dataset.py -v
```

Paste back output. Expected: `4 passed`. Then, once real fall clips exist
under `videos/`:

```bash
mkdir -p results/dataset
POSE_BACKEND=yolo POSE_YOLO_WEIGHTS=<model from checkpoint 1> \
    PYTHONPATH=. python tools/pose_pipeline/extract_dataset.py \
    videos/fall_clips results/dataset
```

Paste back the per-video `N track(s) -> ...` lines — this satisfies
"Extraction script produces .npy files" in the Definition of Done.

---

## Task 10: `render_comparison.py` — Step 7 evidence

**Files:**
- Create: `tools/pose_pipeline/render_comparison.py`

**Interfaces:**
- Consumes: `MediaPipePoseExtractor`, `YoloPoseExtractor`,
  `skeleton_draw.draw_skeleton`, `skeleton_draw.COCO17_EDGES`,
  `skeleton_draw.MEDIAPIPE_SLICE17_EDGES`.
- Produces: `results/comparison/frame_XXXXX_compare.jpg`, one MediaPipe[:17]
  render and one YOLO-pose render side by side on identical frames.

- [ ] **Step 1: Write `tools/pose_pipeline/render_comparison.py`**

```python
#!/usr/bin/env python3
"""Step 7 evidence: side-by-side MediaPipe[:17] vs YOLO-pose skeleton
renders on identical frames - visibly shows the missing lower body in the
MediaPipe path (the known defect in the spec).

Usage:
    python render_comparison.py --video videos/fall_clips/sample.mp4 \
        --frame-indices 10 45 90 --weights yolo11s-pose.pt \
        --out-dir results/comparison
"""
import argparse
from pathlib import Path

import cv2
import numpy as np

from pose_extraction.mediapipe_extractor import MediaPipePoseExtractor
from pose_extraction.yolo_extractor import YoloPoseExtractor
from skeleton_draw import COCO17_EDGES, MEDIAPIPE_SLICE17_EDGES, draw_skeleton


def get_frame(video_path: str, frame_index: int):
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"Could not read frame {frame_index} from {video_path}")
    return frame


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--frame-indices", type=int, nargs="+", required=True)
    parser.add_argument("--weights", default="yolo11s-pose.pt")
    parser.add_argument("--out-dir", default="results/comparison")
    args = parser.parse_args()

    mp_extractor = MediaPipePoseExtractor()
    yolo_extractor = YoloPoseExtractor(weights_path=args.weights)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for frame_index in args.frame_indices:
        frame = get_frame(args.video, frame_index)

        mp_people = mp_extractor.extract(frame)
        yolo_people = yolo_extractor.extract(frame)

        mp_render = (
            draw_skeleton(frame, mp_people[0].keypoints, MEDIAPIPE_SLICE17_EDGES)
            if mp_people else frame.copy()
        )
        yolo_render = (
            draw_skeleton(frame, yolo_people[0].keypoints, COCO17_EDGES)
            if yolo_people else frame.copy()
        )

        cv2.putText(mp_render, "MediaPipe[:17] (no legs)", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.putText(yolo_render, "YOLO-pose COCO-17", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        side_by_side = np.hstack([mp_render, yolo_render])
        out_path = out_dir / f"frame_{frame_index:05d}_compare.jpg"
        cv2.imwrite(str(out_path), side_by_side)
        print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: User runs it, reports back**

```bash
cd tools/pose_pipeline
PYTHONPATH=/path/to/repo/root python render_comparison.py \
    --video /path/to/videos/fall_clips/fall_01.mp4 \
    --frame-indices 10 60 120 \
    --weights <model from checkpoint 1> \
    --out-dir /path/to/results/comparison
```

Paste back the list of saved files (and, ideally, describe or attach one
image) so we can confirm the MediaPipe side visibly stops at the waist
while the YOLO side shows hips/knees/ankles.

---

## Task 11: Evidence index + Definition-of-Done checklist

**Files:**
- Create: `results/README.md` (evidence index — not committed code, just a
  pointer file the user keeps alongside `results/`, which is git-ignored
  scratch output, not part of the repo's tracked source)

**Interfaces:** none — this is a summary file, not code.

- [ ] **Step 1: Write `results/README.md`** summarizing, once Tasks 1-10 are
      all confirmed:

```markdown
# Pose extractor migration — evidence

- Benchmark table (Step 1): results/benchmark_report.md
- Selected model: <fill in from checkpoint 1>
- Gate report (Step 2): results/gate/gate_report.md — PASS at <rate>%
- Extracted dataset (Step 6): results/dataset/*.npy
- Comparison renders (Step 7): results/comparison/*.jpg

## Definition of done
- [x] Benchmark table exists; a model is selected with justification
- [x] Lying-person gate passed and documented
- [x] POSE_BACKEND switches cleanly in both directions (tests/pose/test_factory.py)
- [x] Normalization passes the near/far camera test (tests/pose/test_normalization.py)
- [x] Extraction script produces .npy files
- [x] Comparison images saved
```

- [ ] **Step 2: Final report to user** — everything above, plus the
      explicit reminder that `pose_extraction/*` is not wired into
      `camera_manager` or `v2_fall_detection_onnx.py` (out of scope, per
      spec) and that the live `fall_v2` classifier still runs on the
      hardcoded all-zero pose vector documented in the spec's Codebase
      Finding — that is a separate, future work package.

---

## Self-review notes (already applied above)

- **Spec coverage:** Step 1 -> Task 1, Step 2 (gate) -> Task 2, Step 3
  (switchable layer) -> Tasks 3-6, Step 4 (normalization) -> Task 7, Step 5
  (smoothing) -> Task 8, Step 6 (extraction script) -> Task 9, Step 7
  (evidence) -> Tasks 2/10/11, Definition of Done -> Task 11. All hard
  constraints are restated in Global Constraints and re-checked per task
  (MediaPipe defect preserved: Task 4; classifier/camera_manager untouched:
  no task writes to those files; POSE_BACKEND switch: Task 6).
- **Placeholder scan:** no task contains "TBD"/"handle appropriately"/etc.;
  every step has runnable code or an exact command.
- **Type consistency:** `PosePerson.keypoints` is `ndarray(17,3)` everywhere
  it's produced (Tasks 4, 5) and consumed (Tasks 9, 10); `normalize_sequence`
  and `smooth_sequence` both take/return `ndarray(T,17,3)` consistently
  between Task 7, Task 8, and Task 9's `extract_video`.
