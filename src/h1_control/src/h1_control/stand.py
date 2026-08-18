"""Pure stand controller: holds the nominal H1-2 pose from config/stand.yaml.

No ROS imports — unit-testable.
"""

import os

import yaml

# Clamping bounds (rad). Tighter than URDF limits; enough for any sane pose
# and protects against NaN/garbage config values.
MIN_POS = -3.5
MAX_POS = 3.5


def load_yaml(path):
    """Load a YAML file as a plain dict (pure, no ROS)."""
    with open(path, "r") as f:
        return yaml.safe_load(f)


class StandController:
    """Holds the nominal standing pose; target_pose() returns clamped values.

    The pose is a {joint_name: radians} dict. Values are clamped to
    [MIN_POS, MAX_POS] so a bad config can never command a broken joint.
    """

    def __init__(self, pose):
        if not isinstance(pose, dict) or not pose:
            raise ValueError("stand pose must be a non-empty {joint: rad} dict")
        self._pose = {name: self._clamp(float(v)) for name, v in pose.items()}

    @staticmethod
    def _clamp(value):
        if value != value:  # NaN
            raise ValueError("stand pose contains NaN")
        return min(MAX_POS, max(MIN_POS, value))

    def target_pose(self):
        """Nominal standing pose as {joint_name: radians} (clamped)."""
        return dict(self._pose)

    @property
    def joints(self):
        return tuple(self._pose.keys())

    @classmethod
    def from_yaml(cls, path):
        """Build from a stand.yaml config file."""
        return cls(load_yaml(path))
