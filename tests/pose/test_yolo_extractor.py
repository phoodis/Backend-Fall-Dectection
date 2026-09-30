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
    from pose_extraction.yolo_extractor import YoloPoseExtractor

    extractor = YoloPoseExtractor.__new__(YoloPoseExtractor)  # skip YOLO(weights) load
    extractor._conf = 0.25
    extractor._imgsz = 480
    extractor._device = "cpu"
    extractor.consecutive_errors = 0
    return extractor


def test_extract_calls_track_with_the_bare_frame_not_a_list():
    # CONFIRMED root cause of the train4 crash (2026-09-30, see spec
    # addendum): model.track(source=[frame]) makes ultralytics treat the
    # call as a batch of independent sources and skip creating
    # predictor.trackers for it, so its on_predict_postprocess_end callback
    # later crashes indexing trackers[0]. source=frame (the bare ndarray)
    # is the correct single-source call. This is exactly the gap the old
    # 54/54-passing suite had: every fake .track() here accepted `source`
    # as whatever shape it was given without checking, so a wrong call
    # shape could never fail a test - acceptance tests passed 10/10 on the
    # dev machine while the real run failed 12/13 on train4. This test
    # closes that gap by asserting the call shape itself, not just the
    # result of the call.
    captured = {}

    class _CapturingModel:
        def track(self, **kw):
            captured.update(kw)
            return [_FakeResult(None, None)]

    extractor = _make_extractor_without_loading_weights()
    extractor._model = _CapturingModel()

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    extractor.extract(frame)

    assert "source" in captured
    assert not isinstance(captured["source"], list), (
        "source must be the bare ndarray - wrapping it in a list is the "
        "confirmed root cause of the train4 crash, see spec addendum 2026-09-30"
    )
    assert captured["source"] is frame


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
    # This IS the "boxes present, boxes.id is None" case reported from real
    # train4 extraction runs (ByteTrack hasn't confirmed a track yet for
    # this detection) - not a hypothetical. Already guarded before the
    # 2026-09-30 hardening pass; kept/renamed for clarity, not new.
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


def test_extract_returns_empty_when_boxes_present_but_keypoints_missing():
    xyxy = np.array([[0, 0, 10, 10]], dtype=np.float32)
    fake_result = _FakeResult(keypoints=None, boxes=_FakeBoxes(xyxy, ids=None))

    extractor = _make_extractor_without_loading_weights()
    extractor._model = type("M", (), {"track": lambda self, **kw: [fake_result]})()

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    assert extractor.extract(frame) == []


def test_extract_returns_empty_when_model_track_raises():
    # The real train4 crash (TypeError: 'NoneType' object is not
    # subscriptable) is now understood to be the source=[frame] bug fixed
    # above, not this path. This guard stays anyway: .track() failing for
    # some other, genuinely unexpected reason must still degrade to "no
    # detection this frame" rather than crash the whole clip - it now also
    # increments consecutive_errors (see the tests below) so a sustained
    # run of real failures still surfaces instead of being silently
    # swallowed forever.
    class _RaisingModel:
        def track(self, **kw):
            raise TypeError("'NoneType' object is not subscriptable")

    extractor = _make_extractor_without_loading_weights()
    extractor._model = _RaisingModel()

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    assert extractor.extract(frame) == []


def test_extract_returns_empty_when_unpacking_raises_unexpectedly():
    class _ExplodingTensor:
        def cpu(self):
            raise RuntimeError("simulated unexpected tensor state")

    class _ExplodingKeypoints:
        xy = _ExplodingTensor()
        conf = None

    xyxy = np.array([[0, 0, 10, 10]], dtype=np.float32)
    fake_result = _FakeResult(_ExplodingKeypoints(), _FakeBoxes(xyxy, ids=None))

    extractor = _make_extractor_without_loading_weights()
    extractor._model = type("M", (), {"track": lambda self, **kw: [fake_result]})()

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    assert extractor.extract(frame) == []


