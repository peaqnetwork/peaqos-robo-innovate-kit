# The robot you record from

The kit records any ROS 2 `sensor_msgs/msg/JointState` topic. Every segment stores where it came from (`ros2:/dsr01/joint_states`, `csv:<file>` or `synthetic`). The run you hand in comes from the Doosan emulator, another ROS 2 simulator or a real robot; synthetic and CSV are for building and testing.

## Option A: the Doosan A0509 emulator (recommended)

Doosan's emulator runs the A0509 controller and publishes `/dsr01/joint_states` like the real arm. On x86-64 Ubuntu 22.04 with ROS 2 Humble and Docker, set it up natively as below. On a Mac, on Windows (WSL2) or any other system, use the [Docker setup](../docker/README.md) instead.

```bash
# once: build the Doosan workspace
mkdir -p ~/dsr_ws/src && cd ~/dsr_ws/src
git clone -b humble https://github.com/DoosanRobotics/doosan-robot2.git
cd ~/dsr_ws
sudo apt-get update && rosdep update            # without these, rosdep installs nothing
rosdep install -r --from-paths src --ignore-src -y
colcon build --packages-skip dsr_gazebo2
source install/setup.bash

# start the emulator and driver (the first run pulls a 1.8 GB image: do it before the event)
ros2 launch dsr_bringup2 dsr_bringup2_rviz.launch.py mode:=virtual model:=a0509

# in another terminal: you should see a steady rate
ros2 topic hz /dsr01/joint_states
```

If RViz crashes with "Couldn't open X display", ignore it: the driver keeps running.

Move the emulated arm any way you like (RViz/MoveIt, `dsr_msgs2` service calls, a DRL script). Every move above the velocity threshold becomes a segment. The quickest first move, in another terminal with ROS sourced (angles in degrees):

```bash
ros2 service call /dsr01/motion/move_joint dsr_msgs2/srv/MoveJoint "{pos: [30.0, 0.0, 90.0, 0.0, 90.0, 0.0], vel: 30.0, acc: 30.0}"
ros2 service call /dsr01/motion/move_joint dsr_msgs2/srv/MoveJoint "{pos: [0.0, 0.0, 90.0, 0.0, 90.0, 0.0], vel: 30.0, acc: 30.0}"
```

If it answers `success=False`, put the controller in autonomous mode once: `ros2 service call /dsr01/system/set_robot_mode dsr_msgs2/srv/SetRobotMode "{robot_mode: 1}"`.

## Option B: your own robot or simulator

Anything that publishes `JointState` works: MoveIt demos, Gazebo, Isaac Sim's ROS 2 bridge, a desktop arm. Set `KIT_ROS2_TOPIC` to your topic. Any number of joints works.

## Option C: no ROS (building and testing only)

`--source synthetic` is a fake six-axis arm; `--source csv` replays `data/sample_joint_log.csv` or your own file (columns `t, joint_1 … joint_n`). Useful for building your project without spending PEAQ. They don't count for the hand-in.

## Recording from ROS 2 on Ubuntu

ROS 2 Humble's Python packages (`rclpy`) can't be installed with pip, so the kit needs a venv on the system Python 3.10 that can see them:

```bash
deactivate 2>/dev/null                    # leave the Python 3.12 quick-start venv
cd ~/peaqos-robo-innovate-kit             # your kit folder
source /opt/ros/humble/setup.bash && source ~/dsr_ws/install/setup.bash
/usr/bin/python3 -m venv --system-site-packages .venv-ros && source .venv-ros/bin/activate
pip install -U pip && pip install -e .
export ROS_LOCALHOST_ONLY=1               # shared Wi-Fi: only see your own robot
KIT_JOINT_SOURCE=ros2 KIT_LOG_DIR=./dev-log armkit record    # test run, nothing sent
KIT_JOINT_SOURCE=ros2 armkit record --live                   # the run you hand in
```

Ctrl-C closes the move in progress and waits for the last events to land.
