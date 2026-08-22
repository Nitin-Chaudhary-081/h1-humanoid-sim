"""MuJoCo single-leg-squat env for the H1 planar-biped proxy.

Mirrors H1StandEnv's API exactly (obs 12 / act 4, gym-style 5-tuple step).
One leg squats to a target knee-flexion depth and stands back up; the other
leg's actions are forced to zero every control step.

Pure logic, no ROS. mujoco is imported lazily in __init__ so the rest of
the package stays usable without it.
"""

import numpy as np

from h1_rl_policy.env_h1 import (
    OBS_DIM,
    ACT_DIM,
    FALL_HEIGHT,
    PITCH_LIMIT,
    CONTROL_FRAMESKIP,
    STAND_HEIGHT,
    default_model_path,
)

__all__ = ['H1SquatEnv', 'OBS_DIM', 'ACT_DIM']

# Leg joint order: [hip_left, knee_left, hip_right, knee_right].
_LEFT_IDX = (0, 1)
_RIGHT_IDX = (2, 3)


class H1SquatEnv:

    def __init__(self, leg='left', target_depth=0.8, down_steps=60,
                 pitch_limit=1.3,
                 episode_steps=150):
        import mujoco
        self._mujoco = mujoco
        self.model = mujoco.MjModel.from_xml_path(default_model_path())
        self.data = mujoco.MjData(self.model)
        self.obs_dim = OBS_DIM
        self.act_dim = ACT_DIM
        self.leg = leg
        self.set_difficulty(target_depth)
        self.down_steps = int(down_steps)
        self.episode_steps = int(episode_steps)
        # Knee slide-free hinge index in qpos: torso_z(0), torso_pitch(1),
        # hip_left(2), knee_left(3), hip_right(4), knee_right(5) -> ctrl idx.
        self.knee_index = 1 if leg == 'left' else 3
        self.step_count = 0
        # Deep-squat posture legitimately leans the torso; allow more
        # lean than the stand env before calling it a fall.
        self.pitch_limit = float(pitch_limit)

    @staticmethod
    def _apply_leg_mask(action, leg):
        """Zero the non-squat leg entries of a clipped action array."""
        masked = np.atleast_1d(np.array(action, dtype=np.float64, copy=True))
        dead = _RIGHT_IDX if leg == 'left' else _LEFT_IDX
        masked[list(dead)] = 0.0
        return masked

    def set_difficulty(self, target_depth):
        """Curriculum hook: set target knee-flexion depth (radians)."""
        if not 0.2 <= float(target_depth) <= 1.3:
            raise ValueError(
                f'target_depth must be within [0.2, 1.3], got {target_depth}')
        self.target_depth = float(target_depth)

    def reset(self, seed=None):
        mujoco = self._mujoco
        del seed  # Deterministic env; kept for API parity.
        mujoco.mj_resetData(self.model, self.data)
        # Torso slide joint: qpos is world height (body frame starts at 0).
        self.data.qpos[0] = STAND_HEIGHT
        mujoco.mj_forward(self.model, self.data)
        self.step_count = 0
        return self._obs()

    def _obs(self):
        return np.concatenate([self.data.qpos, self.data.qvel]).astype(
            np.float32)

    def step(self, action):
        mujoco = self._mujoco
        action = np.clip(np.asarray(action, dtype=np.float64), -1.0, 1.0)
        scaled_action = self._apply_leg_mask(action, self.leg)
        self.data.ctrl[:] = scaled_action
        for _ in range(CONTROL_FRAMESKIP):
            mujoco.mj_step(self.model, self.data)
        self.step_count += 1

        z = float(self.data.qpos[0])
        pitch = float(self.data.qpos[1])
        knee_flex = -float(self.data.qpos[2 + self.knee_index])
        self._peak_flex = max(getattr(self, '_peak_flex', 0.0), knee_flex)

        phase = 'down' if self.step_count < self.down_steps else 'up'
        reward_bonus = 0.0
        if phase == 'down':
            # Bending toward target earns positive reward (freezing earns ~0,
            # so squatting is strictly better than standing still).
            r_track = 2.0 * min(knee_flex / self.target_depth, 1.0)
        else:
            # Stand back up tall; unbending earns positive reward.
            r_track = (2.0 * max(0.0, 1.0 - knee_flex / self.target_depth)
                       + 2.0 * max(0.0, z - 0.5))
            if (self.step_count == self.down_steps + 1
                    and self._peak_flex >= 0.9 * self.target_depth):
                reward_bonus = 10.0  # reached full depth: milestone bonus
            else:
                reward_bonus = 0.0

        upright = max(0.0, float(np.cos(pitch)))
        reward = float(upright + 0.5 * r_track + reward_bonus
                       - 0.01 * float(np.sum(scaled_action ** 2)))

        fell = z < FALL_HEIGHT or abs(pitch) > self.pitch_limit
        trunc = self.step_count >= self.episode_steps
        if fell:
            # Penalize collapse so shorter episodes score strictly worse.
            reward -= 5.0
        info = {'z': z, 'pitch': pitch, 'knee_flex': knee_flex,
                'phase': phase}
        return self._obs(), reward, bool(fell), bool(trunc), info
