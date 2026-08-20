# TASK-h1_slam_nav2_m6 — M6 SLAM + Nav2 configuration

**Status**: CONFIG DONE / LIVE VERIFICATION BLOCKED (lidar sensor not publishing in Gazebo Harmonic) · **Date**: 2026-08-20 · Commit: `b753a11`

## Summary

M6 mapping + autonomous navigation on the 2 GB box: 2D lidar on H1 (Unitree L1
spec, bridged to `/h1/lidar/scan`), `slam_toolbox` online_async mapping, and
Nav2 with a legged-friendly controller. Config-only — verified by
`scripts/verify_m6_config.py`. Live sim verification blocked on Gazebo Harmonic
lidar sensor publishing issue (sensor defined in SDF, bridge configured, but
gz-sim-sensors-system not generating `/world/demo/model/h1_ign/link/lidar_link/sensor/lidar/scan`).

## What was built

### Lidar + bridge (M6 hardware plugin spec)

- Unitree L1 2D lidar plugin spec on the H1 (`/h1/lidar/scan`, sensor_msgs/LaserScan, BEST_EFFORT).
- `h1_bringup/launch/slam.launch.py`: topic remap `/scan` → `/h1/lidar/scan` between sim and SLAM/Nav2 nodes.
- Custom world `src/h1_bringup/worlds/empty_h1_lidar.sdf` with H1 model including lidar_link + gpu_lidar sensor.
- Parameter bridge config `ros_gz_h1_bridge.yaml` includes `/world/demo/model/h1_ign/link/lidar_link/sensor/lidar/scan` → `/h1/lidar/scan`.

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

# Live sim test (2026-08-20):
# - Sim launches with custom world (empty_h1_lidar.sdf)
# - Parameter bridge creates lidar bridge (Lazy)
# - BUT: /h1/lidar/scan has NO DATA — gz-sim-sensors-system not generating gz topic
# - Sensor defined: gpu_lidar, update_rate=10, always_on=1, 360 samples, 0.1-30m range
# - Bridge topic: /world/demo/model/h1_ign/link/lidar_link/sensor/lidar/scan
# - Status: BLOCKED — sensor system plugin not publishing in Gazebo Harmonic 8
```

All YAML parses; topic references (`/h1/lidar/scan`, `/map`, `/map_metadata`)
consistent across h1_bringup → h1_slam → h1_nav2.

## Files changed

- `src/h1_bringup/launch/slam.launch.py` (lidar remap + slam/nav2 launch wiring)
- `src/h1_bringup/launch/h1_headless.launch.py` (uses custom lidar world)
- `src/h1_bringup/worlds/empty_h1_lidar.sdf` (new — world with H1 + lidar sensor)
- `src/h1_bringup/models/h1_ign_lidar/model.sdf` (new — H1 with gpu_lidar sensor)
- `src/h1_bringup/models/h1_ign_lidar/model.config` (new)
- `src/h1_bringup/config/ros_gz_h1_bridge.yaml` (lidar bridge entry)
- `src/h1_slam/config/mapper_params_online_async.yaml` (new)
- `src/h1_nav2/config/nav2_params.yaml` (new)
- `scripts/verify_m6_config.py` (new — config validation gate)

## Next steps

1. **Fix lidar sensor publishing**: Debug gz-sim-sensors-system in Gazebo Harmonic (may need plugin update, topic naming fix, or render_engine=ogre2 config). The example world `gpu_lidar_sensor.sdf` works — diff against our model.
2. **Live-sim verify**: Once lidar publishes, run slam_toolbox + Nav2, teleop H1 through world, confirm `/map` builds and Nav2 plans path.
3. MPPI tuning on 2 GB RTF (sim-time vs wall-time) — short paths only (per AGENTS.md RTF gotcha).
4. M8: SLAM-assisted 0.3 m walks / navigation demo in Foxglove.
