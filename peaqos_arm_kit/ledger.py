"""The local motion log.

Layout under ``KIT_LOG_DIR``::

    segments/000001.json   canonical raw_data of segment 1 (the bytes that were hashed)
    ledger.jsonl           one line per segment: hash, timestamps, tx hash once submitted

The ledger is append-only. Nothing here is secret; it is what a team hands a
judge together with their machine ID so the judge can re-verify.
"""

from __future__ import annotations

import fcntl
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from .schema import EventPayload

log = logging.getLogger("armkit.ledger")


@dataclass
class LedgerEntry:
    segment_index: int
    timestamp: int
    value: int
    data_hash: str  # 0x-hex keccak256(raw_data)
    metadata: str  # utf-8 text of the on-chain metadata
    raw_file: str  # relative path of the raw_data file
    status: str = "pending"  # pending | dry-run | submitted | failed
    tx_hash: str | None = None
    error: str | None = None


class Ledger:
    def __init__(self, root: str | Path, *, create: bool = True) -> None:
        self.root = Path(root)
        self.segments_dir = self.root / "segments"
        self.path = self.root / "ledger.jsonl"
        if create:
            self.segments_dir.mkdir(parents=True, exist_ok=True)
        elif not self.path.exists():
            raise FileNotFoundError(f"no ledger.jsonl in {self.root}: is this the right motion log folder?")

    def lock(self):
        """Hold an exclusive lock on this folder while recording or resubmitting, so two
        processes never take the same segment index. The OS releases it if the process dies."""
        fh = open(self.root / ".armkit.lock", "w")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.close()
            raise SystemExit(f"another armkit record or resubmit is using {self.root}; stop it first (one recorder per folder)")
        except OSError as exc:  # e.g. ENOLCK on a WSL2 /mnt/c mount: keep going, just unguarded
            log.warning("could not lock %s (%s); run only one recorder on this folder", self.root, exc)
        return fh

    def record(self, payload: EventPayload) -> LedgerEntry:
        raw_file = f"segments/{payload.segment_index:06d}.json"
        (self.root / raw_file).write_bytes(payload.raw_data)
        entry = LedgerEntry(
            segment_index=payload.segment_index,
            timestamp=payload.timestamp,
            value=payload.value,
            data_hash="0x" + payload.data_hash.hex(),
            metadata=payload.metadata.decode("utf-8"),
            raw_file=raw_file,
        )
        self._append(entry)
        return entry

    def update(self, entry: LedgerEntry, *, status: str, tx_hash: str | None = None, error: str | None = None) -> LedgerEntry:
        entry.status = status
        entry.tx_hash = tx_hash
        entry.error = error
        self._append(entry)  # later line for the same segment wins
        return entry

    def _append(self, entry: LedgerEntry) -> None:
        # A crash mid-append can leave a last line without its newline. Start a fresh
        # line first, otherwise this entry would be glued onto the fragment and lost too.
        needs_newline = False
        if self.path.exists() and self.path.stat().st_size > 0:
            with self.path.open("rb") as fh:
                fh.seek(-1, 2)
                needs_newline = fh.read(1) != b"\n"
        with self.path.open("a", encoding="utf-8") as fh:
            if needs_newline:
                fh.write("\n")
            fh.write(json.dumps(asdict(entry), separators=(",", ":")) + "\n")

    def entries(self) -> list[LedgerEntry]:
        """Latest state of every segment, in segment order."""
        latest: dict[int, LedgerEntry] = {}
        for entry in self._iter_lines():
            latest[entry.segment_index] = entry
        return [latest[k] for k in sorted(latest)]

    def _iter_lines(self) -> Iterator[LedgerEntry]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield LedgerEntry(**json.loads(line))
                except (json.JSONDecodeError, TypeError) as exc:
                    # a crash mid-append leaves a truncated last line; keep the rest readable
                    log.warning("ledger.jsonl line %d unreadable (%s); skipped", lineno, exc)

    def raw_bytes(self, entry: LedgerEntry) -> bytes:
        return (self.root / entry.raw_file).read_bytes()

    def next_index(self) -> int:
        entries = self.entries()
        return entries[-1].segment_index + 1 if entries else 1
