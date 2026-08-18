"""Pure motion replay for the H1-2: LocoMuJoCo .npz mocap + sine-gait fallback.

No ROS imports — unit-testable. All sample_at(t) methods are periodic.
"""

import os

import numpy as np
import yaml

# LocoMuJoCo 19-DOF keys (qpos cols 7..25 after root xyz+quat).
LOCO_MUJOCO_KEYS = (
    "hip_rotation_l", "hip_adduction_l", "hip_flexion_l", "knee_angle_l", "ankle_angle_l",
    "hip_rotation_r", "hip_adduction_r", "hip_flexion_r", "knee_angle_r", "ankle_angle_r",
    "back_bkz",
    "l_arm_shy", "l_arm_shx", "l_arm_shz", "left_elbow",
    "r_arm_shy", "r_arm_shx", "r_arm_shz", "right_elbow",
)


def load_yaml(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)


class JointMap:
    """Maps LocoMuJoCo DOF keys -> H1-2 actuated joint names.

    apply() maps present keys; unmapped source keys contribute zero (the
    H1-2 joints they would drive are either un-actuated or intentionally
    frozen). Output always covers the full target joint set.
    """

    def __init__(self, mapping, target_joints=None):
        self._map = dict(mapping)
        # Target joint set defaults to the mapped names (union of values).
        self._targets = tuple(target_joints) if target_joints is not None else tuple(
            sorted(set(self._map.values())))
        unknown = [v for v in self._map.values() if v not in self._targets]
        if unknown:
            raise ValueError("mapping targets unknown joints: %s" % sorted(set(unknown)))

    @classmethod
    def from_yaml(cls, path, target_joints=None):
        return cls(load_yaml(path), target_joints=target_joints)

    @property
    def mapping(self):
        return dict(self._map)

    @property
    def targets(self):
        return self._targets

    def apply(self, values):
        """Map a {loco_key: rad} dict to {h1_joint: rad}; unmapped -> 0."""
        out = dict.fromkeys(self._targets, 0.0)
        for key, val in values.items():
            target = self._map.get(key)
            if target is not None:
                out[target] = float(val)
        return out

    def zero_pose(self):
        return dict.fromkeys(self._targets, 0.0)


class MotionReplay:
    """Periodic, time-indexed playback of a joint trajectory.

    The source (LocoMuJoCo .npz qpos, ~40 Hz) is resampled to `playback_rate`
    Hz at load time; sample_at(t) linearly interpolates on that grid and
    loops. speed_multiplier slows playback (0.5 = half speed).

    `duration` is the source duration (post-window) at nominal speed; the
    real-time loop period is duration / speed_multiplier.
    """

    def __init__(self, track, keys, duration, joint_map, playback_rate=100.0,
                 speed_multiplier=1.0, window_s=None, start_s=0.0):
        # track: (N, n_dof) array aligned with `keys`
        track = np.asarray(track, dtype=np.float64)
        if track.ndim != 2 or track.shape[1] != len(keys):
            raise ValueError("track shape %s != (N, %d)" % (track.shape, len(keys)))
        if duration <= 0.0:
            raise ValueError("duration must be > 0")
        if window_s is not None and window_s <= 0.0:
            raise ValueError("window_s must be > 0")
        if playback_rate <= 0.0 or speed_multiplier <= 0.0:
            raise ValueError("playback_rate and speed_multiplier must be > 0")

        self._keys = list(keys)
        self._joint_map = joint_map
        self._playback_rate = float(playback_rate)
        self._speed_multiplier = float(speed_multiplier)

        src_dt = duration / float(track.shape[0])
        self._duration = float(duration)
        self._start_s = float(start_s)
        if window_s is not None:
            self._duration = min(self._duration, float(window_s))
        n_src = min(track.shape[0],
                    int(round(self._duration / src_dt)) + 1)
        src_t = np.arange(n_src) * src_dt
        src_vals = track[:n_src]

        n_rs = int(np.ceil(self._duration * self._playback_rate))
        grid = np.arange(n_rs + 1) / self._playback_rate
        grid = np.clip(grid, 0.0, self._duration)
        self._grid = grid
        # Resample each joint column onto the fixed playback-rate grid.
        self._rs = np.column_stack([np.interp(grid, src_t, src_vals[:, i])
                                    for i in range(src_vals.shape[1])])
        self._n = len(grid)

    @classmethod
    def from_npz(cls, npz_path, joint_map, playback_rate=100.0, speed_multiplier=1.0,
                 window_s=None):
        """Load a LocoMuJoCo mocap .npz (qpos Nx(7+n), joint_names, frequency)."""
        with np.load(npz_path, allow_pickle=True) as d:
            qpos = np.asarray(d["qpos"], dtype=np.float64)
            names = list(d["joint_names"])
            if names and names[0] == "root":
                names = names[1:]
            freq = float(d["frequency"])
            if qpos.shape[1] != 7 + len(names):
                raise ValueError("qpos cols %d != 7 root + %d joints"
                                 % (qpos.shape[1], len(names)))
            track = qpos[:, 7:]
            duration = qpos.shape[0] / freq
        return cls(track, names, duration, joint_map,
                   playback_rate=playback_rate, speed_multiplier=speed_multiplier,
                   window_s=window_s)

    @property
    def duration(self):
        """Track duration (s) at nominal speed."""
        return self._duration

    @property
    def realtime_duration(self):
        """One loop period (s) at the configured speed_multiplier."""
        return self._duration / self._speed_multiplier

    @property
    def playback_rate(self):
        return self._playback_rate

    @property
    def keys(self):
        return tuple(self._keys)

    def sample_at(self, t, speed_multiplier=None):
        """Periodic sample: returns {h1_joint: rad} for time t (seconds)."""
        mult = self._speed_multiplier if speed_multiplier is None else speed_multiplier
        tt = (float(t) * mult - self._start_s) % self._duration
        if tt < 0.0:
            tt += self._duration
        frac = tt * self._playback_rate
        i = int(frac)
        if i >= self._n - 1:
            return self._joint_map.apply(dict(zip(self._keys, self._rs[-1])))
        f = frac - i
        row = (1.0 - f) * self._rs[i] + f * self._rs[i + 1]
        return self._joint_map.apply(dict(zip(self._keys, row)))


