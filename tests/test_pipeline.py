from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from peaqos_arm_kit.chain import ChainEvent
from peaqos_arm_kit.ledger import Ledger
from peaqos_arm_kit.schema import SCHEMA_ID, EventPayload, build_payload, canonical_bytes, parse_metadata
from peaqos_arm_kit.segmenter import MotionSegmenter
from peaqos_arm_kit.sources.base import JointSample
from peaqos_arm_kit.sources.synthetic import SyntheticArm
from peaqos_arm_kit.verify import verify

MACHINE_ID = 123456789


def _segments(moves: int = 3, seed: int = 1):
    arm = SyntheticArm(realtime=False, moves=moves, seed=seed)
    return list(MotionSegmenter().segments(arm.samples()))


def _payloads(moves=2):
    return [build_payload(s, machine_id=MACHINE_ID, source="synthetic") for s in _segments(moves=moves)]


# ---------------------------------------------------------------- segmenter

def test_segmenter_finds_one_segment_per_move():
    segs = _segments(moves=3)
    assert len(segs) == 3
    assert [s.index for s in segs] == [0, 1, 2]
    for s in segs:
        assert 1.5 < s.duration < 3.5


def test_segmenter_ignores_jitter_and_stillness():
    names = ("j1",)
    samples = [JointSample(t=i * 0.02, names=names, positions=(0.0,)) for i in range(200)]
    samples[50] = JointSample(t=1.0, names=names, positions=(0.001,))
    assert list(MotionSegmenter().segments(iter(samples))) == []


def test_segmenter_uses_reported_velocities_when_present():
    names = ("j1",)
    samples = [JointSample(t=i * 0.02, names=names, positions=(0.0,), velocities=(0.5 if 20 <= i < 60 else 0.0,)) for i in range(100)]
    assert len(list(MotionSegmenter(min_segment_seconds=0.2).segments(iter(samples)))) == 1


def test_segmenter_ignores_all_zero_velocity_arrays():
    """The Doosan emulator publishes velocity=[0,...] while moving; positions must be used instead."""
    arm = SyntheticArm(realtime=False, moves=2, seed=3)
    with_zero_vel = [JointSample(s.t, s.names, s.positions, velocities=tuple(0.0 for _ in s.positions)) for s in arm.samples()]
    assert len(list(MotionSegmenter().segments(iter(with_zero_vel)))) == 2


def test_segmenter_zero_velocity_position_noise_is_not_motion():
    """Stationary arm, velocity reported as 0, positions jittering +-0.0003 rad at 50 Hz."""
    names = ("j1",)
    samples = [JointSample(t=i * 0.02, names=names, positions=(0.0003 if i % 2 else -0.0003,), velocities=(0.0,)) for i in range(500)]
    assert list(MotionSegmenter().segments(iter(samples))) == []


def test_segmenter_keeps_short_slow_move_with_zero_velocities():
    """0.05 rad/s for 0.34 s after a still second, velocities reported as 0 (emulator style).
    Moves right at the 0.02 rad/s threshold and the 0.3 s minimum can land either side of it."""
    names = ("j1",)
    for hz in (50, 100):
        dt, samples, pos = 1.0 / hz, [], 0.0
        for i in range(int(2.5 * hz)):
            t = i * dt
            if 1.0 <= t < 1.34:
                pos += 0.05 * dt
            samples.append(JointSample(t=t, names=names, positions=(pos,), velocities=(0.0,)))
        assert len(list(MotionSegmenter().segments(iter(samples)))) == 1, hz


def test_segmenter_drops_short_blip_with_zero_velocities():
    """0.5 rad/s for 0.12 s is shorter than min_segment_seconds and must not become a segment."""
    names = ("j1",)
    for hz in (50, 100):
        dt, samples, pos = 1.0 / hz, [], 0.0
        for i in range(int(2.0 * hz)):
            t = i * dt
            if 1.0 <= t < 1.12:
                pos += 0.5 * dt
            samples.append(JointSample(t=t, names=names, positions=(pos,), velocities=(0.0,)))
        assert list(MotionSegmenter().segments(iter(samples))) == [], hz


def test_segmenter_flush_closes_segment_in_progress():
    seg = MotionSegmenter()
    closed = []
    for s in SyntheticArm(realtime=False, moves=1, seed=5, pause_seconds=0.0).samples():
        closed += seg.feed(s)
    # the single move ends the stream with no settle tail -> nothing closed yet
    assert closed == []
    assert len(seg.flush()) == 1


# ---------------------------------------------------------------- schema / ledger

