#!/usr/bin/env python3
"""Step 1 benchmark: yolo11s-pose / yolo11m-pose / yolo26s-pose / yolo26m-pose
on one CPU, same test video, 3 rounds each. See
docs/superpowers/specs/2026-09-18-pose-extractor-migration-spec.md for the
acceptance criterion (>= 10 fps/camera). A model that fails to load (e.g.
yolo26-pose weights don't exist yet) is recorded as LOAD_FAILED and the run
continues with the remaining models - never let one bad weight name kill
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
