#!/usr/bin/env python3
"""STEP 3D: folder of videos -> per-video .npy files of normalized,
smoothed (by default), track-separated COCO-17 keypoint sequences, plus a
matching .status.npy validity mask and a .json sidecar. Consumed by the
(out-of-scope) classifier-retraining work package (W3).

Runs STANDALONE - this file and everything it imports (pose_extraction.*)
never imports Flask, Celery, a database, or the app/ package. Real
dependencies: numpy, opencv-python-headless, and whichever ONE backend is
selected (ultralytics for --backend yolo, mediapipe for --backend
mediapipe) - pose_extraction.factory imports each backend lazily, so a
yolo-only run never needs mediapipe installed and vice versa. Verified by
tests/pose/test_extract_dataset.py::test_script_runs_without_flask_or_app.

Do NOT install opencv-python (non-headless) anywhere in this environment -
train4 has no libGL.so.1 and it will crash there. A fresh
`pip install ultralytics` has pulled in opencv-python transitively before
(twice) - if it happens again, fix with, in this exact order:
    pip install ultralytics==<pinned version>
    pip install --force-reinstall opencv-python-headless

Output contract, per video (files share the same <stem>):
    <stem>.npy          dict[int track_id, np.ndarray]
                         each array: shape (T, 17, 3), dtype float32,
                         axis -1 = (x, y, confidence). x/y are normalized
                         (hip-midpoint origin, torso-length scale - see
                         pose_extraction.normalization), NOT pixel coords.
                         Smoothed unless --no-smoothing.
    <stem>.status.npy   dict[int track_id, np.ndarray]
                         each array: shape (T, 17), dtype int8, values are
                         pose_extraction.normalization.{MEASURED,
                         INTERPOLATED, HELD, MISSING}. Same track_id keys
                         and same T as the matching array in <stem>.npy.
                         NOT optional - W3 needs it to decide whether to
                         discard windows with too many HELD frames (the
                         open hold_edges question recorded in the spec).
    <stem>.json          sidecar metadata - see _build_sidecar() for the
                         exact schema (model+version, imgsz, conf,
                         tracker, smoothing on/off + params, hold_edges,
                         source video path/resolution/fps/frame_count,
                         per-track frame counts, tracks skipped for being
                         too short, extraction timestamp).

Per-track separation is load-bearing, not a style choice: this is what the
original FallDetectionState got wrong (one sliding-window queue per
camera, keypoints of different people interleaved in a single array) -
never merge multiple people's keypoints into one sequence here.

Memory: only per-frame keypoints (tiny: a handful of (17,3) floats per
detected person) are held across a whole video, never raw frames - each
frame is discarded immediately after extractor.extract() returns it a
keypoint list. Nothing accumulates ACROSS videos either: the extractor is
reset() and each video's intermediate arrays go out of scope before the
next video starts.

Usage:
    cd <repo root>              # must be repo root - pose_extraction/ is
                                 # a top-level package, needs to be on
                                 # sys.path (PYTHONPATH=. also works)
    python -m tools.pose_pipeline.extract_dataset videos/ output/
    # ablation: compare smoothed vs raw, held vs left-NaN edges
    python -m tools.pose_pipeline.extract_dataset videos/ output_raw/ --no-smoothing
    python -m tools.pose_pipeline.extract_dataset videos/ output_nohold/ --no-hold-edges
"""
import argparse
import datetime
import json
import os
import traceback
from collections import defaultdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import cv2
import numpy as np

from pose_extraction.factory import get_pose_extractor
from pose_extraction.normalization import CONF_THRESHOLD_DEFAULT, normalize_sequence
from pose_extraction.smoothing import smooth_sequence

UNOBSERVED_CONFIDENCE = -1.0  # sentinel: track not detected this frame - never a real 0.0 reading
DEFAULT_MIN_TRACK_LENGTH = 16  # matches the classifier's window size


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


