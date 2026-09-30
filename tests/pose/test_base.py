import numpy as np
import pytest

from app.detection.pose.base import PoseExtractor, PosePerson


def test_pose_extractor_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        PoseExtractor()


def test_pose_person_holds_expected_shapes():
    keypoints = np.zeros((17, 3), dtype=np.float32)
    person = PosePerson(track_id=3, keypoints=keypoints, bbox=[0, 0, 10, 10])
    assert person.track_id == 3
    assert person.keypoints.shape == (17, 3)
    assert person.bbox == [0, 0, 10, 10]
