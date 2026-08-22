"""Backflip env tests — pure pytest, no ROS.

mujoco-dependent tests skip cleanly when the lib is absent
(same pattern as test_rl.py's HAS_MUJOCO guard).
"""

import numpy as np
import pytest

try:
    import mujoco  # noqa: F401
    import h1_rl_policy.env_backflip as env_mod
    HAS_MUJOCO = True
except ImportError:
    HAS_MUJOCO = False


@pytest.mark.skipif(not HAS_MUJOCO, reason='mujoco not installed')
def test_dims_and_reset():
    from h1_rl_policy.env_backflip import ACT_DIM, OBS_DIM
    assert OBS_DIM == 12 and ACT_DIM == 5
    env = env_mod.H1BackflipEnv()
    obs = env.reset(seed=0)
    assert obs.shape == (env.obs_dim,) == (OBS_DIM,)
    assert env.act_dim == ACT_DIM
    assert np.isfinite(obs).all()


@pytest.mark.skipif(not HAS_MUJOCO, reason='mujoco not installed')
def test_rollout_finite_50_steps():
    env = env_mod.H1BackflipEnv()
    rng = np.random.default_rng(7)
    env.reset(seed=0)
    for _ in range(50):
        obs, reward, done, trunc, info = env.step(
            rng.uniform(-1.0, 1.0, size=env.act_dim))
        assert np.isfinite(obs).all()
        assert np.isfinite(reward)
        assert all(np.isfinite(v) for v in
                   [info['z'], info['pitch'], info['fraction'],
                    info['cum_pitch']])
        if done or trunc:
            env.reset(seed=0)


@pytest.mark.skipif(not HAS_MUJOCO, reason='mujoco not installed')
def test_pitch_accumulates_signed():
    env = env_mod.H1BackflipEnv()
    env.reset(seed=0)
    action = np.array([1.0, -1.0, -1.0, 1.0, 1.0])
    info = {}
    for _ in range(80):
        _obs, _r, _done, _trunc, info = env.step(action)
    # Wrapped-qpos alone would saturate near +-pi and lose turns; the
    # cumulative integrator must track raw signed rotation past that.
    assert abs(info['cum_pitch']) > 0.5, \
        f'cum_pitch={info["cum_pitch"]:.4f} after 80 steps'


@pytest.mark.skipif(not HAS_MUJOCO, reason='mujoco not installed')
def test_crash_detection():
    env = env_mod.H1BackflipEnv()
    env.reset(seed=0)
    action = np.array([1.0, 1.0, -1.0, -1.0, -1.0])
    done = trunc = False
    for _ in range(400):
        _obs, _r, done, trunc, _info = env.step(action)
        if done or trunc:
            break
    assert done or trunc, 'episode neither crashed nor truncated'


@pytest.mark.skipif(not HAS_MUJOCO, reason='mujoco not installed')
def test_target_rotation_param():
    env = env_mod.H1BackflipEnv(target_rotation=-3.14)
    assert env.target_rotation == -3.14
    env.reset(seed=0)
    action = np.array([1.0, -1.0, -1.0, 1.0, -1.0])
    info = {}
    for _ in range(80):
        _obs, _r, _d, _t, info = env.step(action)
    assert info['cum_pitch'] != 0.0
    # fraction must be exactly cum/target: with target < 0 the sign flips
    # relative to the raw cumulative pitch.
    assert abs(info['fraction'] * env.target_rotation
               - info['cum_pitch']) < 1e-9
    assert (info['cum_pitch'] > 0) != (info['fraction'] > 0) or \
        abs(info['cum_pitch']) < 1e-12
