# H1-2 Hardware Bring-up Checklist

> Target: Unitree H1-2 humanoid (real hardware)  
> Base OS: Ubuntu 24.04 (Noble) + ROS 2 Jazzy  
> Workspace: `/home/ubuntu/humanoid_sim_ws` (cross-compiled or native build)

---

## 1. Network Configuration

### Static IPs
| Device | Role | Static IP | Netmask | Gateway |
|--------|------|-----------|---------|---------|
| Robot (onboard PC) | ROS 2 participant | `192.168.1.100` | `255.255.255.0` | `192.168.1.1` |
| Base Station (laptop/desktop) | ROS 2 participant | `192.168.1.101` | `255.255.255.0` | `192.168.1.1` |
| Router/AP | WiFi 5/6 | `192.168.1.1` | — | — |

- Reserve IPs via DHCP reservation (MAC-based) or configure `/etc/netplan/01-netcfg.yaml` on each machine.
- Verify: `ping -c 3 192.168.1.100` (base → robot) and `ping -c 3 192.168.1.101` (robot → base).

### ROS 2 DDS Configuration (FastDDS)
Create `/home/ubuntu/fastdds.xml` on **both** machines:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<profiles xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles">
  <participant profile_name="h1_wifi_participant" is_default_profile="true">
    <rtps>
      <builtin>
        <metatrafficUnicastLocatorList>
          <locator>
            <udpv4>
              <address>192.168.1.100</address>  <!-- robot IP -->
              <port>7400</port>
            </udpv4>
          </locator>
        </metatrafficUnicastLocatorList>
        <initialPeersList>
          <locator>
            <udpv4>
              <address>192.168.1.101</address>  <!-- base station IP -->
              <port>7400</port>
            </udpv4>
          </locator>
        </initialPeersList>
      </builtin>
      <port>
        <portBase>7400</portBase>
      </port>
    </rtps>
  </participant>
</profiles>
```

- On robot: `<address>192.168.1.100</address>` (own IP), peer = base station.
- On base station: `<address>192.168.1.101</address>` (own IP), peer = robot.
- Set env on both: `export FASTRTPS_DEFAULT_PROFILES_FILE=/home/ubuntu/fastdds.xml`
- Add to `~/.bashrc` for persistence.

### Discovery Verification
```bash
# On robot
ros2 topic list
ros2 node list
# Should see base station nodes (e.g., foxglove_bridge, rviz2 if running)

# On base station
ros2 topic list
# Should see robot topics: /h1/joint_states, /h1/imu/data, /h1/lidar/scan, /camera/*
```

---

## 2. ROS 2 Workspace Build

### Cross-compile (Recommended)
On build machine (x86_64 Ubuntu 24.04):
```bash
# Install cross-compilation toolchain
sudo apt install gcc-aarch64-linux-gnu g++-aarch64-linux-gnu

# Create cross-compile sysroot from robot
rsync -avz ubuntu@192.168.1.100:/lib /opt/cross/sysroot/lib
rsync -avz ubuntu@192.168.1.100:/usr /opt/cross/sysroot/usr

# Build with colcon (in workspace)
colcon build \
  --merge-install \
  --cmake-args -DCMAKE_TOOLCHAIN_FILE=/path/to/aarch64-toolchain.cmake \
  --packages-select h1_bringup h1_control h1_telemetry h1_llm_agent h1_visualization h1_interfaces
```

### Native Build on Robot (Fallback)
On robot (aarch64 Ubuntu 24.04):
```bash
# Install ROS 2 Jazzy (if not pre-installed)
sudo apt update && sudo apt install -y ros-jazzy-desktop

# Clone workspace
git clone https://github.com/Nitin-Chaudhary-081/h1-humanoid-sim.git humanoid_sim_ws
cd humanoid_sim_ws

# Install dependencies
rosdep install --from-paths src --ignore-src -r -y

# Build with colcon defaults (symlink-install, -j1, Release)
colcon build --packages-select h1_bringup h1_control h1_telemetry h1_llm_agent h1_visualization h1_interfaces
```

### Colcon Defaults (Enforced)
`~/.colcon/defaults.yaml`:
```yaml
build:
  symlink-install: true
  parallel-workers: 1
  cmake-args:
    - "-DCMAKE_BUILD_TYPE=Release"
