# TASK: h1_control — M2 locomotion controller (stand + motion replay + actions)

**Agent:** h1_control workstream · **Branch:** wt-h1_control · **Date:** 2026-08-18
**Status:** DONE (pure-logic layer complete, 32/32 tests pass; sim integration is the main thread's job)

## Changed files (only under src/h1_control/ + this doc)

| File | Change |
|---|---|
| `src/h1_control/src/h1_control/stand.py` | NEW — `StandController`: nominal pose from stand.yaml, `target_pose()`, clamps to ±3.5 rad (constants `MIN_POS/MAX_POS`), NaN rejection |
| `src/h1_control/src/h1_control/motion_player.py` | NEW — `JointMap` (LocoMuJoCo 19-DOF → H1-2; unmapped → zero), `MotionReplay` (npz load → resample to fixed playback_rate (100 Hz default) → periodic `sample_at(t)` with linear interp, `duration`, `speed_multiplier`), `SineGait` fallback (1.6 Hz, amp 0.25–0.35 rad, legs π out of phase), `make_motion_player` factory |
| `src/h1_control/src/h1_control/estop.py` | NEW — `EstopGate`: `allows(estop_active)` + `should_abort(estop_active, running)` |
| `src/h1_control/src/h1_control/control_server.py` | REWRITTEN — action server `/h1/command` (RobotCommand), 17× `/h1/<joint>/cmd_pos` @50 Hz, `/h1/control_state` @10 Hz, `/h1/odometry` (best_effort) vx integration per goal, `/estop` subscribe→abort+freeze, use_sim_time default True, coroutine execute_callback (no blocking), MultiThreadedExecutor |
| `src/h1_control/config/stand.yaml` | ADDED `torso_joint: 0.0` — spec says 17 joints; file had 16 and torso is actuated in heinz (21 = 12 legs + torso + 8 arms, wrists commented) |
| `src/h1_control/config/joint_map.yaml` | REWRITTEN to the real npz DOF names (`hip_rotation_l`, `hip_flexion_l`, `knee_angle_l`, `ankle_angle_l`, `back_bkz`, `l_arm_shy`, `left_elbow`, …); skeleton keys did not match the actual mocap file. 15/19 DOFs mapped (shoulder shx/shz unmapped → uncontrolled), `back_bkz → torso_joint` |
| `src/h1_control/data/walk.npz` | NEW — 7.2 MB LocoMuJoCo UnitreeH1 walk mocap (see npz status below) |
| `src/h1_control/setup.py` | data_files += `data/walk.npz`; install_requires += numpy, PyYAML |
| `src/h1_control/package.xml` | exec_depend: python3-numpy, python3-yaml, python3-ament-index-python |
| `src/h1_control/test/test_pure.py` | 32 tests (no ROS imports): stand clamp/completeness, joint-map completeness + unmapped→zero, npz load/resample rate/periodicity/values-within-source-range/speed multiplier, sine gait periodicity/amplitude/phase, estop gating, npz→sine fallback |

## walk.npz status — OBTAINED

- URL: `https://huggingface.co/datasets/robfiras/loco-mujoco-datasets/resolve/main/DefaultDatasets/mocap/UnitreeH1/walk.npz` (HuggingFace mirror of the LocoMuJoCo release data; verified via the HF tree API, downloaded 7.2 MB, committed).
- Contents: `qpos` (35198, 26) = 7 root + 19 joints, `joint_names` (20, root first), `frequency` 40 Hz, dt 0.025 s; 880 s of human walking mocap mapped onto the Unitree H1.
- Default playback window `npz_window_s=30.0` (sanitized: 43 stride zero-crossings, hip flexion −0.73..0.18 rad, knee 0.07..1.14 rad — plausible walking). Node default `speed_multiplier=0.5`.

## Test evidence (acceptance)

```
$ PYTHONPATH=src python3 -m pytest test/ -q      # run from src/h1_control/
................................                                         [100%]
32 passed in 3.93s
```

Node import check (against installed h1_interfaces, no daemon started): `control_server import OK; _execute is coroutine: True`.

## Deviations from contract

1. **rclpy Jazzy execute_callback**: async generators are NOT supported by `await_or_execute` (rclpy/executors.py:108) — a `yield`-style callback would be "assumed aborted". Implemented as a plain coroutine (`async def _execute`) with explicit `goal_handle.publish_feedback(...)` and `succeed()/abort()` before returning the Result. Same behaviour as the spec (feedback + result), verified against installed rclpy source.
2. **stand.yaml was 16 joints**, spec says 17 → added `torso_joint: 0.0` (real actuated joint; the only sane 17th).
3. **joint_map.yaml skeleton keys did not exist in the npz** → rewritten to actual `joint_names` from the file (list in motion_player.py `LOCO_MUJOCO_KEYS`).
4. **Cancel requests are rejected** (CancelResponse.REJECT) — estop is the abort path, and rclpy cancel + async execute interplay is error-prone. Busy goals are also rejected (single-goal server) rather than preempted.
5. Sign conventions (hip/knee/ankle pitch) assumed identical between heinz URDF (+Y axes) and LocoMuJoCo menagerie MJCF (both Unitree-derived); **verify in sim during integration** — a mirrored ankle/hip sign falls within seconds. `test_leg_axis_columns_match_config` pins the column order only.

## Next step for the main thread

1. Merge `wt-h1_control` topologically (after h1_interfaces is built — RobotCommand/ControlState).
2. `colcon build --packages-select h1_control`; launch h1_bringup sim; launch `control_server`; send `STAND` goal via `ros2 action send_goal /h1/command h1_interfaces/action/RobotCommand "{mode: 0}"`; verify joint_states hold the stand pose (~-0.1 hip / 0.2 knee).
3. Then `WALK` goal (mode 1, distance 0 → 3 cycles ≈ 90 s at 0.5×): expect a few steps then a fall (honest expectation per plan.md §1C); watch `/h1/control_state` (MODE_WALK/STATUS_RUNNING → SUCCEEDED at timeout).
4. Estop check: publish `/estop` True mid-walk → goal aborts, STATUS_ESTOPPED, cmd_pos stops; False → IDLE.
5. If the walk direction/signs look wrong, flip signs in `config/joint_map.yaml` (hip_flexion/ankle_angle values are the likely culprits) — do NOT change the DOF keys.
6. M2.3 (IMU ankle compensation) is a separate follow-up task, not included here.