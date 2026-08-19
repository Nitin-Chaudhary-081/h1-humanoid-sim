#!/usr/bin/env bash
exec env -i PATH=/usr/bin:/bin:/opt/ros/jazzy/bin HOME=/home/ubuntu LANG=C.UTF-8 \
  bash -c 'source /opt/ros/jazzy/setup.bash && source /home/ubuntu/humanoid_sim_ws/install/setup.bash && exec ros2 run h1_visualization viz_node'