"""Population (keep-best) search trainer — pure numpy, CPU friendly."""

import numpy as np

from .policy import PureNumPyPolicy


def rollout_return(env, policy, max_steps):
    obs = env.reset()
    total = 0.0
    for _ in range(max_steps):
        action = policy.forward(obs)[0]
        obs, reward, done, _trunc, _info = env.step(action)
        total += reward
        if done:
            break
    return total


def evaluate(env_factory, params, base_policy, max_steps):
    base_policy.set_params(params)
    return rollout_return(env_factory(), base_policy, max_steps)


def train_policy(env_factory, seed=0, iters=10, pop_size=6, sigma=0.1,
                 episode_steps=200):
    """Greedy keep-best population search.

    Returns dict(best_params, best_return, history) where best_return is
    non-decreasing across iterations.
    """
    env_probe = env_factory()
    policy = PureNumPyPolicy(env_probe.obs_dim, env_probe.act_dim,
                             hidden_dim=16, act_scale=1.0, seed=seed)

    best_params = policy.get_params()
    best_return = evaluate(env_factory, best_params, policy, episode_steps)
    history = [best_return]
    rng = np.random.default_rng(seed + 1)

    for _ in range(iters):
        dim = best_params.shape[0]
        candidates = best_params[None, :] + sigma * rng.normal(
            0.0, 1.0, (pop_size, dim))
        returns = [evaluate(env_factory, c, policy, episode_steps)
                   for c in candidates]
        idx = int(np.argmax(returns))
        if returns[idx] > best_return:
            best_return = float(returns[idx])
            best_params = candidates[idx].copy()
        history.append(best_return)

    return {'best_params': best_params, 'best_return': best_return,
            'history': history}


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog='rl_train',
                                description='Train H1 stand policy (numpy ES)')
    p.add_argument('--iters', type=int, default=10)
    p.add_argument('--pop-size', type=int, default=6)
    p.add_argument('--sigma', type=float, default=0.1)
    p.add_argument('--episode-steps', type=int, default=200)
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--save', default=None,
                   help='np.save path for best params')
    args = p.parse_args(argv)

    from .env_h1 import H1StandEnv
    result = train_policy(
        H1StandEnv, seed=args.seed, iters=args.iters,
        pop_size=args.pop_size, sigma=args.sigma,
        episode_steps=args.episode_steps)
    print('best_return: %.4f' % result['best_return'])
    print('history: %s' % ['%.3f' % v for v in result['history']])
    if args.save:
        np.save(args.save, result['best_params'])
        print('saved params -> %s' % args.save)
    return 0
