from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Protocol


@dataclass(frozen=True)
class JointSample:
    """One joint-state reading.

    ``t`` is seconds (Unix time for live sources, any monotonic base for
    replays). ``positions`` are radians in joint order; ``velocities`` are
    rad/s if the controller reports them, otherwise ``None`` and the
    segmenter differentiates positions.
    """

    t: float
    names: tuple[str, ...]
    positions: tuple[float, ...]
    velocities: tuple[float, ...] | None = None


class JointSource(Protocol):
    def samples(self) -> Iterator[JointSample]: ...

    def close(self) -> None: ...
