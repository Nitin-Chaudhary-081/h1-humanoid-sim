"""MuJoCo standing env for the H1 planar-biped proxy.

Pure logic, no ROS. mujoco is imported lazily so the rest of the package
(policy/train/export) stays usable without it.

State layout (tree order): torso_z, torso_pitch, hip_l, knee_l, hip_r, knee_r
-> OBS_DIM = 6 qpos + 6 qvel = 12.  ACT_DIM = 4 (hip/knee motors, both legs).
"""

import os

OBS_DIM = 12
ACT_DIM = 4

FALL_HEIGHT = 0.45
PITCH_LIMIT = 1.0
CONTROL_FRAMESKIP = 5
STAND_HEIGHT = 0.82


def default_model_path():
    # env_h1.py lives at <pkg>/src/h1_rl_policy/ -> package root is 3 up.
    pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    return os.path.join(pkg_root, 'assets', 'h1_stand.xml')


class H1StandEnv:

    def __init__(self, model_path=None):
        import mujoco
        self._mujoco = mujoco
        self.model = mujoco.MjModel.from_xml_path(model_path or default_model_path())
        self.data = mujoco.MjData(self.model)
        self.obs_dim = OBS_DIM
        self.act_dim = ACT_DIM

    def reset(self, seed=None, options=None):
        mujoco = self._mujoco
        mujoco.mj_resetData(self.model, self.data)
        # Torso slide joint: qpos is world height (body frame starts at 0).
        self.data.qpos[0] = STAND_HEIGHT
        mujoco.mj_forward(self.model, self.data)
        return self._obs()

    def _obs(self):
        import numpy as np
        return np.concatenate([self.data.qpos, self.data.qvel]).astype(np.float32)

    def step(self, action):
        import numpy as np
        mujoco = self._mujoco
        action = np.clip(np.asarray(action, dtype=np.float64), -1.0, 1.0)
        self.data.ctrl[:] = action
        for _ in range(CONTROL_FRAMESKIP):
            mujoco.mj_step(self.model, self.data)
        z = float(self.data.qpos[0])
        pitch = float(self.data.qpos[1])
        upright = max(0.0, np.cos(pitch))
        reward = float(upright + 0.5 * min(1.0, max(z, 0.0))
                       - 0.01 * float(np.sum(action ** 2)))
        fell = z < FALL_HEIGHT or abs(pitch) > PITCH_LIMIT
        if fell:
            # Penalize collapse so shorter episodes score strictly worse.
            reward -= 5.0
        return self._obs(), reward, bool(fell), False, {'z': z, 'pitch': pitch}