def collect_track_sequences(frames_people: list) -> dict:
    """Pure aggregation, no I/O: a list of PosePerson-lists (one per
    frame) -> {track_id: ndarray(T,17,3) raw pixel-space}, one row per
    frame across the track's full [first_seen, last_seen] span. Frames
    within that span where the track wasn't detected get confidence
    UNOBSERVED_CONFIDENCE (never 0.0 - normalize_sequence treats this as
    unmeasured and interpolates/holds/drops it per its own rules, same as
    a genuinely low-confidence keypoint).
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


def extract_video(video_path: Path, extractor, apply_smoothing: bool, hold_edges: bool,
                   min_track_length: int, norm_conf_threshold: float) -> tuple:
    """Run pose extraction over every frame of one video.

    Returns (sequences, statuses, meta):
        sequences: dict[track_id, ndarray(T,17,3) float32] normalized (+smoothed)
        statuses:  dict[track_id, ndarray(T,17) int8]
        meta: {"fps", "width", "height", "frame_count", "tracks_detected",
               "tracks_kept", "tracks_skipped_short"}
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise IOError(f"could not open {video_path}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        frames_people = []
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frames_people.append(extractor.extract(frame))
    finally:
        cap.release()

    frame_count = len(frames_people)
    raw_sequences = collect_track_sequences(frames_people)

    sequences = {}
    statuses = {}
    skipped_short = 0
    for track_id, raw in raw_sequences.items():
        if raw.shape[0] < min_track_length:
            skipped_short += 1
            continue
        normalized, status = normalize_sequence(
            raw, conf_threshold=norm_conf_threshold, hold_edges=hold_edges
        )
        sequences[track_id] = smooth_sequence(normalized, fps=fps) if apply_smoothing else normalized
        statuses[track_id] = status

    meta = {
        "fps": fps,
        "width": width,
        "height": height,
        "frame_count": frame_count,
        "tracks_detected": len(raw_sequences),
        "tracks_kept": len(sequences),
        "tracks_skipped_short": skipped_short,
    }
    return sequences, statuses, meta


def _build_sidecar(video_path: Path, backend: str, model: str, backend_version: str,
                    imgsz, conf, tracker, apply_smoothing: bool, smoothing_params: dict,
                    hold_edges: bool, min_track_length: int, meta: dict, sequences: dict) -> dict:
    return {
        "video": video_path.name,
        "backend": backend,
        "model": model,
        "model_package_version": backend_version,
        "imgsz": imgsz,
        "conf": conf,
        "tracker": tracker,
        "smoothing": apply_smoothing,
        "smoothing_params": smoothing_params if apply_smoothing else None,
        "hold_edges": hold_edges,
        "min_track_length": min_track_length,
        "source": {
            "path": str(video_path),
            "width": meta["width"],
            "height": meta["height"],
            "fps": meta["fps"],
            "frame_count": meta["frame_count"],
        },
        "tracks": {
            str(track_id): {"frame_count": int(seq.shape[0])}
            for track_id, seq in sequences.items()
        },
        "tracks_detected": meta["tracks_detected"],
        "tracks_kept": meta["tracks_kept"],
        "tracks_skipped_short": meta["tracks_skipped_short"],
        "extracted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input_dir")
    parser.add_argument("output_dir")
    parser.add_argument("--pattern", default="*.mp4")
    parser.add_argument("--backend", choices=["yolo", "mediapipe"], default="yolo",
                         help="Note: defaults to 'yolo' here (STEP 3D production config), "
                              "NOT pose_extraction.factory's own 'mediapipe' default.")
    parser.add_argument("--weights", default="yolo11n-pose.pt")
    parser.add_argument("--conf", type=float, default=0.25, help="detector confidence threshold")
    parser.add_argument("--imgsz", type=int, default=480)
    parser.add_argument("--norm-conf-threshold", type=float, default=CONF_THRESHOLD_DEFAULT,
                         help="separate from --conf: gates whether a detected keypoint's own "
                              "confidence is high enough to normalize, not whether a person "
                              "was detected at all")
    parser.add_argument("--min-track-length", type=int, default=DEFAULT_MIN_TRACK_LENGTH)
    parser.add_argument("--no-smoothing", action="store_true")
    parser.add_argument("--no-hold-edges", action="store_true")
    parser.add_argument("--smoothing-min-cutoff", type=float, default=1.0)
    parser.add_argument("--smoothing-beta", type=float, default=0.007)
    args = parser.parse_args()

    os.environ["POSE_BACKEND"] = args.backend
    if args.backend == "yolo":
        os.environ["POSE_YOLO_WEIGHTS"] = args.weights
        os.environ["POSE_YOLO_CONF"] = str(args.conf)
        os.environ["POSE_YOLO_IMGSZ"] = str(args.imgsz)

    apply_smoothing = not args.no_smoothing
    hold_edges = not args.no_hold_edges

    extractor = get_pose_extractor()
    model_name = args.weights if args.backend == "yolo" else "mediapipe (mp.solutions.pose)"
    backend_version = _package_version("ultralytics" if args.backend == "yolo" else "mediapipe")
    tracker = "bytetrack.yaml" if args.backend == "yolo" else None
    imgsz = args.imgsz if args.backend == "yolo" else None
    conf = args.conf if args.backend == "yolo" else None

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    video_paths = sorted(Path(args.input_dir).glob(args.pattern))
    print(f"Found {len(video_paths)} video(s) matching {args.pattern!r} in {args.input_dir}",
          flush=True)

    ok_count = 0
    fail_count = 0
    for i, video_path in enumerate(video_paths, 1):
        print(f"[{i}/{len(video_paths)}] {video_path.name} ...", flush=True)
        extractor.reset()
        try:
            sequences, statuses, meta = extract_video(
                video_path, extractor, apply_smoothing, hold_edges,
                args.min_track_length, args.norm_conf_threshold,
            )
        except Exception:  # noqa: BLE001 - one bad video must not abort the batch
            fail_count += 1
            last_line = traceback.format_exc().strip().splitlines()[-1]
            print(f"  FAILED: {last_line}", flush=True)
            continue

        stem = video_path.stem
        np.save(output_dir / f"{stem}.npy", sequences, allow_pickle=True)
        np.save(output_dir / f"{stem}.status.npy", statuses, allow_pickle=True)

        smoothing_params = {
            "fps": meta["fps"],
            "min_cutoff": args.smoothing_min_cutoff,
            "beta": args.smoothing_beta,
        }
        sidecar = _build_sidecar(
            video_path, args.backend, model_name, backend_version, imgsz, conf, tracker,
            apply_smoothing, smoothing_params, hold_edges, args.min_track_length, meta, sequences,
        )
        (output_dir / f"{stem}.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

        ok_count += 1
        print(
            f"  OK: {meta['tracks_kept']} track(s) kept, "
            f"{meta['tracks_skipped_short']} skipped (< {args.min_track_length} frames), "
            f"{meta['frame_count']} frames total",
            flush=True,
        )

    print(f"\nDone: {ok_count} succeeded, {fail_count} failed, out of {len(video_paths)} video(s).")


if __name__ == "__main__":
    main()
