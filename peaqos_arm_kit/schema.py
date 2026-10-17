"""The ``joint_motion/0.1`` event: what one peaqOS event stands for.

One event = one motion segment of the arm. The full segment (every sampled
joint position) is serialised to canonical JSON. That byte string is
``raw_data``: it stays in the local motion log, and only ``keccak256`` of it
goes on chain as ``dataHash``. A short summary goes on chain as ``metadata``
so a verifier can read the chain alone and see what each event was.

Canonical form: UTF-8 JSON, keys sorted, no whitespace, floats rounded to a
fixed number of decimals and rendered with ``repr`` so the same segment always
produces the same bytes on any machine.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from .segmenter import MotionSegment

SCHEMA_ID = "joint_motion/0.1"
POSITION_DECIMALS = 5  # radians -> ~1e-5 rad resolution
TIME_DECIMALS = 3  # milliseconds
METADATA_MAX_BYTES = 4096  # EventRegistry MAX_METADATA_SIZE


def _r(value: float, nd: int) -> float:
    return round(float(value), nd)


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class EventPayload:
    """Everything the chain needs for one segment, plus the raw bytes for the log."""

    segment_index: int
    timestamp: int  # unix seconds of segment end
    raw_data: bytes
    metadata: bytes
    value: int  # duration in milliseconds

    @property
    def data_hash(self) -> bytes:
        from peaq_os_sdk.utils.data_hash import compute_data_hash

        return compute_data_hash(self.raw_data)


def build_payload(segment: MotionSegment, *, machine_id: int, source: str = "unknown") -> EventPayload:
    """``source`` names where the joint states came from (``ros2:/dsr01/joint_states``,
    ``csv:path``, ``synthetic``). It is part of the hashed document, so a team's declared
    input source is fixed at recording time."""
    t0 = segment.start_t
    samples = [
        [_r(s.t - t0, TIME_DECIMALS), *[_r(q, POSITION_DECIMALS) for q in s.positions]]
        for s in segment.samples
    ]
    start_pose = [_r(q, POSITION_DECIMALS) for q in segment.samples[0].positions]
    end_pose = [_r(q, POSITION_DECIMALS) for q in segment.samples[-1].positions]
    delta = [_r(b - a, POSITION_DECIMALS) for a, b in zip(start_pose, end_pose)]
    duration_ms = int(round(segment.duration * 1000))

    document = {
        "schema": SCHEMA_ID,
        "machine_id": str(machine_id),
        "source": source,
        "segment_index": segment.index,
        "start_ts": _r(t0, TIME_DECIMALS),
        "end_ts": _r(segment.end_t, TIME_DECIMALS),
        "joint_names": list(segment.names),
        "sample_count": len(samples),
        "samples": samples,  # [t_rel_s, q1..qN] per row
        "start_pose": start_pose,
        "end_pose": end_pose,
    }
    raw = canonical_bytes(document)

    summary = {
        "s": SCHEMA_ID,
        "i": segment.index,
        "ms": duration_ms,
        "n": len(samples),
        "j": len(segment.names),
        "d": delta,  # joint delta start->end, rad
    }
    metadata = canonical_bytes(summary)
    if len(metadata) > METADATA_MAX_BYTES:
        raise ValueError("metadata exceeds EventRegistry MAX_METADATA_SIZE")

    # On-chain timestamp = wall-clock time the segment was closed. The raw
    # document keeps the source clock (which for replays is not wall time);
    # the EventRegistry reverts on timestamps in the future.
    return EventPayload(
        segment_index=segment.index,
        timestamp=int(time.time()),
        raw_data=raw,
        metadata=metadata,
        value=duration_ms,
    )


def parse_metadata(metadata: bytes) -> dict[str, Any] | None:
    try:
        obj = json.loads(metadata.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) and obj.get("s") == SCHEMA_ID else None
