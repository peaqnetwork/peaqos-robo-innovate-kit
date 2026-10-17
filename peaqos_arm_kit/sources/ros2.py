"""ROS 2 joint-state source for the Doosan A0509 (doosan-robot2).

Subscribes to a ``sensor_msgs/msg/JointState`` topic (``/dsr01/joint_states``
with the default namespace) and yields samples as they arrive. Needs a
sourced ROS 2 environment (rclpy is not a pip dependency). See docs/ARM.md.

Joints are sorted by name, so the recorded order is ``joint_1 … joint_6``
even though doosan-robot2 publishes them as ``1, 2, 4, 5, 3, 6``.
Some publishers send an all-zero ``velocity`` array while moving (seen in one Doosan
emulator run); the segmenter ignores zero vectors and differentiates positions instead.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Iterator

from .base import JointSample

log = logging.getLogger("armkit.ros2")


class Ros2JointStates:
    def __init__(self, topic: str = "/dsr01/joint_states", *, queue_size: int = 20000) -> None:
        try:
            import rclpy  # noqa: F401
            from sensor_msgs.msg import JointState  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on ROS install
            raise RuntimeError(
                "rclpy / sensor_msgs not importable. Source your ROS 2 setup.bash "
                "(and the doosan-robot2 workspace) before running with KIT_JOINT_SOURCE=ros2."
            ) from exc
        self.topic = topic
        self.dropped = 0
        self._q: queue.Queue[JointSample | None] = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, name="armkit-ros2", daemon=True)
        self._thread.start()

    def _spin(self) -> None:  # pragma: no cover - needs ROS
        import rclpy
        from rclpy.node import Node
        from sensor_msgs.msg import JointState

        rclpy.init()
        node = Node("peaqos_arm_kit")

        def on_msg(msg: JointState) -> None:
            stamp = msg.header.stamp
            t = stamp.sec + stamp.nanosec * 1e-9
            if t == 0.0:
                t = node.get_clock().now().nanoseconds * 1e-9
            order = sorted(range(len(msg.name)), key=lambda i: msg.name[i])
            names = tuple(msg.name[i] for i in order)
            positions = tuple(msg.position[i] for i in order)
            vel = tuple(msg.velocity[i] for i in order) if len(msg.velocity) == len(msg.position) else None
            sample = JointSample(t=t, names=names, positions=positions, velocities=vel)
            try:
                self._q.put_nowait(sample)
            except queue.Full:
                self.dropped += 1
                if self.dropped in (1, 100, 1000) or self.dropped % 10000 == 0:
                    log.warning("joint-state queue full: %d samples dropped so far", self.dropped)

        from rclpy.qos import qos_profile_sensor_data

        # best-effort subscriber: compatible with reliable AND best-effort JointState publishers
        node.create_subscription(JointState, self.topic, on_msg, qos_profile_sensor_data)
        try:
            while not self._stop.is_set() and rclpy.ok():
                rclpy.spin_once(node, timeout_sec=0.1)
        except Exception as exc:  # Ctrl-C shuts rclpy down under us (ExternalShutdownException)
            if rclpy.ok():
                log.warning("ROS 2 spin stopped: %s", exc)
        finally:
            try:
                node.destroy_node()
                if rclpy.ok():
                    rclpy.shutdown()
            except Exception:  # already shut down by the signal handler
                pass
            self._q.put(None)

    def samples(self) -> Iterator[JointSample]:
        while True:
            item = self._q.get()
            if item is None:
                return
            yield item

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        if self.dropped:
            log.warning("ROS 2 source dropped %d samples in total", self.dropped)
