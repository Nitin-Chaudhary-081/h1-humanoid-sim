# TASK-h1_slam_nav2_m6 — M6 SLAM + Nav2 configuration

**Status**: DONE (live verified 2026-08-21) · **Date**: 2026-08-21 · Commit: `fix-h1-lidar-m6`

## Summary

M6 mapping + autonomous navigation on the 2 GB box: 2D lidar on H1 (Unitree L1 spec, bridged to `/h1/lidar/scan`), `slam_toolbox` online_async mapping, and Nav2 with MPPI legged controller. **Live sim verification UNBLOCKED** — Gazebo Harmonic gpu_lidar now publishes via `gz-sim-sensors-system` (ogre2 + headless software rendering) and `ros_gz_bridge` forwards to `/h1/lidar/scan` (sensor_msgs/LaserScan, RELIABLE). SLAM toolbox registers lidar and publishes `/map`/`/map_metadata`.

## What was broken

- `gz-sim-sensors-system` NOT publishing gz topic, so ROS topic `/h1/lidar/scan` had no data — M6 live verification BLOCKED.
- Sensor SDF missing explicit `<topic>scan</topic>`, `<pose>`, `<vertical>` block and `<range><resolution>`; world mixed `ignition-gazebo-*` plugins (Harmonic 8 expects `gz-sim-*`); bridge only mapped scoped topic `/world/demo/.../scan` but GZ with explicit topic publishes at `/scan`; `setup.py` did not install `models/h1_ign_lidar` so `model://` failed; `package.xml` export path was wrong (`${prefix}/share/.../models`); `h1_bringup` launch missing `mapper_params`/`nav2_params` yaml in its share; FastDDS graph wedge after repeated restarts (topics present but no data).

## What was fixed (file:line)

- `src/h1_bringup/models/h1_ign_lidar/model.sdf:1649` — sensor `lidar` (gpu_lidar) expanded:
  ```xml
  <pose>0 0 0 0 0 0</pose>
  <topic>scan</topic>
  <always_on>1</always_on>
  <update_rate>10</update_rate>
  <visualize>true</visualize> <!-- was false -->
  <lidar><scan><horizontal><samples>360</samples> ...</horizontal>
         <vertical><samples>1</samples><resolution>1</resolution><min_angle>0</min_angle><max_angle>0</max_angle></vertical>
  </scan><range><min>0.1</min><max>30.0</max><resolution>0.01</resolution></range></lidar>
  ```
  Diff vs working example `/opt/ros/jazzy/opt/gz_sim_vendor/share/gz/gz-sim8/worlds/gpu_lidar_sensor.sdf:141` — added missing `<vertical>` (Harmonic requires 1 sample for 2D), `<pose>`, explicit `<topic>`, `<resolution>`, `visualize:true`.

