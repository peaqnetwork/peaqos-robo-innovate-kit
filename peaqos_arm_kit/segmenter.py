"""Turn a stream of joint samples into motion segments.

A segment starts when any joint's speed rises above ``velocity_threshold``
and ends once every joint has been below it for ``settle_seconds``. The
settle tail is kept in the segment (it shows the arm coming to rest) but does
not count toward its length: a segment whose *active* motion is shorter than
``min_segment_seconds`` is dropped as jitter. A segment longer than
``max_segment_seconds`` is closed and a new one started, so one long
continuous motion becomes several events rather than one enormous payload.

Use ``feed(sample)`` per sample (returns closed segments) and ``flush()`` at
end of stream (including on Ctrl-C), so the move in progress is not lost.
``segments(iterable)`` wraps both for the simple case.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterable, Iterator

from .sources.base import JointSample


@dataclass
class MotionSegment:
    index: int
    names: tuple[str, ...]
    samples: list[JointSample] = field(default_factory=list)
    last_moving_t: float = 0.0
    first_moving_t: float | None = None  # when motion was first detected (None: the first sample)
    active_pad: float = 0.0  # correction for the differentiation window, see feed()

    @property
    def start_t(self) -> float:
        return self.samples[0].t

    @property
    def end_t(self) -> float:
        return self.samples[-1].t

    @property
    def duration(self) -> float:
        return self.end_t - self.start_t

    @property
    def active_duration(self) -> float:
        first = self.start_t if self.first_moving_t is None else self.first_moving_t
        return self.last_moving_t - first + self.active_pad


DIFF_WINDOW_SECONDS = 0.1  # differentiate positions over this span, not sample to sample


def _speeds(ref: JointSample, cur: JointSample) -> tuple[float, ...]:
    # Reported velocities are used only when they carry information: the Doosan
    # emulator publishes an all-zero velocity array while moving, so a zero
    # vector falls through to differentiating positions. ``ref`` is a sample about
    # DIFF_WINDOW_SECONDS back, so sub-milliradian position noise at 50-100 Hz
    # does not read as motion.
    if cur.velocities is not None and any(v != 0.0 for v in cur.velocities):
        return tuple(abs(v) for v in cur.velocities)
    dt = cur.t - ref.t
    if dt <= 0:
        return tuple(0.0 for _ in cur.positions)
    return tuple(abs(b - a) / dt for a, b in zip(ref.positions, cur.positions))


class MotionSegmenter:
    def __init__(
        self,
        *,
        velocity_threshold: float = 0.02,
        min_segment_seconds: float = 0.3,
        settle_seconds: float = 0.4,
        max_segment_seconds: float = 20.0,
        start_index: int = 0,
    ) -> None:
        self.velocity_threshold = velocity_threshold
        self.min_segment_seconds = min_segment_seconds
        self.settle_seconds = settle_seconds
        self.max_segment_seconds = max_segment_seconds
        self._next_index = start_index
        self._prev: JointSample | None = None
        self._history: deque[JointSample] = deque()
        self._current: MotionSegment | None = None

    def feed(self, cur: JointSample) -> list[MotionSegment]:
        """Feed one sample; return any segments closed by it (usually none or one)."""
        closed: list[MotionSegment] = []
        prev = self._prev
        self._prev = cur
        history = self._history
        history.append(cur)
        while len(history) > 2 and cur.t - history[1].t >= DIFF_WINDOW_SECONDS:
            history.popleft()
        if prev is None:
            return closed
        moving = max(_speeds(history[0], cur)) > self.velocity_threshold
        current = self._current

        if current is None:
            if moving:
                # Include the last still sample so the segment carries its start pose. When speed
                # comes from differentiating positions, motion is only seen after the 0.1 s
                # window, so start from the window's first sample to keep the onset (and the
                # segment's active length) intact.
                # The active length is measured from detection, not from the kept onset, so
                # stillness kept for the start pose never counts as motion. Windowed speed is
                # seen ~half a window late at both ends; active_pad credits that back.
                reported = cur.velocities is not None and any(v != 0.0 for v in cur.velocities)
                if reported:
                    self._current = MotionSegment(index=self._next_index, names=cur.names, samples=[prev, cur], last_moving_t=cur.t)
                else:
                    self._current = MotionSegment(
                        index=self._next_index, names=cur.names, samples=list(history), last_moving_t=cur.t,
                        first_moving_t=cur.t, active_pad=DIFF_WINDOW_SECONDS / 2,
                    )
            return closed

        current.samples.append(cur)
        if moving:
            current.last_moving_t = cur.t
        elif cur.t - current.last_moving_t >= self.settle_seconds:
            seg = self._close(current)
            self._current = None
            if seg is not None:
                closed.append(seg)
            return closed
        if current.duration >= self.max_segment_seconds:
            seg = self._close(current)
            self._current = MotionSegment(
                index=self._next_index, names=cur.names, samples=[cur], last_moving_t=cur.t,
                first_moving_t=cur.t, active_pad=current.active_pad,
            )
            if seg is not None:
                closed.append(seg)
        return closed

    def flush(self) -> list[MotionSegment]:
        """Close the segment in progress (end of stream, or Ctrl-C)."""
        if self._current is None:
            return []
        seg = self._close(self._current)
        self._current = None
        return [seg] if seg is not None else []

    def segments(self, samples: Iterable[JointSample]) -> Iterator[MotionSegment]:
        for cur in samples:
            yield from self.feed(cur)
        yield from self.flush()

    def _close(self, seg: MotionSegment) -> MotionSegment | None:
        if seg.active_duration < self.min_segment_seconds or len(seg.samples) < 2:
            return None
        self._next_index += 1
        return seg
