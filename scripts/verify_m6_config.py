#!/usr/bin/env python3
"""
M6 SLAM + Nav2 Configuration Verification Script
Validates all configs, bridges, launches for H1-2 sim bringup.
"""

import os
import sys
import yaml
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Any

WORKSPACE = Path("/home/ubuntu/humanoid_sim_ws")
BRINGUP_DIR = WORKSPACE / "src/h1_bringup"
SLAM_DIR = WORKSPACE / "src/h1_slam"
NAV2_DIR = WORKSPACE / "src/h1_nav2"

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"

results = []


def check(condition: bool, msg: str, details: str = "") -> bool:
    status = PASS if condition else FAIL
    results.append((condition, msg, details))
    detail_str = f"  {details}" if details else ""
    print(f"[{status}] {msg}{detail_str}")
    return condition


def run_cmd(cmd: List[str], cwd: Path = None, env: dict = None) -> Tuple[int, str, str]:
    try:
        result = subprocess.run(cmd, cwd=cwd or WORKSPACE, capture_output=True, text=True, timeout=30, env=env)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def load_yaml(path: Path) -> Dict:
    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"[ERROR] Failed to load {path}: {e}")
        return {}


def verify_bridge_config():
    print("\n=== TASK A: Lidar Bridge Validation ===")
    bridge_file = BRINGUP_DIR / "config/ros_gz_h1_bridge.yaml"
    check(bridge_file.exists(), f"Bridge config exists: {bridge_file}")

    data = load_yaml(bridge_file)
    if not data:
        check(False, "Bridge config is valid YAML")
        return

    check(isinstance(data, list), "Bridge config is a list")

    lidar_bridge = None
    cmd_vel_bridge = None
    for entry in data:
        if entry.get("ros_topic_name") == "/h1/lidar/scan":
            lidar_bridge = entry
        if entry.get("ros_topic_name") == "/cmd_vel":
            cmd_vel_bridge = entry

    check(lidar_bridge is not None, "Lidar bridge entry exists")
    if lidar_bridge:
        check(lidar_bridge.get("ros_type_name") == "sensor_msgs/msg/LaserScan", "Lidar ROS type correct")
        check(lidar_bridge.get("gz_type_name") == "gz.msgs.LaserScan", "Lidar GZ type correct")
        check(lidar_bridge.get("direction") == "GZ_TO_ROS", "Lidar direction correct")
        expected_gz_topic = "/world/demo/model/h1_ign/link/lidar_link/sensor/lidar/scan"
        check(lidar_bridge.get("gz_topic_name") == expected_gz_topic, f"Lidar GZ topic matches SDF", f"expected: {expected_gz_topic}, got: {lidar_bridge.get('gz_topic_name')}")

    check(cmd_vel_bridge is not None, "Cmd_vel bridge entry exists (for Nav2 output)")
    if cmd_vel_bridge:
        check(cmd_vel_bridge.get("ros_type_name") == "geometry_msgs/msg/Twist", "Cmd_vel ROS type correct")
        check(cmd_vel_bridge.get("direction") == "ROS_TO_GZ", "Cmd_vel direction correct")

    required_bridges = [
        "/clock", "/imu", "/joint_states", "/tf", "/tf_static", "/h1/odometry", "/camera"
    ]
    for topic in required_bridges:
        found = any(e.get("ros_topic_name") == topic for e in data)
        check(found, f"Required bridge exists: {topic}")


