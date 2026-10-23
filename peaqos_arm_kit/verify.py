"""The independent verifier.

Given a motion log folder and a machine ID, for every segment in the ledger:

1. re-read the raw segment file and recompute keccak256: does it match the
   hash the ledger claims? (catches a log edited after the fact)
2. is the raw document well-formed for this machine: schema id, machine_id,
   sample rows of the right width with finite values and increasing time?
3. find an on-chain event for this machine with that exact ``dataHash``:
   does the chain hold it? (catches a log that was never anchored)
4. check the on-chain summary (sample count, joint count, duration, segment
   index, joint deltas, ``value``) against the raw document: catches a hash
   reused under a different description.

It also reports every on-chain event for the machine that has no matching
segment in the log, so a team cannot quietly drop a segment, and it refuses
to pass a log with unanchored segments or no segments at all.

A passing report means: the log you were handed is byte-for-byte what this
identity anchored, at the times the chain says. It does not prove where the
motion came from; the raw document's ``source`` field is the team's declaration
and the verifier prints it for the judges.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from .chain import ChainEvent, EventRegistryReader
from .config import PEAQ_MAINNET_CHAIN_ID
from .ledger import Ledger, LedgerEntry
from .schema import SCHEMA_ID, parse_metadata


@dataclass
class SegmentVerdict:
    segment_index: int
    hash_recomputed_ok: bool
    document_ok: bool
    on_chain: bool
    metadata_consistent: bool
    source: str = "?"
    event_index: int | None = None
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.hash_recomputed_ok and self.document_ok and self.on_chain and self.metadata_consistent


@dataclass
class VerifyReport:
    machine_id: int
    chain_id: int
    expected_chain_id: int
    verdicts: list[SegmentVerdict] = field(default_factory=list)
    unmatched_chain_events: list[int] = field(default_factory=list)  # joint_motion events missing from the log
    other_chain_events: list[int] = field(default_factory=list)  # non-motion events on the machine (listed, not judged)
    problems: list[str] = field(default_factory=list)  # run-level failures

    @property
    def all_ok(self) -> bool:
        return (
            not self.problems
            and bool(self.verdicts)
            and all(v.ok for v in self.verdicts)
            and not self.unmatched_chain_events
        )

    @property
    def sources(self) -> list[str]:
        return sorted({v.source for v in self.verdicts})

    def to_dict(self) -> dict:
        return {
            "machine_id": str(self.machine_id),
            "chain_id": self.chain_id,
            "sources": self.sources,
            "segments": [v.__dict__ for v in self.verdicts],
            "unmatched_chain_events": self.unmatched_chain_events,
            "other_chain_events": self.other_chain_events,
            "problems": self.problems,
            "all_ok": self.all_ok,
        }


def _check_document(doc: dict | None, machine_id: int) -> tuple[bool, str]:
    if doc is None:
        return False, "raw file is not JSON"
    if doc.get("schema") != SCHEMA_ID:
        return False, f"schema {doc.get('schema')!r} is not {SCHEMA_ID}"
    if str(doc.get("machine_id")) != str(machine_id):
        return False, f"document machine_id {doc.get('machine_id')} is not {machine_id}"
    names = doc.get("joint_names")
    samples = doc.get("samples")
    if not isinstance(names, list) or not names or not all(isinstance(n, str) and n for n in names):
        return False, "joint_names missing or not a list of names"
    if not isinstance(samples, list) or len(samples) < 2:
        return False, "fewer than 2 samples"
    if not isinstance(doc.get("segment_index"), int):
        return False, "segment_index missing"
    if not isinstance(doc.get("source"), str) or not doc["source"]:
        return False, "source missing (the team's declaration of where the motion came from)"
    start_ts, end_ts = doc.get("start_ts"), doc.get("end_ts")
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (start_ts, end_ts)) or end_ts <= start_ts:
        return False, "start_ts/end_ts missing or not increasing"
    if doc.get("sample_count") != len(samples):
        return False, "sample_count does not match samples"
    width = len(names) + 1
    prev_t = -math.inf
    for i, row in enumerate(samples):
        if not isinstance(row, list) or len(row) != width:
            return False, f"sample {i} has {len(row) if isinstance(row, list) else '?'} values, expected {width}"
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in row):
            return False, f"sample {i} has a non-finite value"
        if row[0] < prev_t:
            return False, f"sample {i} time goes backwards"
        prev_t = row[0]
    if abs(samples[0][0]) > 1e-6:
        return False, "first sample time is not 0 (times are relative to start_ts)"
    if samples[-1][0] <= samples[0][0]:
        return False, "sample times do not advance"
    if abs(samples[-1][0] - (doc["end_ts"] - doc["start_ts"])) > 0.01:
        return False, "sample times do not span start_ts..end_ts"
    for key in ("start_pose", "end_pose"):
        if doc.get(key) != [round(float(v), 5) for v in (samples[0] if key == "start_pose" else samples[-1])[1:]]:
            return False, f"{key} does not match the first/last sample"
    return True, ""


def _recompute(ledger: Ledger, entry: LedgerEntry) -> tuple[bool, dict | None]:
    from peaq_os_sdk.utils.data_hash import compute_data_hash

    try:
        raw = ledger.raw_bytes(entry)
    except FileNotFoundError:
        return False, None
    ok = ("0x" + compute_data_hash(raw).hex()).lower() == entry.data_hash.lower()
    try:
        doc = json.loads(raw.decode("utf-8"))
        if not isinstance(doc, dict):
            doc = None
    except (UnicodeDecodeError, json.JSONDecodeError):
        doc = None
    return ok, doc


def _metadata_matches(doc: dict | None, ev: ChainEvent) -> tuple[bool, str]:
    meta = parse_metadata(ev.metadata)
    if meta is None:
        return False, "on-chain metadata is missing or not joint_motion/0.1"
    if doc is None:
        return False, "no document to compare against"
    samples = doc.get("samples") or []
    duration_ms = int(round((doc["end_ts"] - doc["start_ts"]) * 1000)) if samples else 0
    delta = [round(float(b) - float(a), 5) for a, b in zip(doc.get("start_pose", []), doc.get("end_pose", []))]
    checks = {
        "n": meta.get("n") == len(samples),
        "j": meta.get("j") == len(doc.get("joint_names", [])),
        "ms": abs(int(meta.get("ms", -1)) - duration_ms) <= 2,
        "value": int(ev.value) == int(meta.get("ms", -1)),
        "i": meta.get("i") == doc.get("segment_index"),
        "d": [round(float(x), 5) for x in meta.get("d", [])] == delta,
    }
    bad = [k for k, v in checks.items() if not v]
    return (not bad), ("" if not bad else "metadata mismatch on " + ", ".join(bad))


def verify(
    ledger: Ledger,
    reader: EventRegistryReader,
    machine_id: int,
    *,
    expected_chain_id: int = PEAQ_MAINNET_CHAIN_ID,
    include_pending: bool = False,
) -> VerifyReport:
    chain_id = reader.chain_id()
    report = VerifyReport(machine_id=machine_id, chain_id=chain_id, expected_chain_id=expected_chain_id)
    if chain_id != expected_chain_id:
        report.problems.append(f"connected to chain {chain_id}, expected {expected_chain_id} (peaq mainnet)")

    entries = ledger.entries()
    if not entries:
        report.problems.append("the motion log has no segments")
    chain_events = reader.events(machine_id)
    by_hash: dict[str, list[ChainEvent]] = {}
    for ev in chain_events:
        by_hash.setdefault(ev.data_hash.lower(), []).append(ev)
    matched: set[int] = set()
    seen_hashes: set[str] = set()

    for entry in entries:
        if entry.data_hash.lower() in seen_hashes:
            report.problems.append(f"segment {entry.segment_index} repeats the hash of an earlier segment")
        seen_hashes.add(entry.data_hash.lower())
        if entry.status in ("dry-run",) and not include_pending:
            # dry runs are explicitly local-only; everything else must be on chain
            report.problems.append(f"segment {entry.segment_index} is a dry-run (never anchored)")
        hash_ok, doc = _recompute(ledger, entry)
        try:
            doc_ok, doc_note = _check_document(doc, machine_id)
        except (KeyError, TypeError, ValueError) as exc:  # malformed document: a verdict, not a crash
            doc_ok, doc_note = False, f"malformed document ({type(exc).__name__}: {exc})"
        if doc_ok and doc.get("segment_index") != entry.segment_index:
            # the ledger row must describe the document it points to (no relabelling or reordering)
            doc_ok, doc_note = False, f"ledger says segment {entry.segment_index}, document says {doc.get('segment_index')}"
        source = str(doc.get("source", "?")) if doc else "?"
        candidates = [c for c in by_hash.get(entry.data_hash.lower(), []) if c.index not in matched]
        # A team's own extension event can reference a segment's hash: match the kit motion event first
        candidates.sort(key=lambda c: parse_metadata(c.metadata) is None)
        if candidates:
            ev = candidates[0]
            matched.add(ev.index)
            try:
                meta_ok, meta_note = _metadata_matches(doc, ev)
            except (KeyError, TypeError, ValueError) as exc:
                meta_ok, meta_note = False, f"metadata check failed ({type(exc).__name__}: {exc})"
            notes = [n for n in ("" if hash_ok else "raw file does not hash to the ledger value", doc_note, meta_note) if n]
            report.verdicts.append(
                SegmentVerdict(entry.segment_index, hash_ok, doc_ok, True, meta_ok, source, ev.index, "; ".join(notes))
            )
        else:
            notes = [n for n in ("" if hash_ok else "raw file does not hash to the ledger value", doc_note) if n]
            notes.append(f"no on-chain event with this hash (ledger status: {entry.status})")
            report.verdicts.append(SegmentVerdict(entry.segment_index, hash_ok, doc_ok, False, False, source, None, "; ".join(notes)))

    # A joint_motion event with no segment in the log means a move was dropped: that fails.
    # Other events on the same machine (revenue, a team's own extension events) are not
    # motion claims; they are listed for the judges but do not fail the run.
    for ev in chain_events:
        if ev.index in matched:
            continue
        if parse_metadata(ev.metadata) is not None:
            report.unmatched_chain_events.append(ev.index)
        else:
            report.other_chain_events.append(ev.index)
    return report


def format_report(report: VerifyReport) -> str:
    lines = [f"machine {report.machine_id} on chain {report.chain_id}; declared source(s): {', '.join(report.sources) or '?'}"]
    for p in report.problems:
        lines.append(f"  [FAIL] {p}")
    for v in report.verdicts:
        mark = "OK " if v.ok else "FAIL"
        where = f"event #{v.event_index}" if v.on_chain else "not on chain"
        meta = ("ok" if v.metadata_consistent else "BAD") if v.on_chain else "-"
        flags = f"hash {'ok' if v.hash_recomputed_ok else 'BAD'}  doc {'ok' if v.document_ok else 'BAD'}  meta {meta}"
        lines.append(f"  [{mark}] segment {v.segment_index:>5}  {where:<14} {flags}  {v.note}")
    if report.unmatched_chain_events:
        lines.append(f"  [FAIL] on-chain motion events for this machine with no segment in this log: {report.unmatched_chain_events}")
    if report.other_chain_events:
        lines.append(f"  [info] events that are not kit motion events (for example extension events you added), not checked against this log: {report.other_chain_events}")
    lines.append("RESULT: " + ("all segments verified" if report.all_ok else "verification FAILED"))
    return "\n".join(lines)
