"""Pure IMU ankle compensation for the H1-2 (no ROS imports).

M2.3: the open-loop LocoMuJoCo mocap walk drifts in torso pitch/roll and
falls after ~0.3 m. This module computes ankle-joint corrections opposite
to the measured torso drift so the commanded pose keeps the CoP under the
CoM.

Conventions (verified against the ros2_heinz H1-2 URDF and the bridged
pelvis IMU):
  - IMU pitch (deg): positive = torso leaning forward (rotation about +Y).
  - IMU roll  (deg): positive = torso leaning toward +Y (robot's left).
  - Ankle pitch joints (axis +Y): positive = plantarflexion (toes down),
    which presses the CoP forward -> counteracts a forward lean. The H1
    ankle-strategy correction for a forward lean is therefore +kp*pitch
    on both left and right ankle pitch.
  - Ankle roll joints (axis +X): positive = +Y edge down. For a lean
    toward +Y the CoP must move toward +Y, so BOTH ankle rolls get
    +kr*roll (left foot: lateral edge down; right foot: medial edge down).
  - Same sign on both feet for both pitch and roll because the ankle
    frames are not mirrored in the URDF (identical axes for L/R).

Quaternion -> pitch/roll formula (sensor_msgs convention x,y,z,w):
    pitch = asin(2*(w*y - z*x))
    roll  = atan2(2*(w*x + y*z), 1 - 2*(x^2 + y^2))

All corrections are returned in radians, keyed by joint name.
"""

import math

DEFAULT_ANKLE_PITCH_JOINTS = ("left_ankle_pitch_joint", "right_ankle_pitch_joint")
DEFAULT_ANKLE_ROLL_JOINTS = ("left_ankle_roll_joint", "right_ankle_roll_joint")


def _normalized(x, y, z, w):
    """Unit quaternion (x,y,z,w); all zeros if the input has no norm."""
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm == 0.0 or not math.isfinite(norm):
        return 0.0, 0.0, 0.0, 0.0
    return x / norm, y / norm, z / norm, w / norm


def quaternion_to_pitch_roll_deg(x, y, z, w):
    """Map an (x,y,z,w) quaternion to (pitch_deg, roll_deg).

    Zero-norm / non-finite quaternion -> (0.0, 0.0).
    """
    x, y, z, w = _normalized(x, y, z, w)
    if x == 0.0 and y == 0.0 and z == 0.0 and w == 0.0:
        return 0.0, 0.0
    pitch = math.asin(max(-1.0, min(1.0, 2.0 * (w * y - z * x))))
    roll = math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    return math.degrees(pitch), math.degrees(roll)


class ImuAnkleCompensation:
    """EMA-smoothed, deadzoned, clamped ankle correction from torso drift.

    update(pitch_deg, roll_deg) returns {joint_name: correction_rad} for
    the four ankle joints only. With zero drift the output is all zeros.
    """

    def __init__(self, kp_pitch_rad_per_deg=0.02, kp_roll_rad_per_deg=0.02,
                 deadzone_deg=1.0, clamp_pitch_deg=8.0, clamp_roll_deg=6.0,
                 ema_alpha=0.1, pitch_joints=DEFAULT_ANKLE_PITCH_JOINTS,
                 roll_joints=DEFAULT_ANKLE_ROLL_JOINTS):
        if kp_pitch_rad_per_deg < 0.0 or kp_roll_rad_per_deg < 0.0:
            raise ValueError("kp gains must be >= 0")
        if deadzone_deg < 0.0 or clamp_pitch_deg < 0.0 or clamp_roll_deg < 0.0:
            raise ValueError("deadzone/clamp must be >= 0")
        if not 0.0 < ema_alpha <= 1.0:
            raise ValueError("ema_alpha must be in (0, 1]")
        if len(pitch_joints) != len(set(pitch_joints)) or \
                len(roll_joints) != len(set(roll_joints)):
            raise ValueError("joint lists must not contain duplicates")
        if set(pitch_joints) & set(roll_joints):
            raise ValueError("pitch and roll joint sets must be disjoint")
        self._kp_pitch = float(kp_pitch_rad_per_deg)
        self._kp_roll = float(kp_roll_rad_per_deg)
        self._deadzone = float(deadzone_deg)
        self._clamp_pitch = float(clamp_pitch_deg)
        self._clamp_roll = float(clamp_roll_deg)
        self._alpha = float(ema_alpha)
        self._pitch_joints = tuple(pitch_joints)
        self._roll_joints = tuple(roll_joints)
        self._smooth_pitch = 0.0
        self._smooth_roll = 0.0

    def reset(self):
        """Forget the EMA state (e.g. on a new motion goal)."""
        self._smooth_pitch = 0.0
        self._smooth_roll = 0.0

    @staticmethod
    def _ema(old, new, alpha):
        if old is None:
            return float(new)
        return alpha * float(new) + (1.0 - alpha) * old

    def _correction(self, drift_deg, kp, clamp_deg):
        if abs(drift_deg) < self._deadzone:
            return 0.0
        corr = kp * drift_deg
        lim = kp * clamp_deg
        return max(-lim, min(lim, corr))

    def update(self, pitch_deg, roll_deg):
        """Feed a fresh torso measurement; returns {joint: rad} corrections.

        The drift is EMA-smoothed before the deadzone/clamp logic so that
        per-step oscillations are filtered while slow drift accumulates.
        """
        self._smooth_pitch = self._ema(self._smooth_pitch, pitch_deg,
                                       self._alpha)
        self._smooth_roll = self._ema(self._smooth_roll, roll_deg, self._alpha)
        pitch_corr = self._correction(self._smooth_pitch, self._kp_pitch,
                                      self._clamp_pitch)
        roll_corr = self._correction(self._smooth_roll, self._kp_roll,
                                     self._clamp_roll)
        out = {}
        for name in self._pitch_joints:
            out[name] = pitch_corr
        for name in self._roll_joints:
            out[name] = roll_corr
        return out

    @property
    def smoothed_pitch_deg(self):
        return self._smooth_pitch

    @property
    def smoothed_roll_deg(self):
        return self._smooth_roll
