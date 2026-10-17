# The robot: what you record from

The kit needs one thing: a ROS 2 `sensor_msgs/msg/JointState` topic. Where it comes from is up to you, and you declare it: the `source` of every recorded segment is written into the hashed document (`ros2:/dsr01/joint_states`, `csv:<file>`, `synthetic`). The run you hand in comes from the Doosan emulator, another ROS 2 simulator, or a real robot. Synthetic and CSV are for building and testing.

## The real A0509 on site

Driven by peaq's pendant module, which anchors its demo movements under the arm's peaqID (`1508…4755`, already in `.env.example`). Teams do not connect to it, cannot run their own programs on it, and cannot export its motion data. `armkit status --arm` reads its events back.

## Option A: the Doosan emulator (recommended)

doosan-robot2's virtual mode runs the A0509 controller in Doosan's emulator container and publishes `/dsr01/joint_states` like the real arm. Native route: x86-64 Ubuntu 22.04 with Docker and ROS 2 Humble. Everything else (Apple Silicon, Windows via WSL2, other distros): use the container in [`docker/`](../docker/README.md).

Native setup, tested order of operations:

```bash
# once: workspace
mkdir -p ~/dsr_ws/src && cd ~/dsr_ws/src
git clone -b humble https://github.com/DoosanRobotics/doosan-robot2.git
cd ~/dsr_ws
sudo apt-get update && rosdep update            # without these, rosdep install silently installs nothing
rosdep install -r --from-paths src --ignore-src -y
colcon build --packages-skip dsr_gazebo2        # Gazebo Classic is not needed for the emulator path
source install/setup.bash

# emulator + driver (pulls doosanrobot/dsr_emulator, ~1.8 GB, on first run: do this before the event)
ros2 launch dsr_bringup2 dsr_bringup2_rviz.launch.py mode:=virtual model:=a0509
```

RViz is launched too and crashes if there is no display ("Couldn't open X display"). Harmless; the driver keeps running. Launch file and argument names are from the doosan-robot2 README for Humble: check them against the branch you check out.

```bash
ros2 topic hz /dsr01/joint_states          # steady rate, six joints
```

Two things about this topic that the kit already handles: the `velocity` array is all zeros while the arm moves (the kit differentiates positions instead), and the joints arrive as `joint_1, joint_2, joint_4, joint_5, joint_3, joint_6` (the kit sorts them by name, so recorded order is 1 to 6).

Move the emulated arm any way you like (RViz/MoveIt, `dsr_msgs` service calls, a DRL script), and every motion that clears the velocity threshold becomes a segment. Each anchored segment costs ~0.04 PEAQ, so develop with `armkit record` (dry run) and go `--live` for the runs you mean. Keep the two apart: dry runs in their own folder (`KIT_LOG_DIR=./dev-log armkit record`), and only `--live` runs in the `motion-log/` you hand in, because `verify` fails on dry-run segments. Never delete `motion-log/` after anchoring and never record `--live` from two folders against one machine ID: events on chain with no segment in the log fail verification, and nothing can remove an event from the chain.

## Shared Wi-Fi

Every team on the venue network with the default `ROS_DOMAIN_ID=0` sees everyone else's `/dsr01/joint_states`. Set one of these in every shell before launching anything:

```bash
export ROS_LOCALHOST_ONLY=1          # simplest: everything stays on your laptop
# or
export ROS_DOMAIN_ID=<your team number, 1-101>
```

## Option B: your own robot or simulator

Anything that publishes `JointState` works: MoveIt demos, Gazebo, Isaac Sim's ROS 2 bridge, a desktop arm. Point `KIT_ROS2_TOPIC` at the topic. Joint count and names are recorded as-is (sorted by name); nothing in the kit assumes six axes.

## Option C: no ROS at all (building and testing only)

`KIT_JOINT_SOURCE=synthetic` is a fake six-axis arm that moves and pauses. `KIT_JOINT_SOURCE=csv` replays a log (`data/sample_joint_log.csv` is included; record your own with `ros2 bag` and convert to `t, joint_1 … joint_n`). Use them to develop the open part without spending PEAQ; the hand-in run comes from A or B.

## Running the kit against ROS 2

rclpy is not pip-installable, so the kit's venv must see the system ROS packages. On Ubuntu 22.04 that means a venv made with the system `python3` (3.10, the one ROS 2 Humble is built for), not the Python 3.12 venv from the README quick start. ROS 2 Humble ships pip 22 / setuptools 59, which cannot do editable installs without an upgrade:

```bash
deactivate 2>/dev/null  # leave the Python 3.12 quick-start venv
cd ~/peaqos-robo-innovate-kit   # back to your kit folder (wherever you cloned it)
source /opt/ros/humble/setup.bash && source ~/dsr_ws/install/setup.bash
/usr/bin/python3 -m venv --system-site-packages .venv-ros && source .venv-ros/bin/activate
pip install -U pip && pip install -e .
KIT_JOINT_SOURCE=ros2 KIT_ROS2_TOPIC=/dsr01/joint_states armkit record --live
```

Ctrl-C closes the move in progress and waits for pending anchors before exiting.