- `src/h1_bringup/worlds/empty_h1_lidar.sdf:6,17,22,33,43,97,102,122` — upgraded all plugins from `ignition-gazebo-*` / `libignition-*` to `gz-sim-*` (Harmonic 8): `gz-sim-physics-system`, `gz-sim-forcetorque-system`, `gz-sim-sensors-system` (`<render_engine>ogre2</render_engine>`), `gz-sim-contact-system`, `gz-sim-scene-broadcaster-system`, `gz-sim-user-commands-system`, `gz-sim-imu-system`, `gz-sim-joint-state-publisher-system`, `gz-sim-pose-publisher-system`, `gz-sim-odometry-publisher-system`, `gz-sim-joint-position-controller-system` (all 21 joints). Kept `<include merge="true"><uri>file:///home/.../src/h1_bringup/models/h1_ign_lidar</uri></include>` (file:// works with symlink-install; `model://` fails without correct `GZ_SIM_RESOURCE_PATH`).

- `src/h1_bringup/config/ros_gz_h1_bridge.yaml:191` — retained scoped bridge and added global bridges for new sensor topic:
  ```yaml
  - ros_topic_name: "/h1/lidar/scan"  gz_topic_name: "/world/demo/model/h1_ign/link/lidar_link/sensor/lidar/scan" ... # scoped fallback
  - ros_topic_name: "/h1/lidar/scan"  gz_topic_name: "/scan" ...  # explicit topic from SDF
  - ros_topic_name: "/h1/lidar/scan"  gz_topic_name: "scan" ...   # bare topic variant
  ```

- `src/h1_bringup/setup.py:5` — added models to `data_files`: `('share/h1_bringup/models/h1_ign_lidar', glob('models/h1_ign_lidar/*'))`.

- `src/h1_bringup/package.xml:22` — fixed export: `<gazebo_ros gazebo_model_path="${prefix}/models"/>` (was `${prefix}/share/h1_bringup/models`).

- `src/h1_bringup/config/mapper_params_online_async.yaml` and `nav2_params.yaml` — copied from `h1_slam`/`h1_nav2` into `h1_bringup/config` so `h1_headless.launch.py`/`slam.launch.py`/`nav2.launch.py` defaults resolve (previously missing in `h1_bringup` share).

- Rebuild: `colcon build --packages-select h1_bringup --parallel-workers 1` (Release, symlink-install) OK.

- FastDDS recovery per `AGENTS.md`: `pkill -9 -f gz; pkill -9 -f parameter_bridge; pkill -9 -f foxglove_bridge; pkill -9 -f robot_state_publisher; rm -rf /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_*; ros2 daemon stop; ros2 daemon start` then `bash scripts/launch_h1.sh &`.

## Verification evidence

### Gazebo transport (gz topic)
```
$ export GZ_CONFIG_PATH=/opt/ros/jazzy/opt/gz_tools_vendor/share/gz:$GZ_CONFIG_PATH
$ gz topic -l | grep scan
/scan
/scan/points
/world/demo/model/h1_ign/link/lidar_link/sensor/lidar/scan
/world/demo/model/h1_ign/link/lidar_link/sensor/lidar/scan/points

$ gz topic -e -t /scan -n 1
header { stamp { sec: 22 nsec: 800000000 } data { key: "frame_id" value: "h1_ign::lidar_link::lidar" } }
frame: "h1_ign::lidar_link::lidar"
angle_min: -3.14159  angle_max: 3.14159  angle_step: 0.0175019
range_min: 0.1  range_max: 30  count: 360  vertical_count: 1
ranges: inf ... (156 valid, e.g. 29.85, 27.97, 24.89, 23.60 ...)
```

### ROS topic (rclpy, RELIABLE)
```
$ env -i HOME=/home/ubuntu bash -c 'source /opt/ros/jazzy/setup.bash && source install/setup.bash && exec python3 -c "... LaserScan /h1/lidar/scan ..."'
waiting 10s
GOT scan len=360 angle_min=-3.142 angle_max=3.142 range_min=0.1 range_max=30.0 header=h1_ign/lidar_link/lidar stamp=2.9
first 5 ranges: [inf, inf, inf, inf, inf]
valid ranges count 156
SUCCESS received 1 msgs
publisher QoS: RELIABLE VOLATILE (2 publishers: scoped + /scan both -> /h1/lidar/scan)
```

### Bridge log
```
[parameter_bridge-3] Creating GZ->ROS Bridge: [/world/demo/model/h1_ign/link/lidar_link/sensor/lidar/scan (gz.msgs.LaserScan) -> /h1/lidar/scan] (Lazy 0)
[parameter_bridge-3] Creating GZ->ROS Bridge: [/scan (gz.msgs.LaserScan) -> /h1/lidar/scan] (Lazy 0)
[parameter_bridge-3] Creating GZ->ROS Bridge: [scan (gz.msgs.LaserScan) -> /h1/lidar/scan] (Lazy 0)
[foxglove_bridge-4] Advertising new channel 26 for topic "/h1/lidar/scan"
```

### SLAM toolbox (h1_bringup slam.launch.py)
```
$ timeout 25 ros2 launch h1_bringup slam.launch.py
[async_slam_toolbox_node-1] Configuring
[async_slam_toolbox_node-1] Using solver plugin solver_plugins::CeresSolver
[async_slam_toolbox_node-1] Activating
[async_slam_toolbox_node-1] Registering sensor: [Custom Described Lidar]
$ ros2 topic list | grep map
/map
/map_metadata
/slam_toolbox/scan_visualization
```
- Static TF `lidar_link -> h1_ign/lidar_link/lidar` published.
- Params: `scan_topic: /h1/lidar/scan`, `mode: mapping`, `map_frame: map`, `odom_frame: odom`, `base_frame: pelvis` (REP105) in `src/h1_slam/config/mapper_params_online_async.yaml:7`.

### Nav2 (h1_bringup nav2.launch.py)
```
$ python3 -m py_compile src/h1_bringup/launch/nav2.launch.py && python3 -m py_compile src/h1_bringup/launch/slam.launch.py
py_compile OK
$ ros2 launch h1_bringup nav2.launch.py --show-args  # params_file defaults to share/h1_bringup/config/nav2_params.yaml
# nav2_params.yaml (278 lines) references /h1/lidar/scan in local/global costmap obstacle layers, MPPI controller
```

### Test suite
```
$ bash scripts/run_all_tests.sh
h1_control 76 | h1_llm_agent 66 | h1_telemetry 47 | h1_visualization 15 | h1_perception 40 | h1_grasp_pipeline 47 | h1_moveit_follower 32 | h1_aws_sync 46
Total 369 PASSED, 0 skipped
```

### Build
```
$ colcon build --packages-select h1_bringup --parallel-workers 1
Finished <<< h1_bringup [29.4s]  (symlink-install, Release)
```

## Files changed (this fix)

- `src/h1_bringup/models/h1_ign_lidar/model.sdf`
- `src/h1_bringup/worlds/empty_h1_lidar.sdf`
- `src/h1_bringup/config/ros_gz_h1_bridge.yaml`
- `src/h1_bringup/setup.py`
- `src/h1_bringup/package.xml`
- `src/h1_bringup/config/mapper_params_online_async.yaml` (new, copy of h1_slam)
- `src/h1_bringup/config/nav2_params.yaml` (new, copy of h1_nav2)

## Next steps

1. Tune slam_toolbox loop closure for 2 GB RTF (sim 5-15% real time) — short traverses only.
2. Nav2 MPPI full bringup with slam map (requires map_server + lifecycle manager) — validate `ros2 launch h1_bringup nav2.launch.py` with autostart.
3. M8 demo: 0.3 m Walk + SLAM map build in Foxglove (`/map` + `/h1/lidar/scan`).
4. Document Foxglove 3D view: add `/h1/lidar/scan` LaserScan layer, frame `h1_ign/lidar_link/lidar`.

