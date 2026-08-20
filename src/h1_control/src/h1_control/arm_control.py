"""Pure arm-control blend logic for the H1-2 (no ROS imports).

M5: the MoveIt2 follower / grasp pipeline publishes external arm joint
commands on /h1/<arm_joint>/cmd_pos at 50 Hz. This module decides whether
those commands override the motion-plan value for the four actuated arm
joints (shoulder_pitch + elbow per arm; wrists are un-actuated in heinz).

The decision is a thin, unit-testable function; the control_server node only
glues it to the /h1/<joint>/cmd_pos pub/sub graph.
"""

import math

# The four actuated arm joints (AGENTS.md M5; wrists are un-actuated).
ARM_JOINT_NAMES = (
    "left_shoulder_pitch_joint",
    "left_elbow_joint",
    "right_shoulder_pitch_joint",
    "right_elbow_joint",
)

# Default H1-2 joint limits (rad) per arm joint, from the URDF.
# shoulder_pitch and elbow both range [-2.5, 2.5]. Configurable via the
# `arm_joint_limits` param (values may be lists or tuples of [lo, hi]).
DEFAULT_ARM_LIMITS = {
    "left_shoulder_pitch_joint": [-2.5, 2.5],
    "left_elbow_joint": [-2.5, 2.5],
    "right_shoulder_pitch_joint": [-2.5, 2.5],
    "right_elbow_joint": [-2.5, 2.5],
}

# A received arm command is "recent" (external control active) for this many
# seconds after it arrives; afterwards the motion-plan value resumes.
ARM_CMD_FRESH_WINDOW_S = 0.5


def blend_arm_joint(plan_pos, arm_cmd, enabled, recent):
    """Pick the position to command for one arm joint.

    Args:
        plan_pos: value from the motion plan / stand pose (rad).
        arm_cmd: latest external arm command in rad, or None if none received.
        enabled: arm_control_enabled param value.
        recent: True if a valid arm command arrived within the recency window.

    Returns:
        arm_cmd when external arm control is enabled, recent and a command is
        available; plan_pos otherwise (disabled, stale, or never commanded).
    """
    if not enabled or not recent or arm_cmd is None:
        return plan_pos
    return arm_cmd


def clamp_arm_joint(value, limits):
    """Clamp a joint value to its (lo, hi) limits in radians.

    Non-finite values (NaN/inf) are rejected: returns None so the caller can
    ignore the sample rather than command garbage into a joint.
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    lo, hi = limits
    return min(hi, max(lo, value))


def is_arm_cmd_recent(now_s, stamp_s, window_s=ARM_CMD_FRESH_WINDOW_S):
    """True if a command stamped stamp_s is still fresh at now_s.

    A missing stamp (None) is never recent. A slightly future stamp (clock
    edge) is treated as recent rather than rejected.
    """
    if stamp_s is None:
        return False
    delta = now_s - stamp_s
    if delta < 0.0:
        delta = 0.0
    return delta <= window_s