```

---

## 3. Hardware Interfaces

### Joint Command & State
| ROS Topic | Direction | Type | Description |
|-----------|-----------|------|-------------|
| `/h1/<joint>/cmd_pos` | Robot ← Controller | `std_msgs/Float64` | Position command per joint (21 actuated joints) |
| `/h1/joint_states` | Robot → Controller | `sensor_msgs/JointState` | Position, velocity, effort for all 21 joints |

**Joint Names (21 actuated):**
```
left_hip_yaw, left_hip_roll, left_hip_pitch, left_knee, left_ankle_pitch, left_ankle_roll,
right_hip_yaw, right_hip_roll, right_hip_pitch, right_knee, right_ankle_pitch, right_ankle_roll,
waist_yaw, waist_roll, waist_pitch,
left_shoulder_pitch, left_shoulder_roll, left_shoulder_yaw, left_elbow,
right_shoulder_pitch, right_shoulder_roll, right_shoulder_yaw, right_elbow
```
(Wrists are unactuated in H1-2.)

**Implementation Options:**
- **Unitree SDK**: Direct motor control via Unitree's C++ SDK (low-level, high-frequency).
- **ROS 2 Control `hardware_interface`**: Preferred for ROS 2 integration. Implement `SystemInterface` with `read()`/`write()` mapping to Unitree SDK.

### IMU
| ROS Topic | Type | Frame | Rate |
|-----------|------|-------|------|
| `/h1/imu/data` | `sensor_msgs/Imu` | `h1_imu_link` | 200–400 Hz |

Fields: `orientation` (quaternion), `angular_velocity`, `linear_acceleration`. Covariances filled from spec sheet.

### Lidar (Unitree L1 / L2)
| ROS Topic | Type | Frame | Rate |
|-----------|------|-------|------|
| `/h1/lidar/scan` | `sensor_msgs/LaserScan` | `h1_lidar_link` | 10–20 Hz |

- L1: 2D, 270° FOV. L2: 3D (if available, use `sensor_msgs/PointCloud2` on `/h1/lidar/points`).
- Driver: `unitree_lidar_ros2` or `ldlidar_stl_ros2` (adapt for Unitree protocol).

### Camera (RGB-D)
| ROS Topic | Type | Frame | Rate |
|-----------|------|-------|------|
| `/camera/image_raw` | `sensor_msgs/Image` (RGB8) | `camera_color_optical_frame` | 30 Hz |
| `/camera/depth/image_raw` | `sensor_msgs/Image` (16UC1) | `camera_depth_optical_frame` | 30 Hz |
| `/camera/color/camera_info` | `sensor_msgs/CameraInfo` | — | 30 Hz |
| `/camera/depth/camera_info` | `sensor_msgs/CameraInfo` | — | 30 Hz |

- Driver: `realsense2_camera` (Intel RealSense) or `orbbec_camera` (Orbbec) depending on sensor.
- Align depth to color (or vice versa) via driver config.

---

## 4. Calibration

| Calibration | Method | Output | Validation |
|-------------|--------|--------|------------|
| **IMU Orientation** | Place robot flat, stationary. Record 10s IMU. Compute gravity vector → body frame alignment. | `imu_orientation_correction.yaml` (quaternion offset) | `imu/data` shows ~0 pitch/roll when flat. |
| **Camera Intrinsics** | ROS `camera_calibration` (checkerboard 8×6, 0.025m squares). | `camera_info.yaml` (K, D, R, P) | Reprojection error < 0.5 px. |
| **Camera Extrinsics** | Hand-eye calibration (move arm, observe checkerboard) or `ros2 run tf2_ros static_transform_publisher` with measured offsets. | `camera_to_base.yaml` (TF: `base_link` → `camera_link`) | Visual alignment in RViz/Foxglove. |
| **Lidar-to-Base** | Measure physical mount offset (x, y, z, roll, pitch, yaw). | `lidar_to_base.yaml` (TF: `base_link` → `h1_lidar_link`) | Scan aligns with robot footprint in RViz. |
| **Joint Zero Offsets** | Command zero position, measure actual joint angles (encoders vs. physical). | `joint_zero_offsets.yaml` (per-joint radian offset) | `joint_states` reads ~0 at mechanical zero. |

Store all calibration files in `config/calibration/` and load via launch parameters.

---

## 5. Safety

### Hardware E-Stop (GPIO)
- **Pin**: GPIO 17 (configurable) on onboard PC → relay cutting motor power.
- **Logic**: Active-low (pin HIGH = enabled, LOW = estop).
- **ROS Interface**: `/estop` topic (`std_msgs/Bool`, true = estop engaged).
- **Node**: `hardware_estop_node` reads `/estop` → drives GPIO.

### Software E-Stop
- Topic: `/estop` (`std_msgs/Bool`).
- All controllers subscribe; on `true`: command zero torque, disable motors.
- Latency: < 10 ms from publish to motor disable.

### Joint Limit Enforcement
- Config: `config/joint_limits.yaml` (min/max position, max velocity, max effort per joint).
- Enforced in `hardware_interface::write()` — clamp commands before sending to SDK.
- Violation → log warning, publish `/h1/safety/joint_limit_violation` (`std_msgs/String`).

### Torque Limits
- Config: `config/torque_limits.yaml` (max torque per joint).
- Enforced in `hardware_interface::write()` — clamp effort commands.
- Exceeding limit for > 100 ms → trigger software estop.

### Fall Detection
- Monitor: `/h1/imu/data` → compute body pitch/roll (from quaternion).
- Thresholds: `|pitch| > 45°` OR `|roll| > 45°` → **immediate estop**.
- Node: `fall_detector_node` (lifecycle, activates on `configure`).
- Publishes: `/h1/safety/fall_detected` (`std_msgs/Bool`).

---

## 6. Launch System

### `hardware.launch.py` (No Gazebo, Real Bridges Only)
```python
# launch/hardware.launch.py
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

