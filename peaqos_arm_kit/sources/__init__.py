"""Joint-state sources. Each yields :class:`JointSample` objects in time order."""

from .base import JointSample, JointSource

__all__ = ["JointSample", "JointSource", "open_source"]


def open_source(kind: str, *, csv_path=None, topic: str = "/dsr01/joint_states", realtime: bool = True):
    """Build a source by name: ``synthetic``, ``csv`` or ``ros2``."""
    if kind == "synthetic":
        from .synthetic import SyntheticArm

        return SyntheticArm(realtime=realtime)
    if kind == "csv":
        from .csv_replay import CsvReplay

        if csv_path is None:
            raise ValueError("csv source needs csv_path")
        return CsvReplay(csv_path, realtime=realtime)
    if kind == "ros2":
        from .ros2 import Ros2JointStates

        return Ros2JointStates(topic)
    raise ValueError(f"unknown joint source {kind!r} (expected synthetic, csv or ros2)")
