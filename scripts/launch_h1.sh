#!/usr/bin/env bash
set -eo pipefail
export AMENT_TRACE_SETUP_FILES=""
source /opt/ros/jazzy/setup.bash
source /home/ubuntu/humanoid_sim_ws/install/setup.bash
cd /home/ubuntu/humanoid_sim_ws
exec ros2 launch h1_bringup h1_headless.launch.py "$@"