def generate_launch_description():
    # Parameter files for real robot (different gains, limits)
    robot_params = PathJoinSubstitution([
        FindPackageShare('h1_bringup'), 'config', 'real_robot.yaml'
    ])
    safety_params = PathJoinSubstitution([
        FindPackageShare('h1_bringup'), 'config', 'safety_limits.yaml'
    ])
    calibration_params = PathJoinSubstitution([
        FindPackageShare('h1_bringup'), 'config', 'calibration', 'all_calibrations.yaml'
    ])

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),

        # Hardware interface (Unitree SDK bridge)
        Node(
            package='h1_hardware_interface',
            executable='hardware_interface_node',
            name='h1_hardware_interface',
            output='screen',
            parameters=[robot_params, safety_params, calibration_params],
        ),

        # Joint state publisher (from hardware interface)
        Node(
            package='h1_hardware_interface',
            executable='joint_state_publisher',
            name='joint_state_publisher',
            output='screen',
        ),

        # IMU driver
        Node(
            package='unitree_imu_driver',
            executable='imu_node',
            name='imu_driver',
            output='screen',
            parameters=[calibration_params],
        ),

        # Lidar driver
        Node(
            package='unitree_lidar_driver',
            executable='lidar_node',
            name='lidar_driver',
            output='screen',
            parameters=[calibration_params],
        ),

        # Camera driver (RealSense example)
        IncludeLaunchDescription(
            PathJoinSubstitution([
                FindPackageShare('realsense2_camera'), 'launch', 'rs_launch.py'
            ]),
            launch_arguments={
                'align_depth.enable': 'true',
                'enable_color': 'true',
                'enable_depth': 'true',
            }.items(),
        ),

        # Control stack (stand/walk actions)
        IncludeLaunchDescription(
            PathJoinSubstitution([
                FindPackageShare('h1_control'), 'launch', 'control_stack.launch.py'
            ]),
            launch_arguments={'use_sim_time': 'false'}.items(),
        ),

        # Telemetry + anomaly detection
        IncludeLaunchDescription(
            PathJoinSubstitution([
                FindPackageShare('h1_telemetry'), 'launch', 'telemetry.launch.py'
            ]),
            launch_arguments={'sync_enabled': 'true'}.items(),
        ),

        # Foxglove bridge (for remote visualization)
        Node(
            package='foxglove_bridge',
            executable='foxglove_bridge',
            name='foxglove_bridge',
            output='screen',
            parameters=[{'port': 8765, 'address': '0.0.0.0'}],
        ),

        # LLM agent (optional, requires API key)
        IncludeLaunchDescription(
            PathJoinSubstitution([
                FindPackageShare('h1_llm_agent'), 'launch', 'agent.launch.py'
            ]),
            condition=IfCondition(LaunchConfiguration('enable_llm')),
        ),
    ])
