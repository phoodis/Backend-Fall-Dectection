#!/usr/bin/env python3
"""STEP 3E: side-by-side skeleton comparison, MediaPipe[:17] vs YOLO-pose
COCO-17, on the identical frame - the primary visual evidence for the
missing-lower-body defect this whole migration exists to fix.

Does not modify pose_extraction/* or anything under app/ - uses the
existing MediaPipePoseExtractor/YoloPoseExtractor unchanged, and does not
touch the extraction pipeline (tools/pose_pipeline/extract_dataset.py),
which may be mid-run on train4 while this runs on the Windows dev machine
(the only place mediapipe==0.10.14, with the legacy `mp.solutions` API
this repo depends on, is installed).

Usage:
    cd <repo root>
    python -m tools.pose_pipeline.compare_backends CLIP SECONDS OUTPUT \
        [--weights yolo11n-pose.pt] [--imgsz 480] [--conf 0.25]

    # batch: one comparison image per fall clip in labels.csv, at its impact_sec
    python -m tools.pose_pipeline.compare_backends --batch \
        videos/pose_eval/fall_clips/labels.csv \
        videos/pose_eval/fall_clips results/comparison
"""
import argparse
import csv
from pathlib import Path

import cv2
import numpy as np

from pose_extraction.mediapipe_extractor import MediaPipePoseExtractor
from pose_extraction.yolo_extractor import YoloPoseExtractor

# The two backends' 17 points are NOT the same 17 joints - see the table in
# the spec. Two separate edge lists, never one shared list.
#
# MediaPipe landmark[:17] raw slice: 0 nose,1-6 eyes,7-8 ears,9-10 mouth,
# 11-12 shoulders,13-14 elbows,15-16 wrists. Nothing below the shoulders
# exists in this slice - no edge drawn below them, on purpose. The absence
# IS the finding; do not invent an edge to make the drawing look complete.
MEDIAPIPE_SLICE17_EDGES = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (0, 11), (0, 12),
]

# COCO-17: 0 nose,1-2 eyes,3-4 ears,5-6 shoulders,7-8 elbows,9-10 wrists,
# 11-12 hips,13-14 knees,15-16 ankles.
COCO17_EDGES = [
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12),
    (11, 13), (13, 15), (12, 14), (14, 16),
    (0, 5), (0, 6),
]

# "Lower-body keypoints detected" counter, per backend's OWN topology (see
# the index table in the spec - index 11-16 means something different in
# each array). COCO's are real hip/knee/ankle indices, checked against
# confidence like any other measurement. MediaPipe's [:17] slice never
# contains hip/knee/ankle data at ALL - the real MediaPipe landmarks for
# those live at raw indices 23-28, past the [:17] cut - so there is no
# index in this array that COULD hold a lower-body reading. The count is
# therefore 0 by construction, not by a threshold check on indices 11-16
# of MediaPipe's array (which are real, usually well-detected shoulder/
# elbow/wrist data - counting THOSE as "lower-body" would be wrong and
# would silently invert the entire point of this comparison).
COCO_LOWER_BODY_INDICES = (11, 12, 13, 14, 15, 16)
MEDIAPIPE_LOWER_BODY_INDICES = ()

DEFAULT_CONF_THRESHOLD = 0.3

_CIRCLE_COLOR = (0, 255, 0)
_EDGE_COLOR = (0, 200, 255)
_BANNER_COLOR = (0, 0, 255)


