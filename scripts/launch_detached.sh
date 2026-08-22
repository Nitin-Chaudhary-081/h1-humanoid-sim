#!/bin/bash
# Detached launcher for a ROS node (no hang, survives tool shell exit).
# Usage: launch_detached.sh <logfile> <rest...>  -- runs "rest..." in background
# Creates the logfile's directory if missing and prints the detached PID.
LOG="$1"; shift
if [ -z "$LOG" ] || [ $# -eq 0 ]; then
  echo "usage: $0 <logfile> <command> [args...]" >&2
  exit 2
fi
mkdir -p "$(dirname "$LOG")"
setsid "$@" >"$LOG" 2>&1 </dev/null &
pid=$!
disown
echo "$pid"
exit 0
