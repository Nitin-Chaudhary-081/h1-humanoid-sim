"""Population (keep-best) search trainer — pure numpy, CPU friendly."""

import numpy as np

from .policy import PureNumPyPolicy


def rollout_return(env, policy, max_steps):
    obs = env.reset()
    total = 0.0
    for _ in range(max_steps):
        # forward(single_obs) returns shape (act_dim,) -- use directly.
        action = policy.forward(obs)
        obs, reward, done, _trunc, _info = env.step(action)
        total += reward
        if done:
            break
    return total


def evaluate(env_factory, params, base_policy, max_steps):
    base_policy.set_params(params)
    return rollout_return(env_factory(), base_policy, max_steps)


def train_policy(env_factory, seed=0, iters=10, pop_size=6, sigma=0.1,
                 episode_steps=200, warm_start=None):
    """Greedy keep-best population search.

    Returns dict(best_params, best_return, history) where best_return is
    non-decreasing across iterations.
    """
    env_probe = env_factory()
    policy = PureNumPyPolicy(env_probe.obs_dim, env_probe.act_dim,
                             hidden_dim=16, act_scale=1.0, seed=seed)

    if warm_start is not None:
        policy.set_params(warm_start)
    best_params = warm_start if warm_start is not None else policy.get_params()
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


# Task registry: task name -> (env_factory(difficulty), curriculum stages).
# difficulty=None means single-stage. Stages go easy -> hard and the best
# params warm-start each next stage (progressive training).
def _make_tasks():
    from .env_h1 import H1StandEnv
    from .env_squat import H1SquatEnv
    from .env_backflip import H1BackflipEnv
    return {
        'stand': (
            lambda d: H1StandEnv(),
            [None],
        ),
        'squat_left': (
            lambda d: H1SquatEnv(leg='left', target_depth=d),
            [0.4, 0.7, 1.0],
        ),
        'squat_right': (
            lambda d: H1SquatEnv(leg='right', target_depth=d),
            [0.4, 0.7, 1.0],
        ),
        'backflip': (
            lambda d: H1BackflipEnv(target_rotation=d),
            [-1.5707963267948966, -3.141592653589793, -6.283185307179586],
        ),
    }


def _squat_warm_start(leg):
    """Seed policy biased toward the squat coordination (hips forward,
    knees bend) so ES starts near meaningful behavior instead of the
    freeze local optimum."""
    from .policy import PureNumPyPolicy
    p = PureNumPyPolicy(12, 4, hidden_dim=16, seed=7)
    # Output layout: [hip_l, knee_l, hip_r, knee_r]
    p.b2[:] = [0.6, -0.8, 0.6, -0.8]
    return p.get_params()


def train_task(task, seed=0, iters_per_stage=3, pop_size=6, sigma=0.1,
               episode_steps=150):
    """Progressive-curriculum training for a named task.

    Returns dict(task, best_params, best_return, history) where history is
    non-decreasing within each stage and best params warm-start each stage.
    """
    tasks = _make_tasks()
    if task not in tasks:
        raise ValueError('unknown task %r; choose from %s'
                         % (task, sorted(tasks)))
    factory, stages = tasks[task]
    warm = _squat_warm_start(task) if task.startswith('squat_') else None
    best_params, best_return = None, None
    history = []
    for i, stage in enumerate(stages):
        result = train_policy(
            lambda: factory(stage), seed=seed, iters=iters_per_stage,
            pop_size=pop_size, sigma=sigma, episode_steps=episode_steps,
            warm_start=(warm if i == 0 else best_params))
        best_params = result['best_params']
        best_return = result['best_return']
        history.append({'stage': stage, 'return': best_return,
                        'curve': result['history']})
        print('stage %-8s -> best_return %.3f' %
              (str(stage), best_return))
    return {'task': task, 'best_params': best_params,
            'best_return': best_return, 'history': history}


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(
        prog='rl_train',
        description='Train H1 proxy policies: stand / squats / backflip')
    p.add_argument('--task', default='stand',
                   choices=['stand', 'squat_left', 'squat_right', 'backflip'])
    p.add_argument('--iters', type=int, default=10,
                   help='iterations per curriculum stage (ignored for stand '
                        'single stage: total iters)')
    p.add_argument('--pop-size', type=int, default=6)
    p.add_argument('--sigma', type=float, default=0.1)
    p.add_argument('--episode-steps', type=int, default=150)
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--save', default=None,
                   help='np.save path for best params')
    args = p.parse_args(argv)

    if args.task == 'stand':
        from .env_h1 import H1StandEnv
        result = train_policy(
            H1StandEnv, seed=args.seed, iters=args.iters,
            pop_size=args.pop_size, sigma=args.sigma,
            episode_steps=args.episode_steps)
        print('history: %s' % ['%.3f' % v for v in result['history']])
    else:
        result = train_task(args.task, seed=args.seed,
                            iters_per_stage=args.iters,
                            pop_size=args.pop_size, sigma=args.sigma,
                            episode_steps=args.episode_steps)
    print('best_return: %.4f' % result['best_return'])
    if args.save:
        np.save(args.save, result['best_params'])
        print('saved params -> %s' % args.save)
    return 0
