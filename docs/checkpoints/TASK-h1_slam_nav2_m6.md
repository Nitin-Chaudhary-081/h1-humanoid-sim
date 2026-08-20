# TASK-h1_slam_nav2_m6 — M6 SLAM + Nav2 configuration

**Status**: DONE (config validated; live-sim verification pending) · **Date**: 2026-08-19 · Commit: `63ebcc7`

## Summary

M6 mapping + autonomous navigation on the 2 GB box: 2D lidar on H1 (Unitree L1
spec, bridged to `/h1/lidar/scan`), `slam_toolbox` online_async mapping, and
Nav2 with a legged-friendly controller. All config-only — verified by
`scripts/verify_m6_config.py`; live sim verification is a pending M6 follow-up.

## What was built

### Lidar + bridge (M6 hardware plugin spec)

- Unitree L1 2D lidar plugin spec on the H1 (`/h1/lidar/scan`, sensor_msgs/LaserScan, BEST_EFFORT).
- `h1_bringup/launch/slam.launch.py`: topic remap `/scan` → `/h1/lidar/scan` between sim and SLAM/Nav2 nodes.

### `h1_slam` (ament_python, config)

- `config/mapper_params_online_async.yaml` — slam_toolbox **online_async** mapper: `scan_topic: /h1/lidar/scan`, scan buffer settings, matching params (use_scan_matching, scan_barycenter), loop-closure config, `map_frame/odom_frame/base_frame` per REP 105 (odom → base_link → pelvis).
- Outputs `/map` + `/map_metadata` (TRANSIENT_LOCAL).

### `h1_nav2` (ament_python, config)

- `config/nav2_params.yaml` (238 lines) — Nav2 stack tuned for legged locomotion:
  - **Controller**: MPPI controller (legged-friendly, avoids the velocity-kill of DWB on foot slippage) — planner plugin (NavFn/GridBased) with fallback, global costmap
  - **Costmaps** (global + local): `robot_radius`/footprint from URDF, `observation_sources: scan` → `/h1/lidar/scan`, inflation radius
  - **BT navigator**, planner server, recovery behaviors (spin/backup), Waypoint/FollowPath servers, `scan_topic` for obstacle layers

## Verification evidence

```
# Config validation (no sim, no build — M6 acceptance)
$ python3 scripts/verify_m6_config.py
# → lidar remap present, slam_toolbox params load, Nav2 params load,
#   controllers/planners/costmaps reference /h1/lidar/scan, frames match contract
```

All YAML parses; topic references (`/h1/lidar/scan`, `/map`, `/map_metadata`)
consistent across h1_bringup → h1_slam → h1_nav2.

## Files changed

- `src/h1_bringup/launch/slam.launch.py` (lidar remap + slam/nav2 launch wiring)
- `src/h1_slam/config/mapper_params_online_async.yaml` (new)
- `src/h1_nav2/config/nav2_params.yaml` (new)
- `scripts/verify_m6_config.py` (new — config validation gate)

## Next steps

1. **Live-sim verify (pending)**: add lidar plugin to heinz (vendor override in h1_bringup), run slam_toolbox + Nav2, teleop H1 through the world, confirm `/map` builds and Nav2 plans a path.
2. MPPI tuning on 2 GB RTF (sim-time vs wall-time) — short paths only (per AGENTS.md RTF gotcha).
3. M8: SLAM-assisted 0.3 m walks / navigation demo in Foxglove.
