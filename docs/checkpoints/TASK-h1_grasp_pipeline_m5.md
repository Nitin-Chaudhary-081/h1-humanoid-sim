# TASK-h1_grasp_pipeline_m5 — M5 grasp pipeline (ArUco → grasp → trajectory)

**Status**: DONE (pure logic + live E2E verified 2026-08-21)
**Date**: 2026-08-19 (pure) → 2026-08-21 live · Commit: `63ebcc7` → `live-m5-2026-08-21`

## Summary

M5 grasp pipeline: converts ArUco marker detections into arm grasp poses and
joint-space trajectories, with a heuristic planner and an optional MoveIt2
planner (`MoveIt2Planner`), served by the `/h1/grasp/execute` action server
(`GraspExecute.action`). 47 unit tests pass (post-fix). **Live E2E verified**:
demo perception (synthetic marker 42) → GraspExecute → FollowJointTrajectory → joint
commands on live headless Gazebo Harmonic sim (2 GB VPS).

## What was built

| Component | Detail |
|---|---|
| `grasp_pipeline.py` — pure logic (no ROS) | `GraspOffsets` (pregrasp_offset, grasp_depth, approach axis), `CameraToBaseTransform`, `MarkerDetection`, `GraspTrajectory`; `GraspPipeline`: `filter_detections()` (marker id/confidence/reachability), `transform_pose_camera_to_base()`, `compute_grasp_poses()` (grasp + pregrasp + retract poses from marker frame), `solve_ik_simplified()` (arm IK, fallback heuristic), `generate_trajectory()` (approach → grasp → lift), `_plan_with_heuristic()` / `_plan_with_moveit()` |
| `MoveIt2Planner` | Optional ROS-dependent callable wrapping MoveIt2 planning (injected into `GraspPipeline.moveit_planner`); keeps the core testable without ROS |
| `grasp_node.py` — `GraspNode` | Action server `/h1/grasp/execute` (h1_interfaces/GraspExecute: target_marker_id, pregrasp_offset, grasp_depth → success, trajectory, message; feedback phase/progress); subscribes `/h1/perception/detections` (PerceptionFrame) to resolve marker ids; publishes joint trajectory msg for the follower; cancel handler |
| `config/*.yaml` | Grasp offsets, IK settings, planning timeout via params |

Contract (docs/contracts/topics.md): action server at `/h1/grasp/execute`,
goal = marker id + offsets; all clients go through it (perception node, future
LLM agent tool).

## Verification evidence

### Pure tests (369/369 pass via scripts/run_all_tests.sh, 2026-08-21)
```
PASS   h1_control         76 tests
PASS   h1_llm_agent       66 tests
PASS   h1_telemetry       47 tests
PASS   h1_visualization   15 tests
PASS   h1_perception      40 tests
PASS   h1_grasp_pipeline  47 tests
PASS   h1_moveit_follower 32 tests
PASS   h1_aws_sync        46 tests
Total 369/369 PASS
```

### Live E2E — 2026-08-21, headless Gazebo Harmonic on 2 GB VPS

**Workspace builds**: `colcon build --packages-select h1_perception h1_grasp_pipeline h1_moveit_follower --symlink-install -j1` — all 3 OK (45.8s, 40.7s, 43.8s).

**Sim**: `gz sim -s -r --headless-rendering install/h1_bringup/share/h1_bringup/worlds/empty_h1_lidar.sdf` (pid 377756) + `ros_gz_bridge` + `foxglove_bridge` + `robot_state_publisher`. FastDDS wedge recovery: `pkill -9 gz; pkill -9 ruby; rm -rf /dev/shm/fastrtps_*; ros2 daemon stop/start` before restart. Verified via `env -i HOME=/home/ubuntu bash -c '...rclpy...'` — `/clock` OK, `/joint_states` OK (BEST_EFFORT), `/h1/odometry` OK.

**Nodes (detached via scripts/launch_detached.sh + setsid, env -i HOME=/home/ubuntu)**:

