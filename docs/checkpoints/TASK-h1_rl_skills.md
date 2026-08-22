# TASK-h1_rl_skills — Single-leg squats (L/R) + backflip training

**Date**: 2026-08-22 · **Status**: DONE · **Package**: `src/h1_rl_policy` extensions

## What was built
- `assets/h1_acro.xml`: acro variant of the proxy biped — torso_pitch range
  ±10 rad, gear-50 leg motors, lighter torso (7 kg), dedicated flip motor.
- `env_backflip.py` `H1BackflipEnv` (ACT_DIM=5: [hip_l,knee_l,hip_r,knee_r,
  flip]): cumulative signed-pitch tracking, shaped rotation reward (+10/step
  of fraction progress), landing bonus +20 when fraction≥1 AND upright AND
  z≥0.6; crash detection z<0.25.
- `env_squat.py` `H1SquatEnv(leg, target_depth, down_steps, pitch_limit=1.3)`:
  non-squat leg actions masked to zero; phase-profile reward where bending is
  positively rewarded during 'down' and unbending+height during 'up'; +10
  milestone for reaching ≥90% depth; pitch limit relaxed to 1.3 rad because a
  deep squat legitimately leans the torso.
- `train.py`: task registry (`stand|squat_left|squat_right|backflip`),
  progressive curriculum stages with warm-start carry-over, and a squat
  warm-start bias ([hips +0.6, knees −0.8]) that escapes the freeze local
  optimum.

## Bugs found & fixed while building (all silent failures before)
1. **MuJoCo angle units are DEGREES by default** — every joint range in both
   MJCFs was effectively ±1° (the robot was a rigid statue; "trained stand"
   had nothing to learn). Fix: `<compiler angle="radian"/>` in both assets.
   This invalidated the earlier stand policy → retrained honestly (return 211,
   history 25→211 in one ES iteration).
2. **Actuator order mismatch**: flip motor was first in XML but actions send
   it last — the "flip torque" was flexing a knee. Reordered actuators to
   match action layout `[hip_l,knee_l,hip_r,knee_r,flip]`.
3. **Scalar action bug in trainer**: `rollout_return` passed
   `policy.forward(obs)[0]` (a scalar!) so only hip_left was ever actuated
   during ALL previous training runs. Fixed to pass the full vector;
   `_apply_leg_mask` hardened with `np.atleast_1d`.

## Verification evidence
- Tests: package suite **19 passed / 1 correct skip**; full workspace suite
  **425/425 across 9 packages** (`run_all_tests.sh`, h1_rl_policy auto-counted).
- Behavioral checks (not just reward):
  - STAND: survives 150 steps upright (z=0.82, pitch=0.00) after retrain on
    unlocked physics.
  - SQUAT_LEFT/RIGHT: max knee flexion **1.47 / 1.49 rad** at target_depth 1.0
    through the full down→up profile without falling.
  - BACKFLIP: max rotation **105% of −2π**, `landed=True`, no crash.
- ONNX exports (checker-valid, numpy-vs-onnx max diff ≤1.2e−07):
  `models/h1_stand.onnx`, `h1_squat_left.onnx`, `h1_squat_right.onnx`
  (ACT=4), `h1_backflip.onnx` (ACT=5).

## Honest scope note
The backflip uses an explicit whole-body pitch motor (reduced-order acrobatics
template — same abstraction class as SLIP runners); a full free-joint H1-2
backflip needs GPU-scale RL and is out of scope for this 2 GB VPS.

## Next step
Optional: sim-to-sim transfer test loading these ONNX policies in Foxglove-
visible Gazebo demos; or extend curriculum depths beyond 1.0 rad.
