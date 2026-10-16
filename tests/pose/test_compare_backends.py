from pathlib import Path

import cv2
import numpy as np

from pose_extraction.base import PosePerson
from tools.pose_pipeline.compare_backends import (
    COCO17_EDGES,
    COCO_LOWER_BODY_INDICES,
    MEDIAPIPE_LOWER_BODY_INDICES,
    MEDIAPIPE_SLICE17_EDGES,
    _read_fall_clips,
    compare_clip_at_seconds,
    count_detected,
    get_frame_at_seconds,
    lower_body_label_text,
    render_panel,
)


def _person(keypoints: np.ndarray) -> PosePerson:
    return PosePerson(track_id=0, keypoints=keypoints, bbox=[0, 0, 10, 10])


def _make_keypoints(conf_by_index: dict) -> np.ndarray:
    kp = np.zeros((17, 3), dtype=np.float32)
    kp[:, :2] = 50.0
    for i, conf in conf_by_index.items():
        kp[i, 2] = conf
    return kp


def _write_synthetic_video(path: Path, n_frames: int = 20, fps: float = 10.0):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (64, 64))
    for i in range(n_frames):
        writer.write(np.full((64, 64, 3), i % 256, dtype=np.uint8))
    writer.release()


# --- acceptance test 1: both backends receive byte-identical frame data ---

def test_compare_clip_at_seconds_gives_both_backends_the_identical_frame(tmp_path):
    video_path = tmp_path / "synthetic.mp4"
    _write_synthetic_video(video_path, n_frames=10)

    captured = {}

    class _CapturingExtractor:
        def __init__(self, key):
            self.key = key

        def extract(self, frame):
            captured[self.key] = frame
            return []

    compare_clip_at_seconds(
        video_path, seconds=0.5, output_path=tmp_path / "out.jpg",
        weights="unused", imgsz=480, conf=0.25,
        mediapipe_extractor=_CapturingExtractor("mediapipe"),
        yolo_extractor=_CapturingExtractor("yolo"),
    )

    assert captured["mediapipe"] is captured["yolo"]  # same object, not merely equal content
    assert np.array_equal(captured["mediapipe"], captured["yolo"])


# --- acceptance test 2: MediaPipe edge list contains no lower-body edge ---
#
# NOTE on interpreting "no edge involving indices 11-16" (the literal
# acceptance-test wording): taken completely literally this would forbid
# the shoulder(11,12)-elbow(13,14)-wrist(15,16) chain the OUTPUT
# REQUIREMENTS section explicitly asks for ("shoulder-to-shoulder,
# shoulder->elbow->wrist on each side") - those ARE indices 11-16 in
# MediaPipe's OWN 17-point array. The two requirements only make sense
# together if "indices 11-16" means COCO's hip/knee/ankle positions (the
# spec's own index-mapping table), not MediaPipe's identically-numbered
# but differently-meaning positions. What's actually verified below: the
# edge list is EXACTLY the known-correct shoulder/elbow/wrist chain -
# nothing invented, nothing extended toward a leg - and (separately, in
# the lower-body-counter tests) that MediaPipe's array has no encoding
# for hip/knee/ankle at all, so there is no possible "missing leg edge"
# to have omitted in the first place.

