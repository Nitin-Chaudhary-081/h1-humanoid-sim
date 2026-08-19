#!/bin/bash
# Detached launcher for a ROS node (no hang, survives tool shell exit).
# Usage: launch_detached.sh <logfile> <rest...>  -- runs "rest..." in background
LOG="$1"; shift
setsid "$@" >"$LOG" 2>&1 </dev/null &
disown
exit 0