| Node | PID | Log | Start cmd (excerpt) |
|---|---|---|---|
| h1_control (control_server) | 378020 | /tmp/opencode/control.log | `python3 scripts/run_server.py` — `h1_control ready: 17 joints` |
| h1_perception demo | 378049 | /tmp/opencode/perception.log | `python3 -u -m h1_perception.perception_node --ros-args -p demo_mode:=true -p demo_marker_id:=42 -p demo_pose_xyz:="[0.5,0.2,0.8]" -p camera_frame:=camera_link` — `h1_perception_node started: mode=demo, id=42 at [0.5,0.2,0.8]` |
| h1_moveit_follower | 378089 | /tmp/opencode/follower.log | `python3 -u -m h1_moveit_follower.follower_node --ros-args --params-file /home/ubuntu/humanoid_sim_ws/src/h1_moveit_follower/config/follower.yaml` — `H1 MoveIt2 trajectory follower node started`, publishing 4 joints |
| h1_grasp_pipeline | 378369 | /tmp/opencode/grasp.log | `python3 -u -m h1_grasp_pipeline.grasp_node --ros-args --params-file /home/ubuntu/humanoid_sim_ws/src/h1_grasp_pipeline/config/grasp.yaml -p target_marker_id:=42 -p use_moveit:=false` — `h1_grasp_node started: target_marker_id=42, approach=0.15m` |

Verified: `pgrep -a` shows all 4, `get_action_names_and_types` via rclpy shows `/h1/command`, `/h1/grasp/execute`, `/h1/moveit/follow_trajectory` all up (see `ps aux` + action list output 2026-08-21).

**Perception**: `subscribe /h1/perception/detections` (RELIABLE, 10 Hz) — received 2 frames in 3 s, `frame_id=camera_link detections=1 marker 42 pose 0.5 0.2 0.8` (demo mode, see log `demo mode: publishing synthetic marker id=42 at [0.5,0.2,0.8]`). Topic verified via `env -i ... python3 -c "subscribe PerceptionFrame, expect 1 frame with marker 42 within 3s"` — PASS.

**GraspExecute client** (`/tmp/opencode/test_grasp_client.py`, rclpy ActionClient, 30 s timeout):
```
Waiting for grasp server... Server available, sending goal
Sending goal: marker=42, pregrasp_offset=0.15, grasp_depth=0.02
Goal accepted, waiting for result...
Result status: 4 (SUCCEEDED)
Success: True
Message: Grasp executed successfully
Trajectory joint_names: ['left_shoulder_pitch_joint', 'left_elbow_joint', 'right_shoulder_pitch_joint', 'right_elbow_joint']
Trajectory points: 3
  point 0: time 0.00s positions [-0.0685, 0.6324, 0.0685, 0.6324]
  point 1: time 2.00s positions [-0.0621, 0.6522, 0.0621, 0.6522]
  point 2: time 4.00s positions [-0.0585, 0.6629, 0.0585, 0.6629]
```
Second run after follower fix reproduced identical success (wall 17 s for 4 s sim time, RTF ~23 %, see follower log 1536→1554). Both runs returned `success=True`.

**Follower verification**:
- Log `follower.log:41` — `Accepting goal with 4 joints, 3 points` → `Trajectory execution completed` → `No joint state received; skipping tolerance check` (tolerance check skipped because bridge publishes `/joint_states` not `/h1/joint_states`; still returns SUCCESSFUL). After fix, Duration bug resolved, trajectory correctly interpolated at 50 Hz and published to `/h1/*_joint/cmd_pos` (verified via `ros_gz_bridge` creating ROS→GZ bridges for 4 joints).
- Grasp log: `Accepting grasp goal for marker 42` → `GraspExecute goal: marker=42` → `Grasp executed successfully` (no crash after `_send_trajectory` fix).
- Joint states: `subscribe /joint_states` (BEST_EFFORT) shows arm joints moved from 0 to `left_shoulder_pitch -0.039, left_elbow 0.677, right_shoulder_pitch 0.069, right_elbow 0.676` (close to final waypoint, sim dynamics). Initial stand pose was 0, so verified motion.
- Bridge: `ros_gz_h1_bridge.yaml` has 4 arm joints (left/right shoulder_pitch + elbow) as `ROS→GZ` `std_msgs/Float64 → gz.msgs.Double` — matches follower's `arm_joint_names`.

