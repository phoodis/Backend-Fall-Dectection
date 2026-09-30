import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from pose_extraction.base import PosePerson
from pose_extraction.normalization import HELD, INTERPOLATED, MEASURED, MISSING
from tools.pose_pipeline.extract_dataset import (
    _build_sidecar,
    collect_track_sequences,
    extract_video,
)


def _person(track_id: int, x: float = 100.0, y: float = 100.0) -> PosePerson:
    keypoints = np.zeros((17, 3), dtype=np.float32)
    keypoints[:, 0] = x
    keypoints[:, 1] = y
    keypoints[:, 2] = 1.0
    # Shoulders (5,6) and hips (11,12) must be apart, or
    # pose_extraction.normalization's torso-length guard correctly treats
    # every frame as a degenerate (zero-torso) detection and NaNs the
    # whole thing - not a bug, just needs a non-degenerate fixture here.
    keypoints[5, 1] = y - 20  # left shoulder
    keypoints[6, 1] = y - 20  # right shoulder
    keypoints[11, 1] = y      # left hip
    keypoints[12, 1] = y      # right hip
    return PosePerson(track_id=track_id, keypoints=keypoints, bbox=[0, 0, 10, 10])


# --- pure aggregation (collect_track_sequences) ---

def test_collects_one_track_spanning_full_clip():
    frames_people = [[_person(0)], [_person(0)], [_person(0)]]
    sequences = collect_track_sequences(frames_people)

    assert set(sequences.keys()) == {0}
    assert sequences[0].shape == (3, 17, 3)
    assert sequences[0].dtype == np.float32


# --- acceptance test 3: two people in one frame -> two separate arrays ---

def test_two_simultaneous_people_produce_two_separate_track_arrays():
    frames_people = [
        [_person(1, x=100), _person(2, x=500)],
        [_person(1, x=101), _person(2, x=501)],
    ]
    sequences = collect_track_sequences(frames_people)

    assert set(sequences.keys()) == {1, 2}
    assert all(seq.shape == (2, 17, 3) for seq in sequences.values())
    # not merged: each track keeps its own x position, not an average of both
    assert sequences[1][0, 0, 0] == 100.0
    assert sequences[2][0, 0, 0] == 500.0


def test_gap_frame_is_marked_unobserved_not_zero_confidence():
    frames_people = [[_person(0)], [], [_person(0)]]  # occluded on frame 1
    sequences = collect_track_sequences(frames_people)

    assert sequences[0].shape == (3, 17, 3)
    assert sequences[0][1, 0, 2] == -1.0  # UNOBSERVED_CONFIDENCE, not 0.0


def test_single_frame_track_is_dropped():
    assert collect_track_sequences([[_person(5)]]) == {}


# --- fake, dependency-free extractor for extract_video() integration tests ---
# (avoids needing real model weights/network access for these tests)

class _TwoPeopleExtractor:
    def __init__(self):
        self.frame_idx = 0
        self.reset_count = 0

    def extract(self, frame):
        people = [_person(1, x=100 + self.frame_idx), _person(2, x=500 - self.frame_idx)]
        self.frame_idx += 1
        return people

    def reset(self):
        self.reset_count += 1
        self.frame_idx = 0


def _write_synthetic_video(path: Path, n_frames: int = 20, fps: float = 10.0):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (64, 64))
    for i in range(n_frames):
        frame = np.full((64, 64, 3), i % 256, dtype=np.uint8)
        writer.write(frame)
    writer.release()


# --- acceptance tests 1 & 2: output shape/dtype, status mask shape/values ---

