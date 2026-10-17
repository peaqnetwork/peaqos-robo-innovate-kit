# ROS 2 Humble + doosan-robot2 + the peaqOS arm kit, for machines without a native
# Ubuntu 22.04 install, including Apple Silicon. The Doosan emulator itself runs as
# a sibling container started by the doosan launch file, so this image needs the
# host's Docker socket (see docker/README.md).
#
# Recipe tested on an Apple Silicon Mac. If `colcon build` fails, ask a mentor.
FROM ros:humble-ros-base

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        git python3-pip python3-venv python3-colcon-common-extensions \
        docker.io libpoco-dev libyaml-cpp-dev ros-humble-rviz2 \
    && rm -rf /var/lib/apt/lists/*

# doosan-robot2 (Humble). dsr_gazebo2 is skipped: no Gazebo Classic packages on arm64,
# and the emulator path does not need it.
WORKDIR /dsr_ws
RUN git clone -b humble https://github.com/DoosanRobotics/doosan-robot2.git src/doosan-robot2 \
    && apt-get update && rosdep update \
    && rosdep install -r --from-paths src --ignore-src -y || true \
    && rm -rf /var/lib/apt/lists/*
RUN . /opt/ros/humble/setup.sh && colcon build --packages-skip dsr_gazebo2

# the kit, in a venv that can see the ROS Python packages. The venv lives outside
# /kit: the docs mount the team's kit folder over /kit, which would hide it. The
# editable install points at /kit, so the mounted folder's code is what runs.
WORKDIR /kit
COPY . /kit
RUN python3 -m venv --system-site-packages /opt/kit-venv \
    && /opt/kit-venv/bin/pip install -U pip \
    && /opt/kit-venv/bin/pip install -e /kit

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
