"""Tiny MLP policy in pure numpy (no torch)."""

import numpy as np


class PureNumPyPolicy:

    def __init__(self, obs_dim, act_dim, hidden_dim=16, act_scale=1.0,
                 seed=0):
        self.obs_dim = int(obs_dim)
        self.act_dim = int(act_dim)
        self.hidden_dim = int(hidden_dim)
        self.act_scale = float(act_scale)
        rng = np.random.default_rng(seed)
        self.W1 = rng.normal(0.0, 0.1, (self.obs_dim, self.hidden_dim))
        self.b1 = np.zeros(self.hidden_dim)
        self.W2 = rng.normal(0.0, 0.1, (self.hidden_dim, self.act_dim))
        self.b2 = np.zeros(self.act_dim)

    def forward(self, obs):
        obs = np.asarray(obs, dtype=np.float64)
        single = obs.ndim == 1
        if single:
            obs = obs[None, :]
        h = np.tanh(obs @ self.W1 + self.b1)
        act = np.tanh(h @ self.W2 + self.b2) * self.act_scale
        return act.astype(np.float32)[0] if single else act.astype(np.float32)

    def param_count(self):
        return (self.W1.size + self.b1.size + self.W2.size + self.b2.size)

    def get_params(self):
        return np.concatenate([self.W1.ravel(), self.b1,
                               self.W2.ravel(), self.b2])

    def set_params(self, flat):
        flat = np.asarray(flat, dtype=np.float64)
        i = 0
        n = self.W1.size
        self.W1 = flat[i:i + n].reshape(self.W1.shape)
        i += n
        n = self.b1.size
        self.b1 = flat[i:i + n].copy()
        i += n
        n = self.W2.size
        self.W2 = flat[i:i + n].reshape(self.W2.shape)
        i += n
        n = self.b2.size
        self.b2 = flat[i:i + n].copy()