def test_payload_is_deterministic_and_hash_matches_sdk():
    from peaq_os_sdk.utils.data_hash import compute_data_hash

    seg = _segments(moves=1)[0]
    p1 = build_payload(seg, machine_id=MACHINE_ID, source="synthetic")
    p2 = build_payload(seg, machine_id=MACHINE_ID, source="synthetic")
    assert p1.raw_data == p2.raw_data
    assert p1.data_hash == compute_data_hash(p1.raw_data)
    doc = json.loads(p1.raw_data)
    assert doc["schema"] == SCHEMA_ID and doc["source"] == "synthetic"
    assert canonical_bytes(doc) == p1.raw_data
    meta = parse_metadata(p1.metadata)
    assert meta and meta["n"] == doc["sample_count"] and meta["ms"] == p1.value
    assert len(p1.metadata) < 4096


def test_source_changes_hash():
    seg = _segments(moves=1)[0]
    a = build_payload(seg, machine_id=MACHINE_ID, source="synthetic")
    b = build_payload(seg, machine_id=MACHINE_ID, source="ros2:/dsr01/joint_states")
    assert a.data_hash != b.data_hash


def test_ledger_roundtrip_and_tolerates_truncated_line(tmp_path):
    ledger = Ledger(tmp_path)
    [payload] = _payloads(moves=1)
    entry = ledger.record(payload)
    ledger.update(entry, status="submitted", tx_hash="0xabc")
    with ledger.path.open("a") as fh:
        fh.write('{"segment_index": 2, "tim')  # crash mid-append
    [latest] = ledger.entries()
    assert latest.status == "submitted" and latest.tx_hash == "0xabc"
    assert ledger.raw_bytes(latest) == payload.raw_data


def test_ledger_append_after_truncated_line_keeps_new_entry(tmp_path):
    ledger = Ledger(tmp_path)
    p1, p2 = _payloads(moves=2)
    ledger.record(p1)
    with ledger.path.open("a") as fh:
        fh.write('{"segment_index": 9, "tim')  # crash mid-append, no newline
    ledger.record(p2)
    assert [e.segment_index for e in ledger.entries()] == [p1.segment_index, p2.segment_index]


def test_ledger_create_false_requires_existing_log(tmp_path):
    with pytest.raises(FileNotFoundError):
        Ledger(tmp_path / "nope", create=False)


# ---------------------------------------------------------------- verifier

class FakeReader:
    def __init__(self, events, chain_id=3338):
        self._events, self._cid = events, chain_id

    def chain_id(self):
        return self._cid

    def events(self, machine_id, offset=0, limit=None):
        return self._events


def _chain_event(index, payload, *, value=None, metadata=None, data_hash=None):
    return ChainEvent(
        index=index, machine_id=MACHINE_ID, event_type=1,
        value=payload.value if value is None else value, timestamp=payload.timestamp,
        data_hash=data_hash or ("0x" + payload.data_hash.hex()), trust_level=0, source_chain_id=3338,
        metadata=payload.metadata if metadata is None else metadata, currency="",
    )


def _anchored_ledger(tmp_path, payloads):
    ledger = Ledger(tmp_path)
    for p in payloads:
        ledger.update(ledger.record(p), status="submitted", tx_hash="0x1")
    return ledger


def test_verifier_passes_clean_log(tmp_path):
    payloads = _payloads(2)
    ledger = _anchored_ledger(tmp_path, payloads)
    report = verify(ledger, FakeReader([_chain_event(i, p) for i, p in enumerate(payloads)]), MACHINE_ID)
    assert report.all_ok and report.sources == ["synthetic"]


def test_verifier_fails_empty_log(tmp_path):
    report = verify(Ledger(tmp_path), FakeReader([]), MACHINE_ID)
    assert not report.all_ok and "no segments" in report.problems[0]


def test_verifier_fails_wrong_chain(tmp_path):
    payloads = _payloads(1)
    report = verify(_anchored_ledger(tmp_path, payloads), FakeReader([_chain_event(0, payloads[0])], chain_id=9990), MACHINE_ID)
    assert not report.all_ok and "expected 3338" in report.problems[0]


def test_verifier_fails_failed_and_dry_run_entries(tmp_path):
    [p] = _payloads(1)
    ledger = Ledger(tmp_path)
    ledger.update(ledger.record(p), status="failed", error="x")
    report = verify(ledger, FakeReader([]), MACHINE_ID)
    assert not report.all_ok and report.verdicts[0].on_chain is False
    ledger2 = Ledger(tmp_path / "b")
    ledger2.update(ledger2.record(p), status="dry-run")
    report2 = verify(ledger2, FakeReader([]), MACHINE_ID)
    assert not report2.all_ok and any("dry-run" in x for x in report2.problems)


