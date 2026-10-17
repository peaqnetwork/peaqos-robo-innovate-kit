#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash
source /dsr_ws/install/setup.bash
source /opt/kit-venv/bin/activate
# keep each team's DDS traffic to itself on shared Wi-Fi
export ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-1}"
exec "$@"
