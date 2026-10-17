"""A fake six-axis arm: moves, pauses, moves again. Lets the whole pipeline
run on a laptop with no robot attached."""

from __future__ import annotations

import math
import random
import time
from typing import Iterator

from .base import JointSample

JOINT_NAMES = ("joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6")


class SyntheticArm:
    def __init__(
        self,
        *,
        rate_hz: float = 50.0,
        moves: int = 5,
        move_seconds: float = 2.0,
        pause_seconds: float = 1.5,
        realtime: bool = True,
        seed: int | None = 7,
    ) -> None:
        self.rate_hz = rate_hz
        self.moves = moves
        self.move_seconds = move_seconds
        self.pause_seconds = pause_seconds
        self.realtime = realtime
        self._rng = random.Random(seed)

    def samples(self) -> Iterator[JointSample]:
        dt = 1.0 / self.rate_hz
        t = time.time() if self.realtime else 0.0
        q = [0.0, -0.3, 0.9, 0.0, 1.2, 0.0]
        for _ in range(self.moves):
            # pause
            for _ in range(int(self.pause_seconds * self.rate_hz)):
                yield self._emit(t, q)
                t += dt
                if self.realtime:
                    time.sleep(dt)
            # move: smooth cosine ramp to a new target
            target = [qi + self._rng.uniform(-0.8, 0.8) for qi in q]
            start = list(q)
            n = int(self.move_seconds * self.rate_hz)
            for k in range(1, n + 1):
                s = 0.5 - 0.5 * math.cos(math.pi * k / n)
                q = [a + (b - a) * s for a, b in zip(start, target)]
                yield self._emit(t, q)
                t += dt
                if self.realtime:
                    time.sleep(dt)
        for _ in range(int(self.pause_seconds * self.rate_hz)):
            yield self._emit(t, q)
            t += dt
            if self.realtime:
                time.sleep(dt)

    @staticmethod
    def _emit(t: float, q: list[float]) -> JointSample:
        return JointSample(t=t, names=JOINT_NAMES, positions=tuple(q))

    def close(self) -> None:
        return None