**Fixes applied (file:line)**:
- `src/h1_perception/src/h1_perception/perception_node.py:226-244` — removed dead unreachable code after `return out` in `_demo_detections_as_aruco` (previously duplicated `for det in self._latest_detections` block).
- `src/h1_grasp_pipeline/setup.py:9-10` — added `find_packages(where="src"), package_dir={"": "src"}` (was `find_packages(exclude=["test"])` causing `ModuleNotFoundError: No module named 'h1_grasp_pipeline'` when run via `python3 -m h1_grasp_pipeline.grasp_node`).
- `src/h1_grasp_pipeline/config/grasp.yaml:1-41` — wrapped flat YAML into `h1_grasp_node: ros__parameters:` so `--params-file` loads correctly (was flat, rcl failed to parse).
- `src/h1_moveit_follower/src/h1_moveit_follower/follower_node.py:53-72` — robust YAML fallback (absolute, workspace, install share) + `get_package_share_directory` fallback; previously failed with `FileNotFoundError: /home/ubuntu/src/...` when launched via `env -i` with cwd=/home/ubuntu.
- `src/h1_moveit_follower/src/h1_moveit_follower/follower_node.py:168-172` — fixed `Duration` handling: `point.time_from_start.sec + point.time_from_start.nanosec*1e-9` with try/except for `nanoseconds` attribute (was `point.time_from_start.nanoseconds` causing `AttributeError: 'Duration' object has no attribute 'nanoseconds'` and abort).
- `src/h1_grasp_pipeline/src/h1_grasp_pipeline/grasp_node.py:269-290` — replaced nested `rclpy.spin_until_future_complete` inside action callback (caused `wait set index for status subscription is out of bounds` and node crash) with poll loop `while not future.done(): time.sleep(0.05)` (main MultiThreadedExecutor already spinning).

Coverage: detection filtering (id/confidence), camera→base transform math,
grasp pose computation (offsets applied in the right frame), simplified arm IK
(feasible/infeasible targets), trajectory generation (waypoint count, ordering
approach→grasp→lift, durations), heuristic vs moveit planner selection,
trajectory→JointTrajectory msg conversion, action-goal handling (node-level,
fake-ROS patterns).

## Files changed

- `src/h1_grasp_pipeline/src/h1_grasp_pipeline/grasp_pipeline.py` (pure logic, 47 tests)
- `src/h1_grasp_pipeline/src/h1_grasp_pipeline/grasp_node.py` (action server, fixes: setup.py, grasp.yaml wrapper, Duration, spin)
- `src/h1_grasp_pipeline/config/grasp.yaml` — wrapped into `h1_grasp_node: ros__parameters:`
- `src/h1_grasp_pipeline/setup.py:9` — fixed `find_packages(where="src")`
- `src/h1_perception/src/h1_perception/perception_node.py:226` — removed dead code after return
- `src/h1_moveit_follower/src/h1_moveit_follower/follower_node.py:53,168` — YAML fallback + Duration fix
- `src/h1_bringup/config/ros_gz_h1_bridge.yaml` — 4 arm joints verified (left/right shoulder_pitch + elbow) ROS→GZ
- `scripts/run_server.py` — control server (Stand/Walk/Stop) used for live sim
- `h1_interfaces/action/GraspExecute.action` — contract frozen
- `docs/checkpoints/TASK-h1_grasp_pipeline_m5.md` — this live verification

## Next steps

1. ~~Live-sim verify~~ DONE 2026-08-21 — full chain demo_perception → GraspExecute → FollowJointTrajectory → joint_states motion verified.
2. Wire LLM tool `pick_object(id)` → `/h1/grasp/execute` for M3→M5 NL demo (needs GEMINI_API_KEY).
3. Fix follower tolerance: subscribe to `/joint_states` (bridge) or remap `/h1/joint_states` → `/joint_states` via bridge remap; add wrist joints if needed.
4. M8: validate grasp success metric (marker lift + hold) + update `progress.md` + `scripts/smoke.sh` to include M5 checks as PASS (currently WARN).

## Follow timeout fix (2026-08-21)

- `grasp_node.py` `_send_trajectory`: send-poll was hardcoded 5 s wall — DDS discovery + goal response exceed that under full-stack load (RTF ~10%); now uses follow_timeout
- `config/grasp.yaml`: follow_trajectory_timeout 30.0 → 90.0 (4 s sim traj at RTF ~10% ≈ 40+ s wall)
- Node must be launched WITH `--params-file .../config/grasp.yaml` (main() does not self-load YAML)
- Tests: h1_grasp_pipeline 47 pass
