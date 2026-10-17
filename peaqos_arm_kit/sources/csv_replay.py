"""Replay a CSV of joint states.

Expected columns: ``t`` (seconds) then one column per joint, e.g.
``t,joint_1,joint_2,joint_3,joint_4,joint_5,joint_6``. Optional velocity
columns named ``<joint>_vel`` are used when present.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Iterator

from .base import JointSample


class CsvReplay:
    def __init__(self, path: str | Path, *, realtime: bool = True) -> None:
        self.path = Path(path)
        self.realtime = realtime

    def samples(self) -> Iterator[JointSample]:
        with self.path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None or "t" not in reader.fieldnames:
                raise ValueError(f"{self.path}: first column must be 't'")
            joint_cols = [c for c in reader.fieldnames if c != "t" and not c.endswith("_vel")]
            vel_cols = [f"{c}_vel" for c in joint_cols]
            has_vel = all(v in reader.fieldnames for v in vel_cols)
            names = tuple(joint_cols)
            prev_t: float | None = None
            for row in reader:
                t = float(row["t"])
                if self.realtime and prev_t is not None and t > prev_t:
                    time.sleep(min(t - prev_t, 1.0))
                prev_t = t
                positions = tuple(float(row[c]) for c in joint_cols)
                velocities = tuple(float(row[v]) for v in vel_cols) if has_vel else None
                yield JointSample(t=t, names=names, positions=positions, velocities=velocities)

    def close(self) -> None:
        return None