def test_verifier_catches_edited_log(tmp_path):
    [p] = _payloads(1)
    ledger = _anchored_ledger(tmp_path, [p])
    raw_path = tmp_path / ledger.entries()[0].raw_file
    doc = json.loads(raw_path.read_bytes()); doc["samples"][3][1] += 0.5
    raw_path.write_bytes(canonical_bytes(doc))
    report = verify(ledger, FakeReader([_chain_event(0, p)]), MACHINE_ID)
    assert not report.all_ok and report.verdicts[0].hash_recomputed_ok is False


def test_verifier_catches_bad_document_even_if_hash_matches(tmp_path):
    """A document whose hash was anchored but whose content is nonsense (wrong machine, bad time)."""
    seg = _segments(moves=1)[0]
    good = build_payload(seg, machine_id=MACHINE_ID)
    doc = json.loads(good.raw_data); doc["samples"][5][0] = 999999.0
    bad_raw = canonical_bytes(doc)
    from peaqos_arm_kit.schema import EventPayload
    bad = EventPayload(good.segment_index, good.timestamp, bad_raw, good.metadata, good.value)
    ledger = _anchored_ledger(tmp_path, [bad])
    report = verify(ledger, FakeReader([_chain_event(0, bad)]), MACHINE_ID)
    assert report.verdicts[0].hash_recomputed_ok is True and report.verdicts[0].document_ok is False
    # and a document for another machine
    other = build_payload(seg, machine_id=MACHINE_ID + 1)
    ledger2 = _anchored_ledger(tmp_path / "b", [other])
    report2 = verify(ledger2, FakeReader([_chain_event(0, other)]), MACHINE_ID)
    assert report2.verdicts[0].document_ok is False and "machine_id" in report2.verdicts[0].note


def test_verifier_catches_missing_anchor_and_dropped_segment(tmp_path):
    p_logged, p_dropped = _payloads(2)
    ledger = _anchored_ledger(tmp_path, [p_logged])
    report = verify(ledger, FakeReader([_chain_event(0, p_dropped)]), MACHINE_ID)
    assert not report.all_ok and report.verdicts[0].on_chain is False and report.unmatched_chain_events == [0]


def test_verifier_lists_non_motion_events_without_failing(tmp_path):
    # a team's own extension event on the same machine is not a dropped move
    payloads = _payloads(1)
    ledger = _anchored_ledger(tmp_path, payloads)
    foreign = ChainEvent(1, MACHINE_ID, 1, 0, 1, "0x" + "ab" * 32, 2, 3338, b'{"alg":"ES256K"}', "")
    report = verify(ledger, FakeReader([_chain_event(0, payloads[0]), foreign]), MACHINE_ID)
    assert report.unmatched_chain_events == [] and report.other_chain_events == [1] and report.all_ok


def test_verifier_matches_motion_event_when_extension_event_shares_its_hash(tmp_path):
    # an extension event that references a segment's hash, anchored before the motion event
    [p] = _payloads(1)
    ledger = _anchored_ledger(tmp_path, [p])
    extension = _chain_event(0, p, metadata=b'{"alg":"ES256K"}')
    report = verify(ledger, FakeReader([extension, _chain_event(1, p)]), MACHINE_ID)
    assert report.all_ok and report.verdicts[0].event_index == 1 and report.other_chain_events == [0]


def test_verifier_fails_malformed_document_instead_of_crashing(tmp_path):
    [p] = _payloads(1)
    doc = json.loads(p.raw_data)
    del doc["end_ts"]
    raw = json.dumps(doc, separators=(",", ":")).encode()
    bad = EventPayload(segment_index=p.segment_index, timestamp=p.timestamp, raw_data=raw, metadata=p.metadata, value=p.value)
    ledger = _anchored_ledger(tmp_path, [bad])
    report = verify(ledger, FakeReader([_chain_event(0, bad)]), MACHINE_ID)
    assert not report.all_ok and report.verdicts[0].document_ok is False


def test_verifier_rejects_relabelled_and_duplicated_segments(tmp_path):
    p1, p2 = _payloads(2)
    ledger = _anchored_ledger(tmp_path, [p1, p2])
    # swap the two segments' indices in the ledger, keep their files and hashes
    a, b = ledger.entries()
    a.segment_index, b.segment_index = b.segment_index, a.segment_index
    ledger.path.write_text("".join(json.dumps(asdict(e)) + "\n" for e in (a, b)))
    events = [_chain_event(0, p1), _chain_event(1, p2)]
    assert not verify(ledger, FakeReader(events), MACHINE_ID).all_ok


