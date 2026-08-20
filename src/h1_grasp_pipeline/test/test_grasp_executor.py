"""Pure unit tests for the GraspExecutor end-to-end sequence (no ROS).

The GraspExecutor wires perception -> GraspPipeline -> follower sender with
injected callables, so the full grasp flow is testable with a mock follower.

Run: cd /home/ubuntu/humanoid_sim_ws/src/h1_grasp_pipeline && PYTHONPATH=src python3 -m pytest test/test_grasp_executor.py -q
"""
import numpy as np
import pytest

from h1_grasp_pipeline.grasp_pipeline import (
    GraspPipeline,
    GraspExecutor,
    GraspOutcome,
    GraspOffsets,
    CameraToBaseTransform,
    MarkerDetection,
    create_default_camera_to_base,
    create_default_arm_joint_names,
)


def make_detection(marker_id, xyz=(0.5, 0.0, 0.5)):
    return MarkerDetection(
        marker_id=marker_id,
        position=np.array(xyz, dtype=np.float64),
        orientation=np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64),
        confidence=1.0,
    )


@pytest.fixture
def pipeline():
    return GraspPipeline(
        camera_to_base=create_default_camera_to_base(),
        arm_joint_names=create_default_arm_joint_names(),
        grasp_offsets=GraspOffsets(),
        target_marker_id=42,
    )


@pytest.fixture
def target_detection():
    return make_detection(42)


class TestGraspExecutorHappyPath:
    def test_full_flow_with_mock_follower(self, pipeline, target_detection):
        """Perception -> trajectory -> mock follower -> success."""
        sent = []
        captured_outcome = {}

        def mock_send(traj_dict):
            sent.append(traj_dict)
            return True, "mock follower OK"

        executor = GraspExecutor(pipeline, send_trajectory=mock_send, timeout_sec=1.0)
        outcome = executor.execute(
            detections_provider=lambda: [target_detection],
            target_marker_id=42,
            pregrasp_offset=0.15,
            grasp_depth=0.02,
        )

        assert outcome.success is True
        assert outcome.trajectory is not None
        assert len(sent) == 1
        # Executed trajectory returned to the caller matches what was sent
        assert sent[0] == outcome.trajectory

    def test_trajectory_structure_sent_to_follower(self, pipeline, target_detection):
        """The dict handed to the follower is a valid JointTrajectory dict."""
        sent = []

        def mock_send(traj_dict):
            sent.append(traj_dict)
            return True, "ok"

        executor = GraspExecutor(pipeline, send_trajectory=mock_send, timeout_sec=1.0)
        executor.execute(
            detections_provider=lambda: [target_detection],
            target_marker_id=42,
            pregrasp_offset=0.15,
            grasp_depth=0.02,
        )

        traj = sent[0]
        assert "joint_names" in traj
        assert "points" in traj
        assert len(traj["joint_names"]) == 4
        assert len(traj["points"]) == 3
        for p in traj["points"]:
            assert "time_from_start" in p
            assert "positions" in p
            assert len(p["positions"]) == 4

    def test_goal_offsets_applied_to_pipeline(self, pipeline, target_detection):
        """Goal offsets must override pipeline defaults before planning."""
        executor = GraspExecutor(pipeline, send_trajectory=None, timeout_sec=1.0)
        executor.execute(
            detections_provider=lambda: [target_detection],
            target_marker_id=42,
            pregrasp_offset=0.25,
            grasp_depth=0.05,
        )
        assert pipeline.grasp_offsets.approach_distance == 0.25
        assert pipeline.grasp_offsets.grasp_depth == 0.05

    def test_marker_id_applied_to_pipeline(self, pipeline, target_detection):
        executor = GraspExecutor(pipeline, send_trajectory=None, timeout_sec=1.0)
        executor.execute(
            detections_provider=lambda: [target_detection],
            target_marker_id=99,
            pregrasp_offset=0.15,
            grasp_depth=0.02,
        )
        assert pipeline.target_marker_id == 99

    def test_detections_arriving_late(self, pipeline):
        """Provider returns empty first, then target appears -> still succeeds."""
        sent = []
        calls = {"n": 0}

        def provider():
            calls["n"] += 1
            if calls["n"] < 3:
                return [make_detection(1)]
            return [make_detection(42)]

        executor = GraspExecutor(pipeline, send_trajectory=lambda t: (True, "ok"), timeout_sec=5.0)
        outcome = executor.execute(
            detections_provider=provider,
            target_marker_id=42,
            pregrasp_offset=0.15,
            grasp_depth=0.02,
        )
        assert outcome.success is True
        assert calls["n"] >= 3


