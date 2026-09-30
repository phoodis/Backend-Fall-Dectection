import numpy as np


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
    from app.detection.pose.yolo_extractor import YoloPoseExtractor

    extractor = YoloPoseExtractor.__new__(YoloPoseExtractor)  # skip YOLO(weights) load
    extractor._conf = 0.25
    extractor._imgsz = 480
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

    monkeypatch.setattr("app.detection.pose.yolo_extractor.YOLO", _FakeYOLO)

    from app.detection.pose.yolo_extractor import YoloPoseExtractor
    extractor = YoloPoseExtractor(weights_path="yolo11n-pose.pt")

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    extractor.extract(frame)
    extractor.extract(frame)
    extractor.extract(frame)

    assert load_count["n"] == 1
