"""MuJoCo backflip env for the H1 planar-biped proxy.

Mirrors env_h1.H1StandEnv's API but scores continuous signed pitch rotation
instead of upright standing: the agent must complete a full backward flip
(target_rotation = -2*pi). Uses assets/h1_acro.xml (unbounded-ish torso_pitch
range, stronger motors, lighter torso). Pure logic, no ROS; mujoco is
imported lazily so the rest of the package stays usable without it.
"""

import math
import os

OBS_DIM = 12
ACT_DIM = 5  # 4 leg motors + torso_pitch flip motor

CONTROL_FRAMESKIP = 5
STAND_HEIGHT = 0.82
CRASH_HEIGHT = 0.25
LANDING_PITCH_TOL = 0.5
LANDING_MIN_Z = 0.6


def default_model_path():
    # env_backflip.py lives at <pkg>/src/h1_rl_policy/ -> package root is 3 up.
    # In colcon build/symlink trees the source-relative path can break, so try
    # candidates: source tree first, then installed share dir.
    pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    candidates = [
        os.path.join(pkg_root, 'assets', 'h1_acro.xml'),
        os.path.join(pkg_root, '..', 'h1_rl_policy', 'assets', 'h1_acro.xml'),
        '/home/ubuntu/humanoid_sim_ws/src/h1_rl_policy/assets/h1_acro.xml',
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return candidates[0]


class H1BackflipEnv:

    def __init__(self, model_path=None, episode_steps=150,
                 target_rotation=-6.283185307179586):
        import mujoco
        self._mujoco = mujoco
        self.model = mujoco.MjModel.from_xml_path(
            model_path or default_model_path())
        self.data = mujoco.MjData(self.model)
        self.obs_dim = OBS_DIM
        self.act_dim = ACT_DIM
        self.episode_steps = int(episode_steps)
        self.target_rotation = float(target_rotation)
        self._cum_pitch = 0.0
        self._last_pitch = 0.0
        self._step_count = 0
        self._landed = False

    def reset(self, seed=None, options=None):
        mujoco = self._mujoco
        mujoco.mj_resetData(self.model, self.data)
        # Torso slide joint: qpos is world height (body frame starts at 0).
        self.data.qpos[0] = STAND_HEIGHT
        self._cum_pitch = 0.0
        self._last_pitch = float(self.data.qpos[1])
        self._step_count = 0
        self._landed = False
        mujoco.mj_forward(self.model, self.data)
        return self._obs()

    @staticmethod
    def _wrap(angle):
        # Wrap to [-pi, pi].
        return (angle + math.pi) % (2.0 * math.pi) - math.pi

    def _obs(self):
        import numpy as np
        return np.concatenate([self.data.qpos, self.data.qvel]).astype(
            np.float32)

    def step(self, action):
        import numpy as np
        mujoco = self._mujoco
        action = np.clip(np.asarray(action, dtype=np.float64), -1.0, 1.0)
        self.data.ctrl[:] = action
        for _ in range(CONTROL_FRAMESKIP):
            mujoco.mj_step(self.model, self.data)

        z = float(self.data.qpos[0])
        pitch = float(self.data.qpos[1])

        # Cumulative signed pitch: integrate wrapped deltas so multi-turn
        # rotation accumulates instead of saturating at +-pi.
        fraction_prev = self._cum_pitch / self.target_rotation
        delta = self._wrap(pitch - self._last_pitch)
        self._cum_pitch += delta
        self._last_pitch = pitch
        fraction_now = self._cum_pitch / self.target_rotation

        reward = float(10.0 * (fraction_now - fraction_prev)
                       + 0.01 * max(0.0, z - 0.5)
                       - 0.005 * float(np.sum(action ** 2)))

        self._step_count += 1
        done = False

        pitch_wrapped = self._wrap(pitch)
        if (not self._landed and fraction_now >= 1.0
                and abs(pitch_wrapped) < LANDING_PITCH_TOL
                and z >= LANDING_MIN_Z):
            self._landed = True
            reward += 20.0
            done = True

        crashed = z < CRASH_HEIGHT
        if crashed:
            done = True
            reward -= 5.0

        info = {'z': z, 'pitch': pitch, 'fraction': fraction_now,
                'cum_pitch': self._cum_pitch, 'landed': self._landed}
        trunc = self._step_count >= self.episode_steps
        return self._obs(), reward, bool(done), bool(trunc), info