def verify_slam_config():
    print("\n=== TASK B: SLAM Launch Validation ===")
    slam_params = SLAM_DIR / "config/mapper_params_online_async.yaml"
    check(slam_params.exists(), f"SLAM params file exists: {slam_params}")

    data = load_yaml(slam_params)
    if data:
        params = data.get("slam_toolbox", {}).get("ros__parameters", {})
        check(params.get("use_sim_time") is True, "SLAM use_sim_time=true")
        check(params.get("map_frame") == "map", "SLAM map_frame=map")
        check(params.get("odom_frame") == "odom", "SLAM odom_frame=odom")
        check(params.get("base_frame") == "h1_ign", "SLAM base_frame=h1_ign")
        check(params.get("scan_topic") == "/h1/lidar/scan", "SLAM scan_topic=/h1/lidar/scan")
        check(params.get("mode") == "mapping", "SLAM mode=mapping")

    slam_launch = BRINGUP_DIR / "launch/slam.launch.py"
    check(slam_launch.exists(), f"SLAM launch file exists: {slam_launch}")

    content = slam_launch.read_text()
    check("async_slam_toolbox_node" in content, "Uses async_slam_toolbox_node directly")
    check("lifecycle" in content.lower() or "ChangeState" in content or "TRANSITION_CONFIGURE" in content, "Has lifecycle management (configure/activate)")
    check("scan_topic" in content or "/h1/lidar/scan" in content, "Remaps scan topic to /h1/lidar/scan")
    check("use_sim_time" in content, "Passes use_sim_time")


def verify_nav2_config():
    print("\n=== TASK C: Nav2 Launch Validation ===")
    nav2_params = NAV2_DIR / "config/nav2_params.yaml"
    check(nav2_params.exists(), f"Nav2 params file exists: {nav2_params}")

    data = load_yaml(nav2_params)
    if not data:
        check(False, "Nav2 params is valid YAML")
        return

    check("controller_server" in data, "Has controller_server")
    check("planner_server" in data, "Has planner_server")
    check("bt_navigator" in data, "Has bt_navigator")
    check("behavior_server" in data, "Has behavior_server")
    check("map_server" in data, "Has map_server")
    check("amcl" in data, "Has amcl")
    check("lifecycle_manager_navigation" in data, "Has lifecycle_manager_navigation")
    check("lifecycle_manager_localization" in data, "Has lifecycle_manager_localization")

    check("local_costmap" in data, "Has local_costmap section")
    check("global_costmap" in data, "Has global_costmap section")

    if "local_costmap" in data:
        lc = data["local_costmap"].get("ros__parameters", {})
        check(lc.get("global_frame") == "odom", "Local costmap global_frame=odom")
        check(lc.get("robot_base_frame") == "h1_ign", "Local costmap robot_base_frame=h1_ign")
        check(lc.get("footprint") == "[[-0.2, -0.15], [-0.2, 0.15], [0.2, 0.15], [0.2, -0.15]]", "Local costmap footprint matches H1-2 (0.4x0.3m)")
        obs = lc.get("plugins", [])
        check("obstacle_layer" in obs, "Local costmap has obstacle_layer")
        check("inflation_layer" in obs, "Local costmap has inflation_layer")
        obs_layer = lc.get("obstacle_layer", {})
        check(obs_layer.get("scan", {}).get("topic") == "/h1/lidar/scan", "Local costmap obstacle_layer uses /h1/lidar/scan")

    if "global_costmap" in data:
        gc = data["global_costmap"].get("ros__parameters", {})
        check(gc.get("global_frame") == "map", "Global costmap global_frame=map")
        check(gc.get("robot_base_frame") == "h1_ign", "Global costmap robot_base_frame=h1_ign")
        check(gc.get("footprint") == "[[-0.2, -0.15], [-0.2, 0.15], [0.2, 0.15], [0.2, -0.15]]", "Global costmap footprint matches H1-2")
        obs = gc.get("plugins", [])
        check("static_layer" in obs, "Global costmap has static_layer")
        check("obstacle_layer" in obs, "Global costmap has obstacle_layer")
        check("inflation_layer" in obs, "Global costmap has inflation_layer")
        static_layer = gc.get("static_layer", {})
        check(static_layer.get("map_subscribe_transient_local") is True, "Global costmap static_layer uses transient_local QoS")

    if "map_server" in data:
        ms = data["map_server"].get("ros__parameters", {})
        check(ms.get("yaml_filename") == "", "Map_server uses empty yaml_filename (map from SLAM)")

    if "amcl" in data:
        amcl = data["amcl"].get("ros__parameters", {})
        check(amcl.get("base_frame_id") == "h1_ign", "AMCL base_frame_id=h1_ign")
        check(amcl.get("odom_frame_id") == "odom", "AMCL odom_frame_id=odom")
        check(amcl.get("scan_topic") == "/h1/lidar/scan", "AMCL scan_topic=/h1/lidar/scan")
        check(amcl.get("use_sim_time") is True, "AMCL use_sim_time=true")

    for node in ["controller_server", "planner_server", "bt_navigator", "behavior_server", "map_server", "amcl"]:
        if node in data:
            params = data[node].get("ros__parameters", {})
            check(params.get("use_sim_time") is True, f"{node} use_sim_time=true")

    if "controller_server" in data:
        cs = data["controller_server"].get("ros__parameters", {})
        follow = cs.get("FollowPath", {})
        check(follow.get("plugin") == "dwb_core::DWBLocalPlanner", "Controller uses DWB planner")
        # Footprint is defined in local_costmap, not directly on controller_server
        lc_footprint = data.get("local_costmap", {}).get("ros__parameters", {}).get("footprint")
        check(lc_footprint == "[[-0.2, -0.15], [-0.2, 0.15], [0.2, 0.15], [0.2, -0.15]]", "Local costmap footprint matches H1-2 (0.4x0.3m)")

    nav2_launch = BRINGUP_DIR / "launch/nav2.launch.py"
    check(nav2_launch.exists(), f"Nav2 launch file exists: {nav2_launch}")

    content = nav2_launch.read_text()
    check("nav2_params_file" in content, "Nav2 launch declares nav2_params_file")
    check("use_sim_time" in content, "Nav2 launch passes use_sim_time")
    check("autostart" in content, "Nav2 launch has autostart")
    check("map" not in content or 'default_value=\'\'' in content or 'default_value=""' in content or "map': ''" in content, "Nav2 launch doesn't require static map file")


