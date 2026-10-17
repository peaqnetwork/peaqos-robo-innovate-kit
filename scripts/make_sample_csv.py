#!/usr/bin/env python3
"""Write data/sample_joint_log.csv from the synthetic arm (deterministic)."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from peaqos_arm_kit.sources.synthetic import SyntheticArm  # noqa: E402

out = Path(__file__).resolve().parents[1] / "data" / "sample_joint_log.csv"
arm = SyntheticArm(realtime=False, moves=4, seed=7)
with out.open("w", newline="") as fh:
    w = csv.writer(fh)
    first = True
    for s in arm.samples():
        if first:
            w.writerow(["t", *s.names])
            first = False
        w.writerow([f"{s.t:.3f}", *[f"{q:.6f}" for q in s.positions]])
print(out)