def test_extract_video_output_shapes_and_dtypes(tmp_path):
    video_path = tmp_path / "synthetic.mp4"
    _write_synthetic_video(video_path, n_frames=20)

    sequences, statuses, meta = extract_video(
        video_path, _TwoPeopleExtractor(), apply_smoothing=True, hold_edges=True,
        min_track_length=16, norm_conf_threshold=0.3,
    )

    valid_codes = {MEASURED, INTERPOLATED, HELD, MISSING}
    assert set(sequences.keys()) == {1, 2}
    for track_id, seq in sequences.items():
        assert seq.dtype == np.float32
        assert seq.shape == (20, 17, 3)
        status = statuses[track_id]
        assert status.dtype == np.int8
        assert status.shape == (20, 17)  # same as sequence, minus the coordinate axis
        assert set(np.unique(status).tolist()) <= valid_codes

    assert meta["frame_count"] == 20
    assert meta["tracks_kept"] == 2
    assert meta["tracks_skipped_short"] == 0


def test_extract_video_skips_tracks_shorter_than_minimum(tmp_path):
    class _OneShortTrackExtractor:
        def __init__(self):
            self.frame_idx = 0

        def extract(self, frame):
            people = [_person(1)]
            if self.frame_idx < 3:  # track 2 only appears for 3 frames - shorter than min
                people.append(_person(2))
            self.frame_idx += 1
            return people

        def reset(self):
            self.frame_idx = 0

    video_path = tmp_path / "synthetic.mp4"
    _write_synthetic_video(video_path, n_frames=20)

    sequences, statuses, meta = extract_video(
        video_path, _OneShortTrackExtractor(), apply_smoothing=False, hold_edges=True,
        min_track_length=16, norm_conf_threshold=0.3,
    )

    assert set(sequences.keys()) == {1}
    assert meta["tracks_skipped_short"] == 1


def test_extract_video_handles_intermittent_detection_dropout_end_to_end(tmp_path):
    # Full pipeline (extract_video -> collect_track_sequences ->
    # normalize_sequence) driven by an extractor whose detection rate
    # mimics real clips (Fall_1 62.5%, Fall_3 12.5%, Fall_2 0% per the
    # Step 2 gate) - gap frames are the normal case for this dataset, not
    # an edge case. Must not crash, and gap frames must show up as MISSING
    # in the status mask, never silently dropped or fabricated.
    #
    # Detected on video frame i whenever i % 3 != 0 (frame 0 itself is
    # therefore a gap, so the track - per collect_track_sequences' documented
    # [first_seen, last_seen] span - starts at frame 1, not frame 0; hence
    # 20 frames (1..20 inclusive) below, not the full 21-frame video).
    class _IntermittentExtractor:
        def __init__(self):
            self.frame_idx = 0

        def extract(self, frame):
            detected = self.frame_idx % 3 != 0  # 2 out of every 3 frames detected
            self.frame_idx += 1
            return [_person(1)] if detected else []

        def reset(self):
            self.frame_idx = 0

    video_path = tmp_path / "synthetic.mp4"
    _write_synthetic_video(video_path, n_frames=21)

    sequences, statuses, meta = extract_video(
        video_path, _IntermittentExtractor(), apply_smoothing=True, hold_edges=True,
        min_track_length=16, norm_conf_threshold=0.3,
    )

    assert set(sequences.keys()) == {1}
    status = statuses[1]
    assert status.shape == (20, 17)  # video frames 1..20 inclusive - see note above
    # video frames 3, 6, 9, 12, 15, 18 were gaps -> track-local indices 2, 5, 8, 11, 14, 17
    gap_track_indices = [2, 5, 8, 11, 14, 17]
    assert (status[gap_track_indices] != MEASURED).all()
    # hold_edges=True and every gap here has a measured neighbour, so every
    # gap gets filled (HELD or INTERPOLATED), never left NaN. (The
    # never-zero-fill guarantee itself is exhaustively covered in
    # test_normalization.py; this test's job is the gap/dropout pipeline.)
    assert not np.isnan(sequences[1][gap_track_indices, :, :2]).any()


# --- acceptance test 4: sidecar JSON contains every required field ---