def verify_integrated_bringup():
    print("\n=== TASK D: Integrated Bringup Validation ===")
    headless_launch = BRINGUP_DIR / "launch/h1_headless.launch.py"
    check(headless_launch.exists(), f"Headless launch exists: {headless_launch}")

    content = headless_launch.read_text()
    check("slam" in content and "DeclareLaunchArgument" in content and "'slam'" in content, "Has slam launch argument")
    check("nav2" in content and "DeclareLaunchArgument" in content and "'nav2'" in content, "Has nav2 launch argument")
    check("IfCondition(slam)" in content, "SLAM included conditionally")
    check("IfCondition(nav2)" in content, "Nav2 included conditionally")
    check("slam.launch.py" in content, "Includes slam.launch.py")
    check("nav2.launch.py" in content, "Includes nav2.launch.py")

    bridge_file = BRINGUP_DIR / "config/ros_gz_h1_bridge.yaml"
    data = load_yaml(bridge_file)
    if data:
        required = [
            ("/h1/lidar/scan", "GZ_TO_ROS"),
            ("/cmd_vel", "ROS_TO_GZ"),
            ("/clock", "GZ_TO_ROS"),
            ("/imu", "GZ_TO_ROS"),
            ("/joint_states", "GZ_TO_ROS"),
            ("/tf", "GZ_TO_ROS"),
            ("/tf_static", "GZ_TO_ROS"),
            ("/h1/odometry", "GZ_TO_ROS"),
        ]
        for topic, direction in required:
            entry = next((e for e in data if e.get("ros_topic_name") == topic), None)
            check(entry is not None, f"Bridge has {topic}")
            if entry:
                check(entry.get("direction") == direction, f"Bridge {topic} direction={direction}")