def test_mediapipe_edge_list_is_exactly_the_shoulder_elbow_wrist_chain_no_more():
    expected = {(11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (0, 11), (0, 12)}
    assert set(MEDIAPIPE_SLICE17_EDGES) == expected


# --- acceptance test 3: COCO edge list includes shoulder-hip-knee-ankle ---

def test_coco_edge_list_includes_shoulder_hip_knee_ankle_chain():
    assert (5, 11) in COCO17_EDGES or (11, 5) in COCO17_EDGES  # shoulder -> hip
    assert (11, 13) in COCO17_EDGES  # hip -> knee
    assert (13, 15) in COCO17_EDGES  # knee -> ankle
    assert (6, 12) in COCO17_EDGES  # shoulder -> hip, other side
    assert (12, 14) in COCO17_EDGES  # hip -> knee, other side
    assert (14, 16) in COCO17_EDGES  # knee -> ankle, other side


# --- acceptance test 4: lower-body counter ---

def test_coco_lower_body_counter_reflects_confidence_at_11_16():
    kp = _make_keypoints({11: 0.9, 12: 0.9, 13: 0.9, 14: 0.1, 15: 0.1, 16: 0.9})
    assert count_detected(kp, COCO_LOWER_BODY_INDICES, conf_threshold=0.3) == 4


def test_mediapipe_lower_body_counter_is_always_zero_regardless_of_confidence():
    # Indices 11-16 in the MediaPipe[:17] slice are shoulders/elbows/wrists
    # (real, often well-detected data) - NOT lower-body joints. Counting
    # them as "lower-body" would be wrong and would silently invert the
    # whole point of this comparison. MEDIAPIPE_LOWER_BODY_INDICES is
    # empty on purpose: there is no index in this 17-element array that
    # could hold hip/knee/ankle data, so the count must be 0 by
    # construction, not by a threshold check that happens to pass.
    kp_all_confident = _make_keypoints({i: 0.99 for i in range(17)})
    assert count_detected(kp_all_confident, MEDIAPIPE_LOWER_BODY_INDICES, conf_threshold=0.3) == 0


# "not in slice [:17]", not "0/6" (reviewed feedback, 2026-10-01): a
# structural absence of lower-body data in MediaPipe's array is a
# different, more defensible claim than "we looked and found none" -
# which is what a bare "0/6" would read as under presentation questioning.

def test_mediapipe_panel_label_says_not_in_slice_not_zero_of_six():
    assert lower_body_label_text(MEDIAPIPE_LOWER_BODY_INDICES, 0) == "lower-body: not in slice [:17]"


def test_coco_panel_label_still_reports_a_real_fraction():
    assert lower_body_label_text(COCO_LOWER_BODY_INDICES, 4) == "lower-body: 4/6"


def test_render_panel_draws_the_lower_body_counter_for_coco():
    kp = _make_keypoints({i: 0.9 for i in range(17)})
    people = [_person(kp)]
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    panel = render_panel(frame, people, COCO17_EDGES, COCO_LOWER_BODY_INDICES, "YOLO-pose (COCO-17)")

    assert panel.shape == frame.shape
    assert not np.array_equal(panel, frame)  # something was actually drawn


# --- acceptance test 5: a backend detecting nobody produces a labelled panel, not a crash ---

def test_render_panel_with_no_people_produces_a_labelled_panel_not_a_crash():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    panel = render_panel(frame, [], MEDIAPIPE_SLICE17_EDGES, MEDIAPIPE_LOWER_BODY_INDICES, "MediaPipe landmark[:17]")

    assert panel.shape == frame.shape
    assert not np.array_equal(panel, frame)  # the "no detection" banner was drawn, not a blank frame


def test_compare_clip_at_seconds_handles_one_backend_detecting_nobody(tmp_path):
    video_path = tmp_path / "synthetic.mp4"
    _write_synthetic_video(video_path, n_frames=10)

    class _NoDetectionExtractor:
        def extract(self, frame):
            return []

    class _DetectingExtractor:
        def extract(self, frame):
            kp = np.zeros((17, 3), dtype=np.float32)
            kp[:, :2] = 10.0
            kp[:, 2] = 0.9
            return [_person(kp)]

    output_path = tmp_path / "out.jpg"
    result = compare_clip_at_seconds(
        video_path, seconds=0.5, output_path=output_path,
        weights="unused", imgsz=480, conf=0.25,
        mediapipe_extractor=_NoDetectionExtractor(),
        yolo_extractor=_DetectingExtractor(),
    )

    assert output_path.exists()
    assert result["mediapipe_detected"] is False
    assert result["mediapipe_total"] == 0
    assert result["mediapipe_lower_body"] == 0
    assert result["yolo_detected"] is True
    assert result["yolo_total"] == 17
    assert result["yolo_lower_body"] == 6


# --- supporting helpers ---

def test_get_frame_at_seconds_reads_the_right_frame_index(tmp_path):
    video_path = tmp_path / "synthetic.mp4"
    _write_synthetic_video(video_path, n_frames=20, fps=10.0)

    frame, frame_idx, fps = get_frame_at_seconds(video_path, seconds=0.5)

    assert fps == 10.0
    assert frame_idx == 5
    assert frame.shape == (64, 64, 3)


def test_read_fall_clips_skips_non_fall_rows_and_parses_impact_sec(tmp_path):
    labels_csv = tmp_path / "labels.csv"
    labels_csv.write_text(
        "clip_id,has_fall,impact_sec\n"
        "Fall_1.mp4,1,9\n"
        "Fall_6.mp4,1,6.2\n"
        "normal_1.mp4,0,\n"
        "bed_1.mp4,0,\n",
        encoding="utf-8",
    )

    rows = list(_read_fall_clips(labels_csv))

    assert rows == [("Fall_1.mp4", 9.0), ("Fall_6.mp4", 6.2)]