```

### Parameter Files (Real Robot vs Sim)
| File | Purpose | Key Differences from Sim |
|------|---------|--------------------------|
| `config/real_robot.yaml` | Control gains, PD targets | Higher Kp/Kd, lower velocity limits |
| `config/safety_limits.yaml` | Joint/torque limits | Hardware-enforced limits |
| `config/calibration/all_calibrations.yaml` | All calibration offsets | Real measured values |

---

## 7. Monitoring & Telemetry

### Foxglove Bridge
- Port: `8765` (restrict via firewall to base station IP).
- Subprotocol: `foxglove.sdk.v1`.
- Panels: 3D (robot model + TF), Time-series (joint states, IMU, odom), Telemetry (system load, battery), Safety (estop status, fall risk).

### Telemetry to AWS
- Enable in `telemetry.launch.py`: `sync_enabled:=true`.
- Lambda: `h1_aws_sync_ingest` (deployed via `scripts/deploy_aws_stack.sh`).
- Data flow: `h1_telemetry` node → `telemetry.jsonl` → Lambda (scheduled or event-driven) → S3 + DynamoDB + SNS.
- SNS alerts → `stickfitofficial@gmail.com` (critical: fall, joint limit, torque limit).

### Log Rotation
```bash
# /etc/logrotate.d/ros2-h1
/var/log/ros2/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 ubuntu ubuntu
}
```
- Apply: `sudo logrotate -f /etc/logrotate.d/ros2-h1`

---

## 8. Testing Procedure

### Phase 1: Standalone Joint Test
1. Launch `hardware.launch.py` (no control stack).
2. Publish to `/h1/left_hip_pitch/cmd_pos` → `0.5` (rad).
3. Verify `/h1/joint_states` shows movement to ~0.5 rad.
4. Repeat for all 21 joints.
5. **Pass**: All joints respond, no limit violations, encoders match command.

### Phase 2: IMU Calibration Verification
1. Place robot flat on level surface.
2. `ros2 topic echo /h1/imu/data --qos-reliability best_effort`
3. Verify: `orientation` ≈ `[0, 0, 0, 1]` (or calibrated offset), `linear_acceleration` ≈ `[0, 0, -9.81]`.
4. Tilt robot ±10° → verify pitch/roll change matches.

### Phase 3: Lidar SLAM Test
1. Launch `hardware.launch.py` + `slam_toolbox` (online_async.launch.py).
2. Walk robot manually (joystick or push) in 5×5m area.
3. Verify map builds in RViz/Foxglove (`/map` topic).
4. **Pass**: Map shows walls/obstacles, robot pose tracked.

### Phase 4: Safety Harness Walk Test (0.3 m)
1. Attach safety harness (overhead gantry or tether) — **robot must not fall unsupported**.
2. Launch full stack: `hardware.launch.py` + control stack.
3. Send `Walk` action goal: `distance: 0.3` (via `ros2 action send_goal` or LLM agent).
4. Monitor: joint states, IMU, estop status, Foxglove.
5. **Pass**: Robot walks 0.3 m, maintains balance, no safety triggers, stops at goal.

---

## 9. Rollback / Recovery

| Issue | Recovery |
|-------|----------|
| FastDDS wedge (topics stop) | `pkill -f fastdds; rm -f /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_*; ros2 daemon stop; restart launch` |
| Motor communication loss | Hardware estop → power cycle motor drivers → re-launch |
| Calibration drift | Re-run calibration procedures (Sec 4) |
| OOM on robot (2 GB RAM) | Disable non-critical nodes (LLM agent, SLAM), reduce publish rates |

---

## 10. Sign-off Checklist

| Item | Verified By | Date |
|------|-------------|------|
| Static IPs + FastDDS discovery | | |
| ROS 2 workspace builds (native/cross) | | |
| All 21 joint cmd/state topics functional | | |
| IMU publishing calibrated data | | |
| Lidar scan visible in Foxglove | | |
| Camera RGB + depth + info publishing | | |
| All calibrations loaded + validated | | |
| Hardware estop cuts motor power | | |
| Software estop disables controllers | | |
| Joint/torque limits enforced | | |
| Fall detection triggers estop | | |
| `hardware.launch.py` brings up full stack | | |
| Foxglove bridge accessible from base station | | |
| Telemetry → AWS (S3/DDB/SNS) working | | |
| Log rotation configured | | |
| Joint test pass (21/21) | | |
| IMU calibration verified | | |
| Lidar SLAM map builds | | |
| **0.3 m walk with harness: PASS** | | |

---

> **Next Steps After Bring-up**: M5 Vision pick-place, M6 SLAM+Nav2, M7 Voice, M8 RL, M9 MLOps.