def verify_topic_consistency():
    print("\n=== Cross-Component Topic Consistency ===")
    bridge_file = BRINGUP_DIR / "config/ros_gz_h1_bridge.yaml"
    slam_params = SLAM_DIR / "config/mapper_params_online_async.yaml"
    nav2_params = NAV2_DIR / "config/nav2_params.yaml"

    bridge_data = load_yaml(bridge_file)
    slam_data = load_yaml(slam_params)
    nav2_data = load_yaml(nav2_params)

    bridge_topics = {e.get("ros_topic_name") for e in bridge_data} if bridge_data else set()
    slam_scan = slam_data.get("slam_toolbox", {}).get("ros__parameters", {}).get("scan_topic") if slam_data else None
    nav2_scan = nav2_data.get("amcl", {}).get("ros__parameters", {}).get("scan_topic") if nav2_data else None

    check("/h1/lidar/scan" in bridge_topics, "Bridge publishes /h1/lidar/scan")
    check(slam_scan == "/h1/lidar/scan", f"SLAM expects /h1/lidar/scan (got {slam_scan})")
    check(nav2_scan == "/h1/lidar/scan", f"Nav2 AMCL expects /h1/lidar/scan (got {nav2_scan})")

    local_scan = nav2_data.get("local_costmap", {}).get("ros__parameters", {}).get("obstacle_layer", {}).get("scan", {}).get("topic") if nav2_data else None
    global_scan = nav2_data.get("global_costmap", {}).get("ros__parameters", {}).get("obstacle_layer", {}).get("scan", {}).get("topic") if nav2_data else None
    check(local_scan == "/h1/lidar/scan", f"Local costmap uses /h1/lidar/scan (got {local_scan})")
    check(global_scan == "/h1/lidar/scan", f"Global costmap uses /h1/lidar/scan (got {global_scan})")


def verify_launch_syntax():
    print("\n=== Launch File Syntax Validation ===")
    launch_files = [
        BRINGUP_DIR / "launch/h1_headless.launch.py",
        BRINGUP_DIR / "launch/slam.launch.py",
        BRINGUP_DIR / "launch/nav2.launch.py",
    ]

    # Source ROS environment
    env = os.environ.copy()
    env["PATH"] = "/opt/ros/jazzy/bin:" + env.get("PATH", "")
    for lf in launch_files:
        if lf.exists():
            rc, out, err = run_cmd(["ros2", "launch", "--show-args", str(lf)], env=env)
            check(rc == 0, f"Launch syntax valid: {lf.name}", err if rc != 0 else "")


def verify_yaml_syntax():
    print("\n=== YAML Syntax Validation ===")
    yaml_files = [
        BRINGUP_DIR / "config/ros_gz_h1_bridge.yaml",
        SLAM_DIR / "config/mapper_params_online_async.yaml",
        NAV2_DIR / "config/nav2_params.yaml",
    ]

    for yf in yaml_files:
        if yf.exists():
            try:
                with open(yf) as f:
                    yaml.safe_load(f)
                check(True, f"YAML syntax valid: {yf.name}")
            except Exception as e:
                check(False, f"YAML syntax valid: {yf.name}", str(e))


def main():
    print("=" * 60)
    print("M6 SLAM + Nav2 Configuration Verification")
    print("=" * 60)

    verify_yaml_syntax()
    verify_bridge_config()
    verify_slam_config()
    verify_nav2_config()
    verify_integrated_bringup()
    verify_topic_consistency()
    verify_launch_syntax()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for r in results if r[0])
    failed = sum(1 for r in results if not r[0])
    for condition, msg, details in results:
        status = PASS if condition else FAIL
        print(f"[{status}] {msg}")

    print(f"\nTotal: {len(results)}, Passed: {passed}, Failed: {failed}")

    if failed == 0:
        print(f"\n{PASS} ALL CHECKS PASSED")
        return 0
    else:
        print(f"\n{FAIL} {failed} CHECK(S) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())