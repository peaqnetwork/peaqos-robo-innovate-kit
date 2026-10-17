"""The recording loop: source -> segmenter -> payload -> ledger -> chain.

Submission runs on a worker thread so a pending receipt never stalls
sampling (the ROS 2 queue would otherwise fill and drop samples). Ctrl-C
flushes the segment in progress, waits for in-flight submissions, and exits
cleanly.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from .config import KitSettings
from .ledger import Ledger, LedgerEntry
from .schema import EventPayload, build_payload
from .segmenter import MotionSegmenter
from .sources import open_source
from .submit import EventSubmitter, LostReceipt, pending_tx_state, redact_urls

log = logging.getLogger("armkit.recorder")

LIVE_SOURCES = ("ros2",)  # sources a team may declare for a hand-in; synthetic/csv are for building


@dataclass
class RecordStats:
    segments: int = 0
    submitted: int = 0
    failed: int = 0
    lost: int = 0  # broadcast, receipt unknown, not found on chain yet -> ledger status 'pending'
    unprocessed: int = 0  # queued but never handled because the anchor worker stopped on an error


def source_label(kind: str, settings: KitSettings) -> str:
    if kind == "ros2":
        return f"ros2:{settings.ros2_topic}"
    if kind == "csv":
        return f"csv:{settings.csv_path.name}"
    return kind


class _Anchorer:
    """Submits payloads sequentially on a background thread and updates the ledger."""

    def __init__(self, submitter: EventSubmitter, ledger: Ledger, stats: RecordStats) -> None:
        self.submitter, self.ledger, self.stats = submitter, ledger, stats
        self._q: queue.Queue[tuple[LedgerEntry, EventPayload] | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="armkit-anchor", daemon=True)
        self._thread.start()

    def put(self, entry: LedgerEntry, payload: EventPayload) -> None:
        self._q.put((entry, payload))

    def close(self) -> None:
        self._q.put(None)
        pending = self._q.qsize()
        if pending > 1:
            log.info("waiting for %d segment(s) still being anchored…", pending - 1)
        self._thread.join()

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            entry, payload = item
            try:
                anchor_one(self.submitter, self.ledger, self.stats, entry, payload)
            except Exception as exc:  # e.g. the ledger itself can't be written (disk full)
                # Count this segment and everything still queued, so the CLI exits non-zero
                # and `armkit resubmit` picks them up from the ledger later.
                log.error("anchor worker stopped: %s: %s", type(exc).__name__, exc)
                self.stats.unprocessed += 1
                while True:
                    rest = self._q.get()
                    if rest is None:
                        return
                    self.stats.unprocessed += 1


def anchor_one(submitter: EventSubmitter, ledger: Ledger, stats: RecordStats, entry: LedgerEntry, payload: EventPayload) -> None:
    try:
        result = submitter.submit(payload)
        ledger.update(entry, status="submitted", tx_hash=result.tx_hash)
        stats.submitted += 1
        log.info("segment %d anchored in tx %s", entry.segment_index, result.tx_hash)
    except LostReceipt as exc:
        # Broadcast, receipt unknown, not (yet) visible on chain. Leave it 'pending';
        # `armkit resubmit` checks the chain again before sending anything.
        msg = redact_urls(str(exc))
        ledger.update(entry, status="pending", error=f"receipt lost: {msg}")
        stats.lost += 1
        log.error("segment %d: receipt lost (%s); run `armkit resubmit` later", entry.segment_index, msg)
    except Exception as exc:
        msg = redact_urls(str(exc))
        ledger.update(entry, status="failed", error=f"{type(exc).__name__}: {msg}")
        stats.failed += 1
        log.error("segment %d NOT anchored: %s", entry.segment_index, msg)


def record(
    settings: KitSettings,
    *,
    live: bool,
    source_kind: str | None = None,
    max_segments: int | None = None,
    realtime: bool = True,
    on_entry: Callable[[LedgerEntry], None] | None = None,
) -> RecordStats:
    machine_id = settings.require_machine_id()
    ledger = Ledger(settings.log_dir)
    lock = ledger.lock()
    segmenter = MotionSegmenter(
        velocity_threshold=settings.velocity_threshold,
        min_segment_seconds=settings.min_segment_seconds,
        settle_seconds=settings.settle_seconds,
        max_segment_seconds=settings.max_segment_seconds,
        start_index=ledger.next_index(),
    )
    kind = source_kind or settings.joint_source
    label = source_label(kind, settings)
    stats = RecordStats()
    anchorer: _Anchorer | None = None
    if live:
        from .submit import make_client

        anchorer = _Anchorer(EventSubmitter(make_client(), machine_id=machine_id, trust_level=settings.trust_level), ledger, stats)

    source = open_source(kind, csv_path=settings.csv_path, topic=settings.ros2_topic, realtime=realtime)

    def handle(segment) -> bool:
        payload = build_payload(segment, machine_id=machine_id, source=label)
        entry = ledger.record(payload)
        stats.segments += 1
        log.info("segment %d: %.2fs, %d samples, hash %s", entry.segment_index, segment.duration, len(segment.samples), entry.data_hash[:18] + "…")
        if anchorer is None:
            ledger.update(entry, status="dry-run")
        else:
            anchorer.put(entry, payload)
        if on_entry is not None:
            on_entry(entry)
        return max_segments is not None and stats.segments >= max_segments

    try:
        try:
            for sample in source.samples():
                if any(handle(seg) for seg in segmenter.feed(sample)):
                    break
            else:
                for seg in segmenter.flush():
                    handle(seg)
        except KeyboardInterrupt:
            log.info("interrupted; closing the segment in progress")
            for seg in segmenter.flush():
                handle(seg)
    finally:
        source.close()
        if anchorer is not None:
            anchorer.close()
        lock.close()
    return stats


def resubmit(settings: KitSettings, *, statuses: tuple[str, ...] = ("failed", "pending")) -> RecordStats:
    """Anchor ledger entries that were recorded but not confirmed on chain.

    Checks the chain for each entry's hash first: an entry whose event already exists
    (a lost receipt) is marked submitted without sending anything, so nothing is
    anchored twice. Entries whose raw document names a different machine_id are
    refused: they came from a quick-start run against a placeholder ID."""
    machine_id = settings.require_machine_id()
    ledger = Ledger(settings.log_dir)
    lock = ledger.lock()
    try:
        return _resubmit(settings, ledger, machine_id, statuses)
    finally:
        lock.close()


def _resubmit(settings: KitSettings, ledger: Ledger, machine_id: int, statuses: tuple[str, ...]) -> RecordStats:
    from .submit import make_client

    client = make_client()
    submitter = EventSubmitter(client, machine_id=machine_id, trust_level=settings.trust_level)
    stats = RecordStats()

    def reconcile(entry: LedgerEntry, ref: str) -> None:
        ledger.update(entry, status="submitted", tx_hash=ref)
        stats.submitted += 1
        log.info("segment %d was already on chain (%s); ledger updated, nothing sent", entry.segment_index, ref)

    for entry in ledger.entries():
        if entry.status not in statuses:
            continue
        raw = ledger.raw_bytes(entry)
        try:
            doc_machine = str(json.loads(raw).get("machine_id"))
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            doc_machine = "?"
        if doc_machine != str(machine_id):
            log.error("segment %d was recorded for machine %s, not %s; refusing to anchor it", entry.segment_index, doc_machine, machine_id)
            stats.failed += 1
            continue
        payload = EventPayload(
            segment_index=entry.segment_index,
            timestamp=entry.timestamp,
            raw_data=raw,
            metadata=entry.metadata.encode("utf-8"),
            value=entry.value,
        )
        stats.segments += 1
        ref = submitter.already_on_chain(payload.data_hash)
        if ref:
            reconcile(entry, ref)
            continue
        if pending_tx_state(client) is not False:
            # A lost receipt can still be mined. Sending now could anchor the same segment
            # twice, which fails verification for good. Already-anchored segments above are
            # reconciled; stop before sending anything new.
            raise SystemExit("a transaction from this wallet may still be pending on chain; wait a minute and run `armkit resubmit` again")
        ref = submitter.already_on_chain(payload.data_hash)  # it may have been mined between the two checks
        if ref:
            reconcile(entry, ref)
            continue
        anchor_one(submitter, ledger, stats, entry, payload)
    return stats
