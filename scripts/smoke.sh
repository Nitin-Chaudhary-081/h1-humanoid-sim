#!/usr/bin/env bash
# smoke.sh — headless-sim integration gate (run after every merge).
#
# IDEMPOTENT / READ-ONLY: only inspects topics, actions, processes and log
# files. Never starts, kills, or writes anything — safe to run repeatedly
# against a live sim.
#
# Checks:
#   PASS/FAIL  core topics + processes + /h1/command action (M2)
#   WARN       optional topics/actions (M3-M6): missing = noted, not fatal
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

# Optional topics (M3-M6): WARN only — a temporarily missing topic must not
# fail the whole gate (nodes may not be started / sim may be mid-restart).
warn_pub() {
  local topic=$1
  local qos=$2
  local label=$3
  if timeout 20 ros2 topic echo "$topic" --once ${qos:+$qos} >/dev/null 2>&1; then
    echo "PASS: $label publishing"
  else
    echo "WARN: $label not publishing (optional — checked presence only)"
  fi
}

# Optional topics whose data may be latched/transient (e.g. /map): just check
# they exist in the ROS graph instead of waiting for a sample.
warn_topic_presence() {
  local topic=$1
  local label=$2
  if timeout 20 ros2 topic list | grep -qx "$topic"; then
    echo "PASS: $label present in graph"
  else
    echo "WARN: $label absent from graph (optional)"
  fi
}

check_action() {
  local action=$1
  local label=$2
  if timeout 20 ros2 action list | grep -q "^$action$"; then
    echo "PASS: $label action server up"
  else
    echo "FAIL: $label action server DOWN"
    fail=1
  fi
}

warn_action() {
  local action=$1
  local label=$2
  if timeout 20 ros2 action list | grep -q "^$action$"; then
    echo "PASS: $label action server up"
  else
    echo "WARN: $label action server down (optional)"
  fi
}

# --- M1/M2 core topics (FAIL) ---------------------------------------------
check_pub /joint_states "" "joint_states"
check_pub /h1/odometry "--qos-reliability best_effort" "h1/odometry"
check_pub /clock "" "clock"

# --- M4 telemetry / anomaly (FAIL — core data path) -----------------------
check_pub /h1/telemetry "" "h1/telemetry"
check_pub /h1/alerts "" "h1/alerts"
check_pub /anomaly_flag "" "anomaly_flag"

# --- M2/M4 visualization (FAIL — core) -------------------------------------
check_pub /h1/control_markers "" "h1/control_markers"
check_pub /h1/llm/intent "" "h1/llm/intent"

# --- M3 LLM observability (WARN — agent may be in mock/stopped) ------------
warn_pub /h1/llm/input_text "" "h1/llm/input_text"
warn_pub /h1/llm/events "" "h1/llm/events"
if [ -s /home/ubuntu/humanoid_sim_ws/data/llm_audit.jsonl ]; then
  echo "PASS: llm audit log file present with content"
else
  echo "WARN: llm audit log file missing/empty (optional — written on first agent turn)"
fi

# --- M5 perception / grasp / moveit (WARN — nodes optional) ----------------
warn_pub /h1/perception/detections "" "h1/perception/detections"
warn_action /h1/moveit/follow_trajectory "h1/moveit/follow_trajectory"
warn_action /h1/grasp/execute "h1/grasp/execute"

# --- M6 SLAM + Nav2 (WARN — needs lidar + slam node running) ---------------
warn_pub /h1/lidar/scan "--qos-reliability best_effort" "h1/lidar/scan"
warn_topic_presence /map "map (slam_toolbox)"
warn_topic_presence /map_metadata "map_metadata (slam_toolbox)"

# --- M2 command action server (FAIL — core) --------------------------------
check_action /h1/command "h1/command"

# --- Processes (FAIL) -------------------------------------------------------
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
