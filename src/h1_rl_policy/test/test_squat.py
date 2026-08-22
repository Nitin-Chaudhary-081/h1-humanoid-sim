"""Single-leg-squat env tests — pure pytest, no ROS.

Same conventions as test_rl.py: mujoco-dependent tests skip cleanly when
the lib is absent.
"""

import numpy as np
import pytest

try:
    import mujoco  # noqa: F401
    import h1_rl_policy.env_squat as squat_mod
    HAS_MUJOCO = True
except ImportError:
    HAS_MUJOCO = False


@pytest.mark.skipif(not HAS_MUJOCO, reason='mujoco not installed')
def test_dims_and_reset():
    env = squat_mod.H1SquatEnv()
    assert env.obs_dim == 12 and env.act_dim == 4
    obs0 = env.reset()
    assert obs0.shape == (12,)
    assert np.isfinite(obs0).all()


@pytest.mark.skipif(not HAS_MUJOCO, reason='mujoco not installed')
def test_masking():
    # Pure unit check of the mask helper (staticmethod).
    masked = squat_mod.H1SquatEnv._apply_leg_mask(
        np.array([1.0, 1.0, 1.0, 1.0]), 'left')
    assert np.allclose(masked, [1.0, 1.0, 0.0, 0.0])
    masked_r = squat_mod.H1SquatEnv._apply_leg_mask(
        np.array([1.0, 1.0, 1.0, 1.0]), 'right')
    assert np.allclose(masked_r, [0.0, 0.0, 1.0, 1.0])

    # Full env step must not raise and must return well-formed outputs.
    env = squat_mod.H1SquatEnv(leg='left')
    obs = env.reset()
    obs, reward, done, trunc, info = env.step(np.ones(env.act_dim) * 1.0)
    assert obs.shape == (12,)
    assert np.isfinite(obs).all()
    assert isinstance(reward, float)
    assert 'z' in info and 'phase' in info


@pytest.mark.skipif(not HAS_MUJOCO, reason='mujoco not installed')
def test_phase_transition():
    env = squat_mod.H1SquatEnv(down_steps=5)
    env.reset()
    _, _, _, _, info = env.step(np.zeros(env.act_dim))
    assert info['phase'] == 'down'
    for _ in range(5):
        _, _, _, _, info = env.step(np.zeros(env.act_dim))
    assert info['phase'] == 'up'


@pytest.mark.skipif(not HAS_MUJOCO, reason='mujoco not installed')
def test_set_difficulty_validation():
    env = squat_mod.H1SquatEnv()
    with pytest.raises(ValueError):
        env.set_difficulty(1.9)
    env.set_difficulty(0.6)
    assert env.target_depth == 0.6


@pytest.mark.skipif(not HAS_MUJOCO, reason='mujoco not installed')
def test_rollout_finite():
    env = squat_mod.H1SquatEnv()
    rng = np.random.default_rng(7)
    env.reset()
    for _ in range(30):
        obs, reward, done, trunc, info = env.step(
            rng.uniform(-1.0, 1.0, size=env.act_dim))
        assert np.isfinite(obs).all()
        assert np.isfinite(reward)
        if done or trunc:
            env.reset()