@pytest.mark.parametrize("field,value", [("n", 1), ("i", 99), ("d", [0.0] * 6), ("ms", 5)])
def test_verifier_catches_metadata_mismatch(tmp_path, field, value):
    [p] = _payloads(1)
    ledger = _anchored_ledger(tmp_path, [p])
    bad_meta = json.loads(p.metadata); bad_meta[field] = value
    ev = _chain_event(0, p, metadata=canonical_bytes(bad_meta), value=value if field == "ms" else None)
    report = verify(ledger, FakeReader([ev]), MACHINE_ID)
    assert report.verdicts[0].metadata_consistent is False and field in report.verdicts[0].note


def test_verifier_fails_missing_metadata(tmp_path):
    [p] = _payloads(1)
    ledger = _anchored_ledger(tmp_path, [p])
    report = verify(ledger, FakeReader([_chain_event(0, p, metadata=b"")]), MACHINE_ID)
    assert report.verdicts[0].metadata_consistent is False


# ---------------------------------------------------------------- recorder / resubmit

@pytest.mark.parametrize("kind", ["synthetic", "csv"])
def test_record_dry_run(tmp_path, kind, monkeypatch):
    from peaqos_arm_kit.config import KitSettings
    from peaqos_arm_kit.recorder import record

    csv_path = tmp_path / "log.csv"
    if kind == "csv":
        import csv as _csv
        with csv_path.open("w", newline="") as fh:
            w = _csv.writer(fh); first = True
            for s in SyntheticArm(realtime=False, moves=2).samples():
                if first:
                    w.writerow(["t", *s.names]); first = False
                w.writerow([s.t, *s.positions])
    monkeypatch.setenv("KIT_MACHINE_ID", str(MACHINE_ID))
    monkeypatch.setenv("KIT_LOG_DIR", str(tmp_path / "log"))
    monkeypatch.setenv("KIT_CSV_PATH", str(csv_path))
    settings = KitSettings.load(dotenv_path=tmp_path / "nonexistent.env")
    stats = record(settings, live=False, source_kind=kind, realtime=False)
    assert stats.segments >= 2 and stats.submitted == 0
    entries = Ledger(tmp_path / "log").entries()
    assert all(e.status == "dry-run" for e in entries)
    assert json.loads(Ledger(tmp_path / "log").raw_bytes(entries[0]))["source"].startswith(kind)


class FakeSubmitter:
    on_chain: set[bytes] = set()
    sent: list[bytes] = []

    def __init__(self, client, **kw):
        pass

    def already_on_chain(self, data_hash):
        return "on-chain:event#0" if data_hash in self.on_chain else None

    def submit(self, payload):
        from peaqos_arm_kit.submit import SubmitResult
        FakeSubmitter.sent.append(payload.raw_data)
        return SubmitResult(tx_hash="0xnew", data_hash=payload.data_hash, timestamp=1)


def _resubmit_env(tmp_path, monkeypatch):
    from peaqos_arm_kit import recorder as rec
    from peaqos_arm_kit.config import KitSettings
    FakeSubmitter.sent = []; FakeSubmitter.on_chain = set()
    monkeypatch.setattr(rec, "EventSubmitter", FakeSubmitter)
    monkeypatch.setattr("peaqos_arm_kit.submit.make_client", lambda: object())
    monkeypatch.setattr(rec, "pending_tx_state", lambda client: False)
    monkeypatch.setenv("KIT_MACHINE_ID", str(MACHINE_ID))
    monkeypatch.setenv("KIT_LOG_DIR", str(tmp_path / "log"))
    return rec, KitSettings.load(dotenv_path=tmp_path / "none.env")


def test_resubmit_anchors_failed_and_skips_already_on_chain(tmp_path, monkeypatch):
    rec, settings = _resubmit_env(tmp_path, monkeypatch)
    ledger = Ledger(tmp_path / "log")
    p_failed, p_lost = _payloads(2)
    ledger.update(ledger.record(p_failed), status="failed", error="FutureTimestamp()")
    ledger.update(ledger.record(p_lost), status="pending", error="receipt lost")
    FakeSubmitter.on_chain = {p_lost.data_hash}  # the lost one actually landed
    stats = rec.resubmit(settings)
    assert stats.segments == 2 and stats.submitted == 2 and stats.failed == 0
    assert FakeSubmitter.sent == [p_failed.raw_data]  # the lost one was NOT sent again
    assert [e.status for e in ledger.entries()] == ["submitted", "submitted"]