class SineGait:
    """Open-loop sine gait fallback (used only if no mocap npz is available).

    Sinusoids on hip/knee/ankle pitch, legs 180 deg out of phase.

    NOTE: this is a naive demo gait — it falls after a few steps (community
    consensus: simple open-loop humanoid gaits are not stable in sim).
    """

    # (joint, amplitude rad, offset rad); left leg phase 0, right leg phase pi.
    LEFT_GAIT = (
        ("left_hip_pitch_joint", 0.30, 0.0),
        ("left_knee_joint", 0.35, -0.35),
        ("left_ankle_pitch_joint", 0.25, 0.0),
    )
    RIGHT_GAIT = (
        ("right_hip_pitch_joint", 0.30, 0.0),
        ("right_knee_joint", 0.35, -0.35),
        ("right_ankle_pitch_joint", 0.25, 0.0),
    )
    FREQUENCY_HZ = 1.6
    AMP_MAX = 0.4  # guard for tests

    def __init__(self, joint_map, frequency_hz=None, speed_multiplier=1.0):
        self._joint_map = joint_map
        self._freq = float(frequency_hz or self.FREQUENCY_HZ)
        self._speed_multiplier = float(speed_multiplier)
        self._period = 1.0 / self._freq

    @property
    def duration(self):
        """One full gait cycle (s) at nominal speed."""
        return self._period

    @property
    def realtime_duration(self):
        return self._period / self._speed_multiplier

    def sample_at(self, t, speed_multiplier=None):
        mult = self._speed_multiplier if speed_multiplier is None else speed_multiplier
        phase = 2.0 * np.pi * self._freq * float(t) * mult
        out = self._joint_map.zero_pose()
        for joint, amp, off in self.LEFT_GAIT:
            out[joint] = amp * np.sin(phase) + off
        for joint, amp, off in self.RIGHT_GAIT:
            out[joint] = amp * np.sin(phase + np.pi) + off
        return out


def make_motion_player(npz_path, joint_map, playback_rate=100.0,
                       speed_multiplier=1.0, window_s=None):
    """MotionReplay from npz, or SineGait fallback if the file is unusable.

    Returns (player, source_name) where source_name is 'npz:<file>' or 'sine'.
    """
    if npz_path and os.path.isfile(npz_path):
        try:
            player = MotionReplay.from_npz(
                npz_path, joint_map,
                playback_rate=playback_rate, speed_multiplier=speed_multiplier,
                window_s=window_s)
            return player, "npz:%s" % os.path.basename(npz_path)
        except Exception:
            pass  # fall back to sine gait; caller may log
    return (SineGait(joint_map, speed_multiplier=speed_multiplier), "sine")