class TestGraspExecutorFailures:
    def test_timeout_when_marker_never_appears(self, pipeline):
        """No target detection within timeout -> fail with timeout message."""
        executor = GraspExecutor(pipeline, send_trajectory=None, timeout_sec=0.05)
        outcome = executor.execute(
            detections_provider=lambda: [make_detection(1)],
            target_marker_id=42,
            pregrasp_offset=0.15,
            grasp_depth=0.02,
        )
        assert outcome.success is False
        assert outcome.trajectory is None
        assert "Timed out" in outcome.message
        assert "42" in outcome.message

    def test_no_perception_at_all_times_out(self, pipeline):
        executor = GraspExecutor(pipeline, send_trajectory=None, timeout_sec=0.05)
        outcome = executor.execute(
            detections_provider=lambda: None,
            target_marker_id=42,
            pregrasp_offset=0.15,
            grasp_depth=0.02,
        )
        assert outcome.success is False
        assert "Timed out" in outcome.message

    def test_follower_reports_failure(self, pipeline, target_detection):
        """Follower returns failure -> outcome failure with trajectory kept."""
        def mock_send(traj_dict):
            return False, "follower error_code=5"

        executor = GraspExecutor(pipeline, send_trajectory=mock_send, timeout_sec=1.0)
        outcome = executor.execute(
            detections_provider=lambda: [target_detection],
            target_marker_id=42,
            pregrasp_offset=0.15,
            grasp_depth=0.02,
        )
        assert outcome.success is False
        assert outcome.trajectory is not None  # executed trajectory still returned
        assert "error_code=5" in outcome.message

    def test_follower_raises_exception(self, pipeline, target_detection):
        def mock_send(traj_dict):
            raise RuntimeError("boom")

        executor = GraspExecutor(pipeline, send_trajectory=mock_send, timeout_sec=1.0)
        outcome = executor.execute(
            detections_provider=lambda: [target_detection],
            target_marker_id=42,
            pregrasp_offset=0.15,
            grasp_depth=0.02,
        )
        assert outcome.success is False
        assert "boom" in outcome.message

    def test_wrong_marker_id_times_out(self, pipeline, target_detection):
        """Target marker never detected (only other IDs) -> timeout."""
        executor = GraspExecutor(pipeline, send_trajectory=None, timeout_sec=0.05)
        outcome = executor.execute(
            detections_provider=lambda: [make_detection(7)],
            target_marker_id=42,
            pregrasp_offset=0.15,
            grasp_depth=0.02,
        )
        assert outcome.success is False
        assert "Timed out" in outcome.message


class TestGraspOutcome:
    def test_dataclass_fields(self):
        outcome = GraspOutcome(success=True, trajectory={"joint_names": []}, message="ok")
        assert outcome.success is True
        assert outcome.trajectory == {"joint_names": []}
        assert outcome.message == "ok"

    def test_failure_outcome(self):
        outcome = GraspOutcome(success=False, trajectory=None, message="nope")
        assert not outcome.success
        assert outcome.trajectory is None


class TestExecutorDefaults:
    def test_default_sender_succeeds(self, pipeline, target_detection):
        """Without an injected sender, the flow reports success (no-op)."""
        executor = GraspExecutor(pipeline, timeout_sec=1.0)
        outcome = executor.execute(
            detections_provider=lambda: [target_detection],
            target_marker_id=42,
            pregrasp_offset=0.15,
            grasp_depth=0.02,
        )
        assert outcome.success is True
        assert outcome.message == "sent"

    def test_injectable_clock_and_sleep(self, pipeline, target_detection):
        """_now/_sleep can be stubbed for deterministic timeout tests."""
        executor = GraspExecutor(pipeline, timeout_sec=1.0)
        now = {"t": 0.0}

        def fake_now():
            return now["t"]

        def fake_sleep(_dt):
            now["t"] += 10.0  # jump past deadline

        executor._now = fake_now
        executor._sleep = fake_sleep
        outcome = executor.execute(
            detections_provider=lambda: [make_detection(1)],  # never target
            target_marker_id=42,
            pregrasp_offset=0.15,
            grasp_depth=0.02,
        )
        assert outcome.success is False
        assert "Timed out" in outcome.message