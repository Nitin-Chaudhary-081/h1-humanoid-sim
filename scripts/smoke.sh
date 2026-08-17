#!/usr/bin/env bash
set -eo pipefail
export AMENT_TRACE_SETUP_FILES=""
source /opt/ros/jazzy/setup.bash
source /home/ubuntu/humanoid_sim_ws/install/setup.bash

fail=0

check_pub() {
  local topic=$1
  local qos=$2
  local label=$3
  if timeout 20 ros2 topic echo "$topic" --once ${qos:+$qos} >/dev/null 2>&1; then
    echo "PASS: $label publishing"
  else
    echo "FAIL: $label NOT publishing"
    fail=1
  fi
}

check_pub /joint_states "" "joint_states"
check_pub /h1/odometry "--qos-reliability best_effort" "h1/odometry"
check_pub /clock "" "clock"

if pgrep -f "gz sim" >/dev/null || pgrep -f "gz-server" >/dev/null; then
  echo "PASS: gz server process alive"
else
  echo "FAIL: gz server process dead"
  fail=1
fi

if pgrep -f foxglove_bridge >/dev/null; then
  echo "PASS: foxglove bridge alive"
else
  echo "FAIL: foxglove bridge dead"
  fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "SMOKE OK"
  exit 0
else
  echo "SMOKE FAILED"
  exit 1
fi
