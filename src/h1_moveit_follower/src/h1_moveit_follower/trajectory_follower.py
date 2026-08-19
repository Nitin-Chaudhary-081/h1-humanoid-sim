"""Pure logic module for MoveIt2 trajectory following.

This module contains the TrajectoryFollower class which handles trajectory
interpolation and joint name mapping without any ROS dependencies.
"""

from typing import Dict, Generator, List, Optional, Tuple
from dataclasses import dataclass
import math


@dataclass
class TrajectoryPoint:
    """Represents a single interpolated trajectory point."""
    timestamp: float
    positions: Dict[str, float]


class TrajectoryFollower:
    """Pure logic class for following joint trajectories.

    Maps MoveIt2 joint names to H1 cmd_pos topics, interpolates trajectory
    points at a fixed rate, and handles arm-only trajectories with legs frozen.
    """

    def __init__(
        self,
        control_hz: float = 50.0,
        arm_joint_names: Optional[List[str]] = None,
        stand_pose_fallback: Optional[Dict[str, float]] = None,
        trajectory_tolerance: Optional[Dict[str, float]] = None,
    ):
        """Initialize the trajectory follower.

        Args:
            control_hz: Control frequency in Hz for interpolation.
            arm_joint_names: List of arm joint names to control.
            stand_pose_fallback: Default stand pose for joints not in trajectory.
            trajectory_tolerance: Position/velocity tolerances for success checking.
        """
        self.control_hz = control_hz
        self.dt = 1.0 / control_hz
        self.arm_joint_names = arm_joint_names or [
            "left_shoulder_pitch_joint",
            "left_elbow_joint",
            "right_shoulder_pitch_joint",
            "right_elbow_joint",
        ]
        self.stand_pose_fallback = stand_pose_fallback or {
            "left_shoulder_pitch_joint": 0.0,
            "left_elbow_joint": 0.0,
            "right_shoulder_pitch_joint": 0.0,
            "right_elbow_joint": 0.0,
        }
        self.trajectory_tolerance = trajectory_tolerance or {
            "position": 0.01,
            "velocity": 0.1,
        }

        # Validate arm joint names are in stand pose fallback
        for joint in self.arm_joint_names:
            if joint not in self.stand_pose_fallback:
                raise ValueError(f"Arm joint '{joint}' not in stand_pose_fallback")

    def follow(
        self,
        trajectory_points: List[Dict],
        joint_names: List[str],
        stand_pose_dict: Optional[Dict[str, float]] = None,
    ) -> Generator[Tuple[float, Dict[str, float]], None, None]:
        """Follow a trajectory and yield interpolated joint positions.

        Args:
            trajectory_points: List of trajectory points, each with 'time_from_start',
                               'positions', and optionally 'velocities'.
            joint_names: Joint names in the trajectory (MoveIt2 order).
            stand_pose_dict: Optional override for stand pose (legs frozen).

        Yields:
            Tuples of (timestamp, {joint_name: position}) for each control cycle.

        Raises:
            ValueError: If trajectory is invalid or joint names don't match.
        """
        if not trajectory_points:
            return

        if not joint_names:
            raise ValueError("Joint names list cannot be empty")

        # Build mapping from trajectory joint index to arm joint name
        traj_to_arm_idx = {}
        for i, name in enumerate(joint_names):
            if name in self.arm_joint_names:
                traj_to_arm_idx[i] = name

        if not traj_to_arm_idx:
            raise ValueError("No arm joints found in trajectory joint names")

        # Merge stand pose with fallback
        stand_pose = self.stand_pose_fallback.copy()
        if stand_pose_dict:
            stand_pose.update(stand_pose_dict)

        # Extract trajectory times and positions
        times = [p["time_from_start"] for p in trajectory_points]
        positions = [p["positions"] for p in trajectory_points]
        velocities = [p.get("velocities", [0.0] * len(joint_names)) for p in trajectory_points]

        total_duration = times[-1]
        num_steps = int(math.ceil(total_duration * self.control_hz))

        for step in range(num_steps + 1):
            t = step * self.dt
            if t > total_duration:
                t = total_duration

            # Find segment for interpolation
            seg_idx = 0
            while seg_idx < len(times) - 1 and times[seg_idx + 1] < t:
                seg_idx += 1

            # Interpolate position for each arm joint in trajectory
            cmd_positions = {}

            if seg_idx >= len(times) - 1:
                # At or past the end - use final positions
                for traj_idx, arm_joint in traj_to_arm_idx.items():
                    cmd_positions[arm_joint] = positions[-1][traj_idx]
            else:
                # Linear interpolation between segment points
                t0 = times[seg_idx]
                t1 = times[seg_idx + 1]
                alpha = (t - t0) / (t1 - t0) if t1 > t0 else 0.0

                for traj_idx, arm_joint in traj_to_arm_idx.items():
                    p0 = positions[seg_idx][traj_idx]
                    p1 = positions[seg_idx + 1][traj_idx]
                    cmd_positions[arm_joint] = p0 + alpha * (p1 - p0)

            # Add frozen joints from stand pose (legs, torso, etc.)
            for joint, pos in stand_pose.items():
                if joint not in cmd_positions:
                    cmd_positions[joint] = pos

            yield (t, cmd_positions)

    def check_trajectory_tolerance(
        self,
        current_positions: Dict[str, float],
        target_positions: Dict[str, float],
        current_velocities: Optional[Dict[str, float]] = None,
    ) -> bool:
        """Check if current state is within trajectory tolerance of target.

        Args:
            current_positions: Current joint positions.
            target_positions: Target joint positions from trajectory end.
            current_velocities: Optional current joint velocities.

        Returns:
            True if within tolerance, False otherwise.
        """
        pos_tol = self.trajectory_tolerance.get("position", 0.01)
        vel_tol = self.trajectory_tolerance.get("velocity", 0.1)

        for joint, target in target_positions.items():
            if joint not in current_positions:
                return False
            if abs(current_positions[joint] - target) > pos_tol:
                return False

        if current_velocities:
            for joint, vel in current_velocities.items():
                if joint in target_positions and abs(vel) > vel_tol:
                    return False

        return True

    def filter_arm_joints(
        self,
        joint_names: List[str],
        positions: List[float],
    ) -> Dict[str, float]:
        """Filter trajectory data to only include arm joints.

        Args:
            joint_names: Full joint names from trajectory.
            positions: Corresponding positions.

        Returns:
            Dict mapping arm joint names to positions.
        """
        result = {}
        for i, name in enumerate(joint_names):
            if name in self.arm_joint_names:
                result[name] = positions[i]
        return result

    def validate_joint_names(self, joint_names: List[str]) -> Tuple[bool, List[str]]:
        """Validate that trajectory joint names contain known arm joints.

        Args:
            joint_names: Joint names from trajectory goal.

        Returns:
            Tuple of (is_valid, unknown_joints_list).
        """
        unknown = []
        has_arm_joint = False
        for name in joint_names:
            if name in self.arm_joint_names:
                has_arm_joint = True
            elif name not in self.stand_pose_fallback:
                unknown.append(name)

        return (has_arm_joint and len(unknown) == 0, unknown)


def create_trajectory_point(
    time_from_start: float,
    positions: List[float],
    velocities: Optional[List[float]] = None,
    accelerations: Optional[List[float]] = None,
) -> Dict:
    """Helper to create a trajectory point dict for testing.

    Args:
        time_from_start: Time from trajectory start in seconds.
        positions: Joint positions.
        velocities: Optional joint velocities.
        accelerations: Optional joint accelerations.

    Returns:
        Dictionary representing a trajectory point.
    """
    point = {"time_from_start": time_from_start, "positions": positions}
    if velocities is not None:
        point["velocities"] = velocities
    if accelerations is not None:
        point["accelerations"] = accelerations
    return point