def test_sidecar_contains_all_required_fields(tmp_path):
    video_path = tmp_path / "fall_01.mp4"
    meta = {
        "fps": 30.0, "width": 640, "height": 480, "frame_count": 90,
        "tracks_detected": 2, "tracks_kept": 2, "tracks_skipped_short": 0,
    }
    sequences = {
        1: np.zeros((90, 17, 3), dtype=np.float32),
        2: np.zeros((80, 17, 3), dtype=np.float32),
    }

    sidecar = _build_sidecar(
        video_path, backend="yolo", model="yolo11n-pose.pt", backend_version="8.4.165",
        imgsz=480, conf=0.25, tracker="bytetrack.yaml", apply_smoothing=True,
        smoothing_params={"fps": 30.0, "min_cutoff": 1.0, "beta": 0.007},
        hold_edges=True, min_track_length=16, meta=meta, sequences=sequences,
    )

    required_top_level = {
        "video", "backend", "model", "model_package_version", "imgsz", "conf",
        "tracker", "smoothing", "smoothing_params", "hold_edges", "min_track_length",
        "source", "tracks", "tracks_detected", "tracks_kept", "tracks_skipped_short",
        "extracted_at",
    }
    assert required_top_level <= sidecar.keys()
    assert sidecar["source"].keys() == {"path", "width", "height", "fps", "frame_count"}
    assert sidecar["tracks"] == {"1": {"frame_count": 90}, "2": {"frame_count": 80}}
    assert sidecar["model_package_version"] == "8.4.165"

    json.dumps(sidecar)  # must be JSON-serializable as-is - this is what gets written to disk


def test_sidecar_nulls_smoothing_params_when_smoothing_disabled():
    sidecar = _build_sidecar(
        Path("x.mp4"), backend="mediapipe", model="mediapipe (mp.solutions.pose)",
        backend_version="0.10.14", imgsz=None, conf=None, tracker=None,
        apply_smoothing=False, smoothing_params={"fps": 30.0, "min_cutoff": 1.0, "beta": 0.007},
        hold_edges=False, min_track_length=16,
        meta={"fps": 30.0, "width": 1, "height": 1, "frame_count": 1,
              "tracks_detected": 0, "tracks_kept": 0, "tracks_skipped_short": 0},
        sequences={},
    )
    assert sidecar["smoothing"] is False
    assert sidecar["smoothing_params"] is None


# --- consecutive-error abort guard (2026-09-30 review, after the
# source=[frame] root cause was found: extract() must tolerate the
# occasional bad frame, but a long unbroken run of real errors must not
# silently produce a near-empty dataset - it must abort loudly instead) ---

def test_extract_video_aborts_after_too_many_consecutive_errors(tmp_path):
    class _AlwaysErroringExtractor:
        """Simulates an extractor whose every call is a genuine internal
        failure (not a legitimate no-detection frame) - consecutive_errors
        climbs every call and never resets, exactly like a systematic bug
        such as the source=[frame] one would look like from the caller's
        side before it was diagnosed.
        """

        def __init__(self):
            self.consecutive_errors = 0

        def extract(self, frame):
            self.consecutive_errors += 1
            return []

        def reset(self):
            self.consecutive_errors = 0

    video_path = tmp_path / "synthetic.mp4"
    _write_synthetic_video(video_path, n_frames=50)

    with pytest.raises(RuntimeError, match="consecutive"):
        extract_video(
            video_path, _AlwaysErroringExtractor(), apply_smoothing=False, hold_edges=True,
            min_track_length=1, norm_conf_threshold=0.3, max_consecutive_errors=10,
        )


