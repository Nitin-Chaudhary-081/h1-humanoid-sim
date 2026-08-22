# TASK-h1_rl_m8 — M8 RL policy (MuJoCo CPU) + ONNX export + M9 quantize hook

**Date**: 2026-08-22 · **Status**: DONE · **Package**: `src/h1_rl_policy` (ament_python)

## Design decisions
- **No torch**: 2 GB RAM box → pure-numpy MLP policy + greedy keep-best
  population search (`train_policy`), no training framework.
- **Planar-biped proxy MJCF** (`assets/h1_stand.xml`) instead of full H1-2:
  torso_z slide + torso_pitch hinge + 2 legs × (hip, knee) = 6 joints,
  OBS_DIM=12 (qpos+qvel), ACT_DIM=4 motor actuators. Standing task:
  upright + height bonus − control cost − fall penalty (−5).
- **ONNX without torch**: hand-built GraphProto via `onnx.helper`
  (Gemm→Tanh→Gemm→Tanh→Mul(scale), opset 13, ir_version 8).
- **M9 hook**: `quantize_m9.quantize_model` wraps
  `onnxruntime.quantization.quantize_dynamic`; clean
  `QuantizeUnavailableError` when onnxruntime absent.

## Gotchas found (documented for posterity)
1. MuJoCo slide-joint qpos is *displacement*, not world pos — spawning a body
   at `pos="0 0 0.82"` with slide z still starts qpos=0 → instant fall.
   Fix: body at origin, reset() sets `qpos[0]=STAND_HEIGHT`.
2. `pip install --user mujoco` silently pulled numpy 2.5.2 into user site,
   shadowing system numpy 1.26 and breaking system scipy binaries
   (`ValueError: numpy.dtype size changed`) — broke h1_grasp_pipeline test
   collection until `pip uninstall numpy`. Always check `pip show numpy`
   after --user installs on this box.

## Verification evidence
- Unit tests: `PYTHONPATH=src python3 -m pytest test/ -q` → **9 passed, 1 skipped**
  (skip = quantize roundtrip before onnxruntime was installed; after install it
  runs green — verified manually below). Suite total via `run_all_tests.sh`
  auto-discovery: **415 passed / 0 failed across 9 packages**.
- Physics sanity: zero-action = stable stand at z=0.82 (reward 1.41/step);
  actuated rollout diverges from passive rollout (>1e-3 max obs delta).
- Training run: `rl_train --iters 12 --pop-size 6 --episode-steps 200`
  → best_return **281.98**, history monotone non-decreasing
  (281.96 → … → 281.98); params saved to `models/h1_policy_params.npy`.
- Export: `models/h1_policy.onnx` (1381 B); `onnx.checker.check_model` OK;
  ReferenceEvaluator output matches numpy forward within **9e-9**.
- Quantize (M9): fp32 → int8 dynamic OK; int8 model loads in onnxruntime
  CPUExecutionProvider and produces sane actions
  ([0.1734, −0.2789, 0.2486, 0.0042] @ zero obs). Note: tiny models grow
  slightly after quantization (1381 → 1937 B) — quantization overhead
  dominates below ~10 KB; benefits appear on real-scale policies.

## Files
- New package: setup.py, package.xml, resource/, assets/h1_stand.xml,
  config/rl_policy.yaml, src/h1_rl_policy/{env_h1,policy,train,export_onnx,quantize_m9}.py,
  test/test_rl.py
- Artifacts: models/h1_policy.onnx, models/h1_policy_params.npy

## Next step
M9 dashboard: serve ONNX inference behind Lambda URL once admin IAM unblocks
the function deploy; swap proxy biped for full H1-2 MJCF when GPU box available.
