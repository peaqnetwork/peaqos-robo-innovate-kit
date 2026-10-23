# Running the emulator and the kit in a container

For laptops without native Ubuntu 22.04, including Apple Silicon Macs. The doosan launch file starts Doosan's emulator (`doosanrobot/dsr_emulator`, amd64-only; runs under Rosetta on Apple Silicon at roughly 4 CPU cores and 700 MiB while idle) as a *sibling* container, which is why the host Docker socket is mounted.

The commands use `--network host`. On Docker Desktop (Mac, Windows) that needs Docker Desktop 4.34 or newer with host networking turned on: Settings → Resources → Network → Enable host networking, then Apply and restart (you have to be signed in to a Docker account).

```bash
# from the kit root. First build takes ~10 min; the built image is ~4.6 GB, the emulator image ~1.8 GB.
docker build -t peaqos-arm-kit -f docker/Dockerfile .

# shell 1: the driver + emulator (RViz will complain about X; ignore it)
docker run --rm -it --network host \
  -v /var/run/docker.sock:/var/run/docker.sock peaqos-arm-kit \
  ros2 launch dsr_bringup2 dsr_bringup2_rviz.launch.py mode:=virtual model:=a0509

# shell 2: the kit, same image. It does not need the Docker socket: only the
# launch in shell 1 starts the emulator container. Keep the socket out of the
# container that holds your .env.
docker run --rm -it --network host \
  -v "$PWD":/kit -w /kit peaqos-arm-kit \
  bash -c 'ros2 topic hz /dsr01/joint_states'
# test run first: nothing sent, its own folder
docker run --rm -it --network host -e KIT_LOG_DIR=./dev-log -v "$PWD":/kit -w /kit peaqos-arm-kit \
  armkit record --source ros2
# the run you hand in
docker run --rm -it --network host -v "$PWD":/kit -w /kit peaqos-arm-kit \
  armkit record --source ros2 --live
```

Stop shell 1 with Ctrl-C: that also removes the emulator container. After `docker stop` the emulator keeps running (about 4 CPU cores); remove it with `docker rm -f dsr01_emulator`.

`-v "$PWD":/kit` mounts your kit folder, so `.env` and `motion-log/` live on your laptop, not in the container.

**At the event, load the images from the mentors' USB stick** instead of building or pulling them over the Wi-Fi: `docker load -i peaqos-arm-kit-arm64.tar` on Apple Silicon or `docker load -i peaqos-arm-kit-amd64.tar` on x86 (`uname -m` tells you which), then `docker load -i dsr_emulator-3.0.1.tar`. Both kit files load as `peaqos-arm-kit:latest`, so skip the build step.