def test_extract_video_tolerates_errors_that_do_not_stay_consecutive(tmp_path):
    class _OccasionallyErroringExtractor:
        """consecutive_errors resets whenever a call succeeds, same as the
        real YoloPoseExtractor - occasional failures scattered through a
        clip must never trip the abort."""

        def __init__(self):
            self.consecutive_errors = 0
            self.frame_idx = 0

        def extract(self, frame):
            is_error = self.frame_idx % 5 == 0  # fails 1 in 5 frames, never 2 in a row
            self.frame_idx += 1
            if is_error:
                self.consecutive_errors += 1
                return []
            self.consecutive_errors = 0
            return [_person(1)]

        def reset(self):
            self.consecutive_errors = 0
            self.frame_idx = 0

    video_path = tmp_path / "synthetic.mp4"
    _write_synthetic_video(video_path, n_frames=30)

    # must not raise, even with max_consecutive_errors as low as 1 extra
    # failure, since no two failures in this pattern are ever back-to-back
    sequences, statuses, meta = extract_video(
        video_path, _OccasionallyErroringExtractor(), apply_smoothing=False, hold_edges=True,
        min_track_length=1, norm_conf_threshold=0.3, max_consecutive_errors=2,
    )
    assert set(sequences.keys()) == {1}


# --- regression test for the CONFIRMED root cause (2026-09-30): a shared
# extractor reused across videos via .reset() crashed every video after
# the first. Uses the REAL ultralytics model (already cached locally from
# earlier investigation, so no network needed) rather than a mock -
# per the same lesson learned earlier in this file (test_extract_calls_
# track_with_the_bare_frame_not_a_list), a mocked .track() cannot fail
# this way, since the bug lives in ultralytics' own tracker-callback state
# machine, not in anything pose_extraction's code decides to call. ---

def test_processing_two_videos_back_to_back_with_real_yolo_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("POSE_BACKEND", "yolo")
    monkeypatch.setenv("POSE_YOLO_WEIGHTS", "yolo11n-pose.pt")
    monkeypatch.setenv("POSE_YOLO_IMGSZ", "64")

    from pose_extraction.factory import get_pose_extractor

    video_a = tmp_path / "a.mp4"
    video_b = tmp_path / "b.mp4"
    _write_synthetic_video(video_a, n_frames=3)
    _write_synthetic_video(video_b, n_frames=3)

    # The actual fix: a fresh extractor per video, exactly as
    # tools/pose_pipeline/extract_dataset.py's main() loop now does -
    # NOT one extractor.reset()-ed and reused, which is what crashed on
    # train4 on every video after the first.
    for video_path in (video_a, video_b):
        extractor = get_pose_extractor()
        extract_video(
            video_path, extractor, apply_smoothing=False, hold_edges=True,
            min_track_length=1, norm_conf_threshold=0.3,
        )
    # must reach here without raising


# --- acceptance test 5: a corrupt video is skipped, the batch continues ---

def test_corrupt_video_is_skipped_and_batch_continues(tmp_path):
    input_dir = tmp_path / "videos"
    input_dir.mkdir()
    output_dir = tmp_path / "output"

    good_video = input_dir / "good.mp4"
    _write_synthetic_video(good_video, n_frames=20)

    corrupt_video = input_dir / "corrupt.mp4"
    corrupt_video.write_bytes(b"not a real video file")

    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "tools.pose_pipeline.extract_dataset",
         str(input_dir), str(output_dir), "--backend", "mediapipe", "--min-track-length", "1"],
        capture_output=True, text=True, cwd=str(repo_root), timeout=60,
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "FAILED" in result.stdout
    assert "Done: 1 succeeded, 1 failed, out of 2 video(s)." in result.stdout
    assert (output_dir / "good.npy").exists()
    assert (output_dir / "good.status.npy").exists()
    assert (output_dir / "good.json").exists()
    assert not (output_dir / "corrupt.npy").exists()


# --- acceptance test 6: importable/runnable without Flask/Celery/app present ---

def test_script_module_import_does_not_pull_in_flask_or_app():
    script = (
        "import sys\n"
        "import tools.pose_pipeline.extract_dataset\n"
        "print('flask' in sys.modules)\n"
        "print(any(m == 'app' or m.startswith('app.') for m in sys.modules))\n"
    )
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd=str(repo_root), timeout=30,
    )
    assert result.returncode == 0, f"import failed:\n{result.stdout}\n{result.stderr}"
    assert result.stdout.strip().splitlines() == ["False", "False"], result.stdout
