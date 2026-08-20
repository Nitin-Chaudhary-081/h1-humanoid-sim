# TASK-h1_control_m2 — M2 Stand / Walk / Stop + race fix + IMU ankle compensation

**Status**: DONE (verified live in sim) · **Date**: 2026-08-18 → 2026-08-19 · **Main thread**: commits `5b41db0`, `be01aef`, `8828550`, `ce7f844`

## Summary

`h1_control` delivers the M2 command layer: a single `/h1/command` action server
(Stand / Walk / Stop) that drives the heinz H1-2 via `/h1/<joint>/cmd_pos`,
plus the LocoMuJoCo walk-replay motion player and IMU-based ankle compensation.
All three actions verified live against the headless sim with short (0.3 m) goals.

## What was built

| Component | Detail |
|---|---|
| `stand.py` — `StandController` | Nominal standing pose from `config/stand.yaml` (17 joints incl. `torso_joint`), clamps to ±3.5 rad, NaN rejection |
| `motion_player.py` — `JointMap`, `MotionReplay`, `SineGait` | LocoMuJoCo 19-DOF → H1-2 joint map (real npz DOF names, 15/19 mapped, unmapped → zero), 100 Hz resample with linear interp, `speed_multiplier`; sine-gait fallback (1.6 Hz, legs π out of phase); `make_motion_player` factory |
| `imu_comp.py` — `ImuAnkleCompensation` | EMA-smoothed IMU pitch/roll → ankle pitch / hip roll offsets applied in `_compute_pose`; extends balance window of the open-loop replay |
| `estop.py` — `EstopGate` | `allows(estop_active)`, `should_abort(...)`; `/estop` subscribe → abort + freeze |
| `control_server.py` | Action server `/h1/command` (RobotCommand), 17× `/h1/<joint>/cmd_pos` @ 50 Hz, `/h1/control_state` @ 10 Hz, `/h1/odometry` (best_effort) vx integration per goal, coroutine execute_callback, **MultiThreadedExecutor** |
| `data/walk.npz` | 7.2 MB LocoMuJoCo `UnitreeH1/walk.npz` (35 198 frames @ 40 Hz, qpos 26 = 7 root + 19 joints), default playback window 30 s, `speed_multiplier=0.5` |

## Key fixes (gotchas hit in sim)

1. **Single-threaded executor hung walks** — `rclpy.spin` ran the long execute_callback inline, blocking timers (cmd/state publishers went silent, completion check never ran). Fixed with `MultiThreadedExecutor` (`be01aef`). Recorded in AGENTS.md.
2. **WALK goal/mode race** — player resources were created *after* flipping mode; an unguarded timer tick could kill the server (RCLError at `succeed()`). Fix: initialize player before flipping mode + try/except around goal outcome (`be01aef`). Recorded in AGENTS.md.
3. **joint_map.yaml keys did not match the npz** — rewritten to actual `joint_names` in the file.
4. **Sign conventions** (hip/knee/ankle pitch) assumed identical between heinz URDF and LocoMuJoCo MJCF — pinned by tests; verified live via 0.3 m walk.
5. **Cancel = reject** (CancelResponse.REJECT) — estop is the abort path; busy goals rejected, not preempted.
6. **rclpy Jazzy execute_callback** — async generators unsupported (`await_or_execute`); implemented as plain coroutine with explicit feedback/succeed/abort.

## Verification evidence

```
# Unit tests (48) — package dir, PYTHONPATH=src
$ PYTHONPATH=src python3 -m pytest test/ -q
........................................  [100%]
48 passed in 5.61s
```

Live (headless sim, direct Python action client `scripts/test_control.py`):
- STAND PASS — joints hold stand pose via `/h1/<joint>/cmd_pos`
- WALK 0.3 m PASS — "walked 0.30 of 0.30 m" (goal from `/h1/odometry` vx integration)
- STOP PASS — both idle and mid-walk
- Full sequence clean: Stand → Stop → Stand → Walk → Stop (commit `be01aef`, re-verified on fresh upright sim)
- `/h1/control_state` publishes MODE/STATUS at 10 Hz; `/h1/control_markers` (viz) shows status text + WALK arrow
- With IMU compensation active (commit `8828550`): 0.3 m walk PASS, compensation keeps robot upright past the plain-replay fall point

## Files changed

- `src/h1_control/src/h1_control/stand.py` (new)
- `src/h1_control/src/h1_control/motion_player.py` (new)
- `src/h1_control/src/h1_control/imu_comp.py` (new)
- `src/h1_control/src/h1_control/estop.py` (new)
- `src/h1_control/src/h1_control/control_server.py` (rewritten)
- `src/h1_control/config/stand.yaml` (added `torso_joint`), `config/joint_map.yaml` (real npz keys)
- `src/h1_control/data/walk.npz` (new, committed)
- `src/h1_control/setup.py`, `package.xml` (data_files, exec deps)
- `src/h1_control/test/test_pure.py` (32) + `test/test_imu_comp.py` (16) — 48 total
- `scripts/run_server.py`, `scripts/start_control_server.sh`, `scripts/test_control.py` (live-verification helpers)

## Known limits

- Open-loop mocap replay loses balance after ~0.3 m (no balance controller) — robot falls; restart sim to re-upright. Long goals (≥1 m) exceed wall-timeouts at sim RTF 5–15 %. Walk verification uses 0.3 m goals.
- Wrists un-actuated (vendor) — 21 actuated joints, not 27.

## Next steps

1. M3: `RosActionExecutor` in h1_llm_agent drives `/h1/command` (done — see TASK-h1_llm_agent_m3).
2. M5: perception/grasp nodes must respect control mode (freeze legs while planning arms).
3. M8 final validation: re-run full Stand/Walk/Stop sequence + smoke gate on a fresh sim.
