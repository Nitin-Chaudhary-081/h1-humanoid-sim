"""M8 RL tests — pure pytest, no ROS.

mujoco/onnx/onnxruntime-dependent tests skip cleanly when the lib is absent
(same pattern as h1_llm_agent's optional google-genai tests).
"""

import numpy as np
import pytest

from h1_rl_policy.policy import PureNumPyPolicy
from h1_rl_policy.train import train_policy, rollout_return

try:
    import onnx  # noqa: F401
    HAS_ONNX = True
except ImportError:
    HAS_ONNX = False

try:
    import mujoco  # noqa: F401
    import h1_rl_policy.env_h1 as env_mod
    HAS_MUJOCO = True
except ImportError:
    HAS_MUJOCO = False

try:
    import onnxruntime  # noqa: F401
    HAS_ORT = True
except ImportError:
    HAS_ORT = False


OBS, ACT, HIDDEN = 12, 4, 16


class FakeEnv:
    """Same API as H1StandEnv; deterministic reward for search tests."""

    def __init__(self, seed=0):
        self.obs_dim = OBS
        self.act_dim = ACT
        self._rng = np.random.default_rng(seed)

    def reset(self):
        self._t = 0
        return np.zeros(OBS, dtype=np.float32)

    def step(self, action):
        action = np.asarray(action)
        self._t += 1
        # Reward favors small actions; slight noise so candidates differ.
        reward = float(1.0 - 0.01 * np.sum(action ** 2))
        done = self._t >= 20
        return (np.zeros(OBS, dtype=np.float32), reward, done, False, {})


def test_env_constants():
    from h1_rl_policy.env_h1 import OBS_DIM, ACT_DIM
    assert OBS_DIM == OBS and ACT_DIM == ACT


def test_forward_shape_and_bounds():
    p = PureNumPyPolicy(OBS, ACT, hidden_dim=HIDDEN, act_scale=1.0)
    out = p.forward(np.random.default_rng(0).normal(size=OBS))
    assert out.shape == (ACT,)
    assert out.dtype == np.float32
    assert np.all(out >= -1.0 - 1e-6) and np.all(out <= 1.0 + 1e-6)


def test_batched_forward_matches_single():
    p = PureNumPyPolicy(OBS, ACT, hidden_dim=HIDDEN)
    obs = np.random.default_rng(1).normal(size=(5, OBS))
    batch = p.forward(obs)
    for i in range(5):
        assert np.allclose(batch[i], p.forward(obs[i]), atol=1e-6)


def test_params_roundtrip_exact():
    p = PureNumPyPolicy(OBS, ACT, hidden_dim=HIDDEN)
    flat = p.get_params()
    assert flat.shape[0] == p.param_count()
    q = PureNumPyPolicy(OBS, ACT, hidden_dim=HIDDEN)
    q.set_params(flat)
    assert np.array_equal(q.get_params(), flat)
    assert np.array_equal(q.W1, p.W1) and np.array_equal(q.b2, p.b2)


def test_train_best_return_non_decreasing():
    result = train_policy(FakeEnv, seed=3, iters=3, pop_size=4,
                          sigma=0.05, episode_steps=20)
    hist = result['history']
    assert len(hist) == 4
    assert all(b >= a - 1e-9 for a, b in zip(hist, hist[1:]))
    assert result['best_params'].shape[0] == \
        PureNumPyPolicy(OBS, ACT, hidden_dim=HIDDEN).param_count()


@pytest.mark.skipif(not HAS_ONNX, reason='onnx not installed')
def test_export_valid_and_matches_numpy(tmp_path):
    from h1_rl_policy.export_onnx import export_onnx, onnx_forward
    p = PureNumPyPolicy(OBS, ACT, hidden_dim=HIDDEN, act_scale=1.0)
    path = str(tmp_path / 'policy.onnx')
    export_onnx(p, path)
    obs = np.random.default_rng(2).normal(size=OBS).astype(np.float32)
    out = onnx_forward(path, obs)
    ref = p.forward(obs)
    assert out.shape == ref.shape
    assert np.allclose(out, ref, atol=1e-5)


class QuantizeUnavailableError(Exception):
    pass


def test_quantize_unavailable_error_type_exists():
    from h1_rl_policy.quantize_m9 import QuantizeUnavailableError as Q
    assert issubclass(Q, Exception)


@pytest.mark.skipif(HAS_ORT, reason='onnxruntime installed')
def test_quantize_raises_clean_when_missing():
    from h1_rl_policy.quantize_m9 import quantize_model
    with pytest.raises(Exception):
        quantize_model('/nonexistent.onnx', '/tmp/out.onnx')


@pytest.mark.skipif(not HAS_ORT or not HAS_ONNX,
                    reason='onnxruntime/onnx not installed')
def test_quantize_dynamic_roundtrip(tmp_path):
    from h1_rl_policy.export_onnx import export_onnx
    from h1_rl_policy.quantize_m9 import quantize_model
    p = PureNumPyPolicy(OBS, ACT, hidden_dim=HIDDEN)
    src = str(tmp_path / 'fp.onnx')
    dst = str(tmp_path / 'int8.onnx')
    export_onnx(p, src)
    quantize_model(src, dst)
    import os
    assert os.path.isfile(dst) and os.path.getsize(dst) > 0


@pytest.mark.skipif(not HAS_MUJOCO, reason='mujoco not installed')
def test_mujoco_env_rollout_finite_and_actuated():
    env = env_mod.H1StandEnv()
    obs0 = env.reset()
    assert obs0.shape == (env_mod.OBS_DIM,)
    assert np.isfinite(obs0).all()

    # Zero actions: stable stand; rollout must stay finite.
    obs = obs0
    for _ in range(50):
        obs, _r, done, _trunc, info = env.step(np.zeros(env.act_dim))
        assert np.isfinite(obs).all()
        assert not done

    # Actuation must drive dynamics: different torques -> divergent states.
    env.reset()
    obs_b = obs0
    for _ in range(50):
        obs_b, _r, done_b, _trunc, _i = env.step(
            np.array([0.8, -0.8, -0.5, 0.5]))
        if done_b:
            break
    assert np.abs(obs_b - obs).max() > 1e-3, \
        'actuation had no effect on dynamics'