def test_extract_handles_alternating_tracked_and_untracked_frames():
    # The real pattern in these clips per the Step 2 gate (Fall_1 62.5%,
    # Fall_10 46.7%, Fall_3 12.5%, Fall_2 0% detection rate) - not a rare
    # edge case, the normal case. Calls extract() repeatedly, simulating
    # one video, with results alternating between a tracked detection, an
    # untracked one (id=None), no detection at all, and a raising call.
    tracked = _FakeResult(
        _FakeKeypoints(np.zeros((1, 17, 2), dtype=np.float32), np.ones((1, 17), dtype=np.float32)),
        _FakeBoxes(np.array([[0, 0, 10, 10]], dtype=np.float32), ids=np.array([3], dtype=np.float32)),
    )
    untracked = _FakeResult(
        _FakeKeypoints(np.zeros((1, 17, 2), dtype=np.float32), np.ones((1, 17), dtype=np.float32)),
        _FakeBoxes(np.array([[0, 0, 10, 10]], dtype=np.float32), ids=None),
    )
    no_detection = _FakeResult(
        _FakeKeypoints(np.zeros((0, 17, 2), dtype=np.float32), np.zeros((0, 17), dtype=np.float32)),
        _FakeBoxes(np.zeros((0, 4), dtype=np.float32), ids=None),
    )

    sequence = [tracked, no_detection, untracked, no_detection, tracked, "raise", no_detection]

    class _AlternatingModel:
        def __init__(self):
            self._i = 0

        def track(self, **kw):
            item = sequence[self._i]
            self._i += 1
            if item == "raise":
                raise TypeError("'NoneType' object is not subscriptable")
            return [item]

    extractor = _make_extractor_without_loading_weights()
    extractor._model = _AlternatingModel()

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    results = [extractor.extract(frame) for _ in sequence]

    track_ids_per_frame = [[p.track_id for p in people] for people in results]
    assert track_ids_per_frame == [[3], [], [-1], [], [3], [], []]


def test_consecutive_errors_increments_on_track_raising():
    class _RaisingModel:
        def track(self, **kw):
            raise TypeError("'NoneType' object is not subscriptable")

    extractor = _make_extractor_without_loading_weights()
    extractor._model = _RaisingModel()

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    assert extractor.consecutive_errors == 0
    extractor.extract(frame)
    assert extractor.consecutive_errors == 1
    extractor.extract(frame)
    assert extractor.consecutive_errors == 2


def test_consecutive_errors_resets_on_a_legitimate_empty_result():
    # A genuine "no detection this frame" (the normal case for these
    # clips) must NOT count as an error - only actual extractor failures
    # should be able to trip the consecutive-error abort in extract_video().
    no_detection = _FakeResult(
        _FakeKeypoints(np.zeros((0, 17, 2), dtype=np.float32), np.zeros((0, 17), dtype=np.float32)),
        _FakeBoxes(np.zeros((0, 4), dtype=np.float32), ids=None),
    )

    class _RaisingModel:
        def track(self, **kw):
            raise TypeError("boom")

    extractor = _make_extractor_without_loading_weights()
    extractor._model = _RaisingModel()
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    extractor.extract(frame)
    extractor.extract(frame)
    assert extractor.consecutive_errors == 2

    extractor._model = type("M", (), {"track": lambda self, **kw: [no_detection]})()
    extractor.extract(frame)
    assert extractor.consecutive_errors == 0


def test_reset_clears_consecutive_errors():
    class _RaisingModel:
        def track(self, **kw):
            raise TypeError("boom")

    extractor = _make_extractor_without_loading_weights()
    extractor._model = _RaisingModel()
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    extractor.extract(frame)
    extractor.extract(frame)
    assert extractor.consecutive_errors == 2

    extractor.reset()

    assert extractor.consecutive_errors == 0


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