def get_frame_at_seconds(video_path: Path, seconds: float):
    """Returns (frame, frame_idx, fps). Raises IOError if the frame can't
    be read (out-of-range timestamp, corrupt file, etc.)."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise IOError(f"could not open {video_path}")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_idx = int(round(seconds * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok or frame is None:
        raise IOError(f"could not read frame at {seconds}s (frame {frame_idx}) from {video_path}")
    return frame, frame_idx, fps


def count_detected(keypoints: np.ndarray, indices, conf_threshold: float = DEFAULT_CONF_THRESHOLD) -> int:
    return sum(1 for i in indices if keypoints[i, 2] >= conf_threshold)


def _draw_skeleton(panel: np.ndarray, keypoints: np.ndarray, edges: list,
                    conf_threshold: float) -> None:
    for x, y, c in keypoints:
        if c >= conf_threshold:
            cv2.circle(panel, (int(x), int(y)), 4, _CIRCLE_COLOR, -1)
    for a, b in edges:
        xa, ya, ca = keypoints[a]
        xb, yb, cb = keypoints[b]
        if ca >= conf_threshold and cb >= conf_threshold:
            cv2.line(panel, (int(xa), int(ya)), (int(xb), int(yb)), _EDGE_COLOR, 2)


def _draw_header(panel: np.ndarray, label: str) -> None:
    cv2.putText(panel, label, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)


def lower_body_label_text(lower_body_indices: tuple, lower_body: int) -> str:
    # "not in slice [:17]" on purpose, not "0/6": MediaPipe's array has no
    # index that COULD hold hip/knee/ankle data at all - this is a
    # structural absence, not a detection that failed. "0/6" reads as "we
    # looked and found none," which is a materially different (and untrue)
    # claim - reviewed feedback, 2026-10-01. A separate, testable function
    # (not inlined in the cv2.putText call) specifically so this exact
    # wording decision has a unit test, not just a visual check.
    if not lower_body_indices:
        return "lower-body: not in slice [:17]"
    return f"lower-body: {lower_body}/6"


def _draw_counters(panel: np.ndarray, total: int, lower_body_indices: tuple, lower_body: int) -> None:
    cv2.putText(panel, f"total: {total}/17", (10, 55),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.putText(panel, lower_body_label_text(lower_body_indices, lower_body), (10, 80),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)


def _draw_no_detection_banner(panel: np.ndarray, label: str) -> None:
    # An empty panel with no explanation looks like a bug, not a finding -
    # say so explicitly (spec constraint, verbatim).
    _draw_header(panel, label)
    cv2.putText(panel, "NO PERSON DETECTED", (10, panel.shape[0] // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, _BANNER_COLOR, 2)


def render_panel(frame: np.ndarray, people: list, edges: list, lower_body_indices: tuple,
                  label: str, conf_threshold: float = DEFAULT_CONF_THRESHOLD) -> np.ndarray:
    panel = frame.copy()
    if not people:
        _draw_no_detection_banner(panel, label)
        return panel

    keypoints = people[0].keypoints  # first detected person
    _draw_skeleton(panel, keypoints, edges, conf_threshold)

    total = count_detected(keypoints, range(17), conf_threshold)
    lower_body = count_detected(keypoints, lower_body_indices, conf_threshold)
    _draw_header(panel, label)
    _draw_counters(panel, total, lower_body_indices, lower_body)
    return panel


def compare_frame(frame: np.ndarray, mediapipe_extractor, yolo_extractor,
                   conf_threshold: float = DEFAULT_CONF_THRESHOLD) -> np.ndarray:
    """The core comparison: BOTH extractors receive the SAME frame object -
    comparing different frames would invalidate the whole point (spec,
    verbatim). Returns the hstacked, annotated comparison image.
    """
    mediapipe_people = mediapipe_extractor.extract(frame)
    yolo_people = yolo_extractor.extract(frame)

    left = render_panel(frame, mediapipe_people, MEDIAPIPE_SLICE17_EDGES,
                         MEDIAPIPE_LOWER_BODY_INDICES, "MediaPipe landmark[:17]", conf_threshold)
    right = render_panel(frame, yolo_people, COCO17_EDGES,
                          COCO_LOWER_BODY_INDICES, "YOLO-pose (COCO-17)", conf_threshold)

    return np.hstack([left, right])


def compare_clip_at_seconds(clip_path: Path, seconds: float, output_path: Path,
                             weights: str, imgsz: int, conf: float,
                             conf_threshold: float = DEFAULT_CONF_THRESHOLD,
                             mediapipe_extractor=None, yolo_extractor=None) -> dict:
    """Extracts the frame at `seconds` in `clip_path`, runs both backends,
    saves the side-by-side comparison to `output_path`. Returns a dict of
    measured numbers for reporting (frame_idx, fps, per-backend total and
    lower-body counts).

    `mediapipe_extractor`/`yolo_extractor` default to a fresh instance per
    call (the CLI never reuses one across clips - same reasoning as
    tools/pose_pipeline/extract_dataset.py's fresh-extractor-per-video
    fix: a shared YoloPoseExtractor with ByteTrack across unrelated clips
    risks the same class of persist=True tracker-state bug fixed there,
    and would carry meaningless track IDs across clip boundaries anyway).
    Accepting them as parameters exists so tests can inject fakes without
    needing real model weights - not to encourage reuse.
    """
    frame, frame_idx, fps = get_frame_at_seconds(clip_path, seconds)

    if mediapipe_extractor is None:
        mediapipe_extractor = MediaPipePoseExtractor()
    if yolo_extractor is None:
        yolo_extractor = YoloPoseExtractor(weights_path=weights, conf=conf, imgsz=imgsz)

    mediapipe_people = mediapipe_extractor.extract(frame)
    yolo_people = yolo_extractor.extract(frame)

    left = render_panel(frame, mediapipe_people, MEDIAPIPE_SLICE17_EDGES,
                         MEDIAPIPE_LOWER_BODY_INDICES, "MediaPipe landmark[:17]", conf_threshold)
    right = render_panel(frame, yolo_people, COCO17_EDGES,
                          COCO_LOWER_BODY_INDICES, "YOLO-pose (COCO-17)", conf_threshold)
    combined = np.hstack([left, right])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), combined)

    mediapipe_total = count_detected(mediapipe_people[0].keypoints, range(17), conf_threshold) if mediapipe_people else 0
    mediapipe_lower = count_detected(mediapipe_people[0].keypoints, MEDIAPIPE_LOWER_BODY_INDICES, conf_threshold) if mediapipe_people else 0
    yolo_total = count_detected(yolo_people[0].keypoints, range(17), conf_threshold) if yolo_people else 0
    yolo_lower = count_detected(yolo_people[0].keypoints, COCO_LOWER_BODY_INDICES, conf_threshold) if yolo_people else 0

    return {
        "clip": clip_path.name,
        "seconds": seconds,
        "frame_idx": frame_idx,
        "fps": fps,
        "output": str(output_path),
        "mediapipe_detected": bool(mediapipe_people),
        "mediapipe_total": mediapipe_total,
        "mediapipe_lower_body": mediapipe_lower,
        "yolo_detected": bool(yolo_people),
        "yolo_total": yolo_total,
        "yolo_lower_body": yolo_lower,
    }


def _read_fall_clips(labels_csv: Path):
    """Yields (clip_id, impact_sec) for every row with has_fall=1 and a
    non-empty impact_sec - skips normal_*/bed_* rows, which have neither.
    """
    with open(labels_csv, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("has_fall", "").strip() != "1":
                continue
            impact_sec = row.get("impact_sec", "").strip()
            if not impact_sec:
                continue
            yield row["clip_id"], float(impact_sec)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("positional", nargs=3,
                         help="CLIP SECONDS OUTPUT (single mode), or "
                              "LABELS_CSV CLIPS_DIR OUTPUT_DIR (--batch mode)")
    parser.add_argument("--batch", action="store_true",
                         help="batch mode: first arg is labels.csv, second is the clips "
                              "directory, third is the output directory")
    parser.add_argument("--weights", default="yolo11n-pose.pt")
    parser.add_argument("--imgsz", type=int, default=480)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--conf-threshold", type=float, default=DEFAULT_CONF_THRESHOLD,
                         help="per-keypoint confidence threshold for drawing/counting "
                              "(separate from --conf, the detector's own threshold)")
    args = parser.parse_args()

    if args.batch:
        labels_csv, clips_dir, output_dir = (Path(p) for p in args.positional)
        output_dir.mkdir(parents=True, exist_ok=True)

        results = []
        for clip_id, impact_sec in _read_fall_clips(labels_csv):
            clip_path = clips_dir / clip_id
            output_path = output_dir / f"{Path(clip_id).stem}_compare.jpg"
            print(f"{clip_id} @ {impact_sec}s ...", flush=True)
            try:
                result = compare_clip_at_seconds(
                    clip_path, impact_sec, output_path,
                    args.weights, args.imgsz, args.conf, args.conf_threshold,
                )
            except Exception as exc:  # noqa: BLE001 - one bad clip must not abort the batch
                print(f"  FAILED: {exc}", flush=True)
                continue
            results.append(result)
            # "not in slice [:17]", not "0/6" - see _draw_counters: a
            # structural absence of lower-body data is a different, and
            # more defensible, claim than "we looked and found none".
            print(
                f"  -> {output_path.name}: mediapipe lower-body not in slice [:17], "
                f"yolo lower-body {result['yolo_lower_body']}/6",
                flush=True,
            )

        print(f"\n{'clip':<14} {'mediapipe lower-body':>22} {'yolo lower-body':>18}")
        for r in results:
            print(f"{r['clip']:<14} {'not in slice [:17]':>22} {r['yolo_lower_body']:>17}/6")
        print(f"\nDone: {len(results)} comparison image(s) written to {output_dir}")
    else:
        clip_path = Path(args.positional[0])
        seconds = float(args.positional[1])
        output_path = Path(args.positional[2])

        result = compare_clip_at_seconds(
            clip_path, seconds, output_path,
            args.weights, args.imgsz, args.conf, args.conf_threshold,
        )
        print(f"frame {result['frame_idx']} (fps={result['fps']:.2f}) from {result['clip']} @ {seconds}s")
        print(f"MediaPipe: total {result['mediapipe_total']}/17, lower-body not in slice [:17]")
        print(f"YOLO:      total {result['yolo_total']}/17, lower-body {result['yolo_lower_body']}/6")
        print(f"Saved: {result['output']}")


if __name__ == "__main__":
    main()