def test_resubmit_refuses_other_machines_documents(tmp_path, monkeypatch):
    rec, settings = _resubmit_env(tmp_path, monkeypatch)
    ledger = Ledger(tmp_path / "log")
    quickstart = build_payload(_segments(moves=1)[0], machine_id=1, source="synthetic")  # placeholder ID
    ledger.update(ledger.record(quickstart), status="dry-run")
    stats = rec.resubmit(settings, statuses=("dry-run",))
    assert stats.submitted == 0 and stats.failed == 1 and FakeSubmitter.sent == []


def test_resubmit_rechecks_chain_after_pending_check(tmp_path, monkeypatch):
    # the lost tx gets mined between the hash lookup and the nonce check
    rec, settings = _resubmit_env(tmp_path, monkeypatch)
    ledger = Ledger(tmp_path / "log")
    (p_lost,) = _payloads(1)
    ledger.update(ledger.record(p_lost), status="pending", error="receipt lost")

    def mined_meanwhile(client):
        FakeSubmitter.on_chain = {p_lost.data_hash}
        return False

    monkeypatch.setattr(rec, "pending_tx_state", mined_meanwhile)
    stats = rec.resubmit(settings)
    assert stats.submitted == 1 and FakeSubmitter.sent == []


def test_resubmit_stops_when_pending_state_unknown(tmp_path, monkeypatch):
    rec, settings = _resubmit_env(tmp_path, monkeypatch)
    ledger = Ledger(tmp_path / "log")
    (p,) = _payloads(1)
    ledger.update(ledger.record(p), status="failed", error="x")
    monkeypatch.setattr(rec, "pending_tx_state", lambda client: None)
    with pytest.raises(SystemExit):
        rec.resubmit(settings)
    assert FakeSubmitter.sent == []


def test_submitter_never_retries_while_a_tx_may_be_pending(monkeypatch):
    from types import SimpleNamespace
    from peaqos_arm_kit import submit as sub

    calls = []

    def submit_event(**kw):
        calls.append(kw)
        raise ConnectionError("connection reset while polling the receipt")

    eth = SimpleNamespace(wait_for_transaction_receipt=lambda *a, **k: None, get_block=lambda _: {"timestamp": 10**10})
    client = SimpleNamespace(web3=SimpleNamespace(eth=eth), submit_event=submit_event)
    monkeypatch.setattr(sub, "pending_tx_state", lambda c: True)
    monkeypatch.setattr(sub.EventSubmitter, "already_on_chain", lambda self, h: None)
    submitter = sub.EventSubmitter(client, machine_id=MACHINE_ID, base_delay=0)
    with pytest.raises(sub.LostReceipt):
        submitter.submit(_payloads(1)[0])
    assert len(calls) == 1


def test_one_writer_per_log_folder(tmp_path):
    first = Ledger(tmp_path).lock()
    with pytest.raises(SystemExit):
        Ledger(tmp_path).lock()
    first.close()
    Ledger(tmp_path).lock().close()


# ---------------------------------------------------------------- misc

def test_explain_revert_decodes_registry_errors():
    from peaqos_arm_kit.submit import explain_revert

    assert explain_revert(Exception("Transaction reverted: ('0x0ff02cef', '0x0ff02cef')")).startswith("FutureTimestamp()")
    assert "NotAuthorizedSubmitter()" in explain_revert(Exception("0x34a8dd7f"))
    assert "NotOwnerOrController()" in explain_revert(Exception("0xfce354b2"))
    assert explain_revert(Exception("something else")) == "something else"


def test_bad_machine_id_gives_readable_error(tmp_path, monkeypatch):
    from peaqos_arm_kit.config import KitSettings

    monkeypatch.setenv("KIT_MACHINE_ID", "PASTE_ID")
    with pytest.raises(SystemExit) as exc:
        KitSettings.load(dotenv_path=tmp_path / "none.env")
    assert "PASTE_ID" in str(exc.value)


def test_env_file_override(tmp_path, monkeypatch):
    from peaqos_arm_kit.config import KitSettings

    (tmp_path / "custom.env").write_text("KIT_MACHINE_ID=42\nKIT_LOG_DIR=/x\n")
    monkeypatch.delenv("KIT_MACHINE_ID", raising=False)
    monkeypatch.setenv("KIT_ENV_FILE", str(tmp_path / "custom.env"))
    s = KitSettings.load()
    assert s.machine_id == 42 and str(s.log_dir) == "/x"
