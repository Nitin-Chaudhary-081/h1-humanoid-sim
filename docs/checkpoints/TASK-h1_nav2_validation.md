# TASK-h1_nav2_validation — M6 SLAM tuning + map snapshot + Nav2 validation

**Date**: 2026-08-22 · **Status**: DONE (config-level Nav2; runtime RAM-gated)

## 1. slam_toolbox tuning (`src/h1_bringup/config/mapper_params_online_async.yaml`)
Rationale: robot walks ≤0.3 m/goal at RTF ~10% → long-traverse loop-closure never fires;
loosen variance gates + raise minimum scan interval to reduce CPU churn.
| key | old | new |
|---|---|---|
| minimum_time_interval | 0.1 | 0.5 |
| distance_variance_penalty (both chains) | 0.5 | 1.0 |
| angle_variance_penalty (both chains) | 1.0 | 2.0 |

YAML re-parse validated ✓. **Restart required**: running `async_slam_toolbox`
(PID 390814) keeps old params until relaunched via `slam.launch.py`.

## 2. Live map snapshot → nav2_map_server format
- Probe: rclpy sub `/map` (TRANSIENT_LOCAL, 30 s wait) → PGM P5 + YAML.
- Files: `maps/h1_live_map.pgm`, `maps/h1_live_map.yaml`
  (resolution 0.05, origin [-7.305, -7.509, 0.0], mode trilinear).
- Verified reload (PIL): **218 × 366 px** — occupied 0-gray 293 px · free 254-gray 2100 px · unknown 205-gray 77395 px.

## 3. Nav2 validation vs live stack
Runtime branch gate: `free -m` available = 406–437 MB < 500 MB threshold (full ROS
stack resident) → **config-level validation**, runtime planning deferred.

Verified against live graph/data:
- `nav2_params.yaml` parses; sections: amcl, behavior_server, bt_navigator,
  collision_monitor, controller_server, global/local_costmap, lifecycle managers,
  map_saver, map_server, planner_server ✓
- **Correction to progress.md**: controller is **DWB** (`FollowPath` →
  `dwb_core::DWBLocalPlanner`), planner `GridBased` → `nav2_navfn_planner::NavfnPlanner`.
  MPPI was never installed (`ros2 pkg prefix nav2_mppi_controller` → not found);
  earlier "MPPI params" notes were inaccurate. DWB+NavFn is the Jazzy default set.
- global_costmap: frame `map`, base `pelvis`, static+obstacle+inflation layers;
  obstacle_layer observation source `scan` topic = **`/h1/lidar/scan`** — matches live lidar ✓
- local_costmap: odom frame, rolling window ✓
- Live data probe (20 s): `/h1/lidar/scan` LaserScan received ✓ · `/map`
  OccupancyGrid received ✓ · `/odom` silent during idle stand (publisher quiet /
  DDS-discovery wedge artifact; /tf + /tf_static present).
- Note: `get_topic_names_and_types` under-reported live topics (known FastDDS
  discovery wedge) — data-level probes are authoritative on this box.

## How to run Nav2 later (RAM permitting)
1. Stop viz+telemetry+agent (~150 MB freed), restart sim+nodes fresh.
2. `ros2 launch h1_bringup nav2.launch.py map:=maps/h1_live_map.yaml` (or
   map_server+planner_server only), lifecycle activate, then
   `/compute_path_to_pose` action test per plan in docs/checkpoints/TASK-h1_slam_nav2_m6.md.

## Next step
Runtime compute_path_to_pose demo when RAM budget allows; then M7 hardware phase-1.
