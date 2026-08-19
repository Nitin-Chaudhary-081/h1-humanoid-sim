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
check_pub /h1/telemetry "" "h1/telemetry"
check_pub /h1/alerts "" "h1/alerts"
check_pub /anomaly_flag "" "anomaly_flag"
check_pub /h1/control_markers "" "h1/control_markers"
check_pub /h1/llm/intent "" "h1/llm/intent"

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

if pgrep -f "[r]un_server.py" >/dev/null; then
  echo "PASS: control server process alive"
else
  echo "FAIL: control server process dead"
  fail=1
fi

if pgrep -f "[v]iz_node" >/dev/null; then
  echo "PASS: viz node process alive"
else
  echo "FAIL: viz node process dead"
  fail=1
fi

if pgrep -f "[h]1_llm_agent" >/dev/null; then
  echo "PASS: llm agent process alive"
else
  echo "FAIL: llm agent process dead"
  fail=1
fi

if pgrep -f "[h]1_telemetry" >/dev/null; then
  echo "PASS: telemetry node process alive"
else
  echo "FAIL: telemetry node process dead"
  fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "SMOKE OK"
  exit 0
else
  echo "SMOKE FAILED"
  exit 1
fi
