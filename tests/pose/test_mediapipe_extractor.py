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
