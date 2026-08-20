"""Pure unit tests for demo-mode synthetic frame generation (no ROS, no cv2).

Run: cd /home/ubuntu/humanoid_sim_ws/src/h1_perception && PYTHONPATH=src python3 -m pytest test/test_demo.py -q
"""
import numpy as np
import pytest

from h1_perception.demo import (
    DemoDetection,
    DemoFrame,
    build_demo_detection,
    build_demo_frame,
    frame_to_detection_dicts,
)


class TestBuildDemoDetection:
    def test_default_identity_orientation(self):
        det = build_demo_detection(42, [0.5, 0.0, 0.5])
        assert det.marker_id == 42
        assert det.position == [0.5, 0.0, 0.5]
        assert det.orientation == [0.0, 0.0, 0.0, 1.0]
        assert det.confidence == 1.0

    def test_custom_orientation(self):
        det = build_demo_detection(7, [1.0, 2.0, 3.0], [0.0, 0.0, 0.7071, 0.7071], confidence=0.9)
        assert det.marker_id == 7
        assert det.position == [1.0, 2.0, 3.0]
        assert abs(det.orientation[2] - 0.7071) < 1e-3
        assert det.confidence == 0.9

    def test_wrong_position_length_raises(self):
        with pytest.raises(ValueError, match="pose_xyz"):
            build_demo_detection(42, [0.5, 0.0])

    def test_wrong_orientation_length_raises(self):
        with pytest.raises(ValueError, match="orientation_xyzw"):
            build_demo_detection(42, [0.5, 0.0, 0.5], [0.0, 0.0, 0.0])

    def test_non_unit_orientation_raises(self):
        with pytest.raises(ValueError, match="unit quaternion"):
            build_demo_detection(42, [0.5, 0.0, 0.5], [1.0, 0.0, 0.0, 1.0])

    def test_converts_to_float(self):
        det = build_demo_detection(1, [1, 2, 3])
        assert det.position == [1.0, 2.0, 3.0]
        assert isinstance(det.position[0], float)

    def test_marker_id_int_cast(self):
        det = build_demo_detection(42.7, [0.0, 0.0, 1.0])
        assert det.marker_id == 42


class TestBuildDemoFrame:
    def test_single_detection(self):
        frame = build_demo_frame(42, [0.5, 0.0, 0.5])
        assert frame.frame_id == "camera_link"
        assert len(frame.detections) == 1
        assert frame.detections[0].marker_id == 42
        assert frame.detections[0].position == [0.5, 0.0, 0.5]

    def test_custom_frame_id_and_stamp(self):
        frame = build_demo_frame(42, [0.5, 0.0, 0.5], frame_id="h1_cam", stamp_nanosec=123456789)
        assert frame.frame_id == "h1_cam"
        assert frame.stamp_nanosec == 123456789

    def test_identity_orientation_default(self):
        frame = build_demo_frame(42, [0.5, 0.0, 0.5])
        np.testing.assert_allclose(frame.detections[0].orientation, [0.0, 0.0, 0.0, 1.0])

    def test_invalid_pose_raises(self):
        with pytest.raises(ValueError):
            build_demo_frame(42, [0.5, 0.0])

    def test_is_dataclass(self):
        frame = build_demo_frame(42, [0.5, 0.0, 0.5])
        assert isinstance(frame, DemoFrame)
        assert isinstance(frame.detections[0], DemoDetection)


class TestFrameToDetectionDicts:
    def test_dict_structure(self):
        frame = build_demo_frame(42, [0.5, 0.0, 0.5], confidence=0.8)
        dicts = frame_to_detection_dicts(frame)
        assert len(dicts) == 1
        d = dicts[0]
        assert set(d.keys()) == {"marker_id", "position", "orientation", "confidence"}
        assert d["marker_id"] == 42
        assert d["position"] == [0.5, 0.0, 0.5]
        assert d["orientation"] == [0.0, 0.0, 0.0, 1.0]
        assert d["confidence"] == 0.8

    def test_empty_frame(self):
        assert frame_to_detection_dicts(DemoFrame()) == []

    def test_dict_contract_matches_marker_detection_kwargs(self):
        """The dicts must expose the exact kwargs GraspPipeline.MarkerDetection
        requires (marker_id, position, orientation, confidence)."""
        frame = build_demo_frame(42, [0.5, 0.0, 0.5], confidence=0.8)
        d = frame_to_detection_dicts(frame)[0]

        # Simulate MarkerDetection construction contract (pure, no ROS import)
        marker_id = d["marker_id"]
        position = np.array(d["position"])
        orientation = np.array(d["orientation"])
        confidence = d["confidence"]

        assert marker_id == 42
        assert position.shape == (3,)
        assert orientation.shape == (4,)
        np.testing.assert_allclose(position, [0.5, 0.0, 0.5])
        np.testing.assert_allclose(orientation, [0.0, 0.0, 0.0, 1.0])
        assert 0.0 <= confidence <= 1.0