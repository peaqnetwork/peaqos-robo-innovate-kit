# Running the emulator and the kit in a container

## At the event: load the images, don't build

Load the images from the mentors' USB stick instead of building or pulling them over the Wi-Fi: `docker load -i peaqos-arm-kit-arm64.tar` on Apple Silicon or `docker load -i peaqos-arm-kit-amd64.tar` on x86 (`uname -m` tells you which), then `docker load -i dsr_emulator-3.0.1.tar`. Both kit files load as `peaqos-arm-kit:latest`, so skip the build step.

Run `setup.sh`, `armkit check` and `armkit verify` on your laptop in `.venv` (README steps 2 and 5). Only the emulator and `armkit record` run in the container.

## Setup

For laptops without native Ubuntu 22.04, including Apple Silicon Macs. The doosan launch file starts Doosan's emulator (`doosanrobot/dsr_emulator`, amd64-only; runs under Rosetta on Apple Silicon at roughly 4 CPU cores and 700 MiB while idle) as a *sibling* container, which is why the host Docker socket is mounted.

The commands use `--network host`. On Docker Desktop (Mac, Windows) that needs Docker Desktop 4.34 or newer with host networking turned on: Settings → Resources → Network → Enable host networking, then Apply and restart (you have to be signed in to a Docker account).

All commands run from your kit folder. Without the USB images, build first (about 10 minutes; the image is about 4.6 GB, the emulator image about 1.8 GB):

```bash
docker build -t peaqos-arm-kit -f docker/Dockerfile .
```

**Shell 1: the driver and the emulator.** RViz will complain about X; ignore it.

```bash
docker run --rm -it --network host -v /var/run/docker.sock:/var/run/docker.sock peaqos-arm-kit ros2 launch dsr_bringup2 dsr_bringup2_rviz.launch.py mode:=virtual model:=a0509
```

**Shell 2: the kit, same image.** It doesn't need the Docker socket (only shell 1 starts the emulator), so keep the socket out of the container that holds your `.env`. First check the emulator publishes: wait for a steady rate, then Ctrl-C.

```bash
docker run --rm -it --network host -v "$PWD":/kit -w /kit peaqos-arm-kit ros2 topic hz /dsr01/joint_states
```

A test run first, nothing sent, in its own folder:

```bash
docker run --rm -it --network host -e KIT_LOG_DIR=./dev-log -v "$PWD":/kit -w /kit peaqos-arm-kit armkit record --source ros2
```

The run you hand in:

```bash
docker run --rm -it --network host -v "$PWD":/kit -w /kit peaqos-arm-kit armkit record --source ros2 --live
```

**Shell 3: make the arm move** while a record command runs. Angles are in degrees; each call is one move.

```bash
docker run --rm -it --network host peaqos-arm-kit ros2 service call /dsr01/motion/move_joint dsr_msgs2/srv/MoveJoint "{pos: [30.0, 0.0, 90.0, 0.0, 90.0, 0.0], vel: 30.0, acc: 30.0}"
```

```bash
docker run --rm -it --network host peaqos-arm-kit ros2 service call /dsr01/motion/move_joint dsr_msgs2/srv/MoveJoint "{pos: [0.0, 0.0, 90.0, 0.0, 90.0, 0.0], vel: 30.0, acc: 30.0}"
```

If it answers `success=False`, put the controller in autonomous mode once: the same `docker run` with `ros2 service call /dsr01/system/set_robot_mode dsr_msgs2/srv/SetRobotMode "{robot_mode: 1}"`.

Stop shell 1 with Ctrl-C: that also removes the emulator container. After `docker stop` the emulator keeps running (about 4 CPU cores); remove it with `docker rm -f dsr01_emulator`.

`-v "$PWD":/kit` mounts your kit folder, so `.env` and `motion-log/` live on your laptop, not in the container.
