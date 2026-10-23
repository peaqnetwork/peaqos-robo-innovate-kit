"""``armkit``: the team-facing command line.

    armkit check              what is configured, is the wallet funded, is the chain reachable
    armkit record             record motion segments to the local log (dry run: nothing sent)
    armkit record --live      ...and anchor each segment on peaq under your machine identity
    armkit resubmit           anchor segments whose submission failed or whose receipt was lost
    armkit verify             re-verify a motion log against the chain (no key needed)
    armkit status             on-chain event count and the latest events (yours, or --arm)

``--env FILE`` (or KIT_ENV_FILE) picks the .env to load; default is ./.env.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from urllib.parse import urlsplit

import click

from . import __version__
from .config import ENV_FILE_VAR, KitSettings

APPROX_PEAQ_PER_EVENT = 0.045
LOW_BALANCE_PEAQ = 0.2


def _settings() -> KitSettings:
    return KitSettings.load()


def _mask(url: str) -> str:
    """Show scheme and host only: private endpoints carry tokens in the path."""
    if not url:
        return "MISSING"
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}" + ("/…" if parts.path.strip("/") else "")


def _redact(exc: BaseException) -> str:
    from .submit import redact_urls

    return redact_urls(str(exc))


def _reader(s: KitSettings, rpc_url: str | None = None, registry: str | None = None):
    from .chain import EventRegistryReader

    rpc = rpc_url or s.rpc_url
    reg = registry or s.event_registry
    missing = [n for n, v in (("PEAQOS_RPC_URL", rpc), ("EVENT_REGISTRY_ADDRESS", reg)) if not v]
    if missing:
        raise click.ClickException(
            f"{' and '.join(missing)} not set in .env: run armkit from the folder where you ran scripts/setup.sh "
            "(for the README quick start only: use .env.example)"
        )
    return EventRegistryReader(rpc, reg)


@click.group()
@click.version_option(__version__, prog_name="armkit")
@click.option("-v", "--verbose", is_flag=True, help="Debug logging.")
@click.option("--env", "env_file", default=None, help="Path of the .env to load (default ./.env).")
def main(verbose: bool, env_file: str | None) -> None:
    if env_file:
        os.environ[ENV_FILE_VAR] = env_file
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


@main.command()
def check() -> None:
    """Show configuration and whether the chain side is ready."""
    s = _settings()
    rows = [
        ("joint source", s.joint_source),
        ("log dir", str(s.log_dir)),
        ("machine id", str(s.machine_id) if s.machine_id else "MISSING (run scripts/setup.sh, README step 2)"),
        ("arm machine id", str(s.arm_machine_id) if s.arm_machine_id else "not set"),
        ("rpc", _mask(s.rpc_url)),
        ("event registry", s.event_registry or "MISSING"),
        ("signer configured", "yes" if s.has_signer else "no (PEAQOS_PRIVATE_KEY)"),
        ("trust level", str(s.trust_level) + ("  (1 needs source_tx_hash; the kit only supports 0)" if s.trust_level else "")),
    ]
    for k, v in rows:
        click.echo(f"{k:>18}: {v}")

    reader = _reader(s)
    try:
        cid = reader.chain_id()
        click.echo(f"{'chain id':>18}: {cid}" + ("" if cid == 3338 else "  (expected 3338, peaq mainnet)"))
        if s.machine_id:
            click.echo(f"{'events on chain':>18}: {reader.event_count(s.machine_id)}")
    except Exception as exc:
        click.echo(f"\nchain: unreachable ({_redact(exc)})", err=True)
        sys.exit(2)

    if s.has_signer:
        try:
            from .submit import make_client

            client = make_client()
            addr = client.account.address
            bal = client.web3.eth.get_balance(addr) / 1e18
            click.echo(f"{'signer':>18}: {addr}")
            click.echo(f"{'balance':>18}: {bal:.4f} PEAQ  (~{int(bal / APPROX_PEAQ_PER_EVENT)} events at ~{APPROX_PEAQ_PER_EVENT} PEAQ each)")
            if bal < LOW_BALANCE_PEAQ:
                click.echo(f"  balance below {LOW_BALANCE_PEAQ} PEAQ: ask a mentor to top up before recording --live", err=True)
        except Exception as exc:
            click.echo(f"signer: could not build client ({_redact(exc)})", err=True)


@main.command()
@click.option("--live", is_flag=True, help="Anchor every segment on peaq. Without it, nothing is sent.")
@click.option("--source", type=click.Choice(["synthetic", "csv", "ros2"]), default=None, help="Override KIT_JOINT_SOURCE.")
@click.option("--max-segments", type=int, default=None, help="Stop after this many segments.")
@click.option("--fast", is_flag=True, help="Replay sources without real-time pacing.")
def record(live: bool, source: str | None, max_segments: int | None, fast: bool) -> None:
    """Record motion segments; each becomes one peaqOS event. Ctrl-C closes the current segment."""
    from .recorder import record as _record

    s = _settings()
    if live and not s.has_signer:
        raise click.ClickException("--live needs PEAQOS_PRIVATE_KEY in .env (run scripts/setup.sh, README step 2)")
    from .recorder import LIVE_SOURCES

    kind = source or s.joint_source
    if live and kind not in LIVE_SOURCES:
        click.echo(f"note: anchoring a '{kind}' run. Synthetic and CSV runs don't count for the hand-in; record the emulator or a robot (--source ros2).", err=True)
    stats = _record(s, live=live, source_kind=source, max_segments=max_segments, realtime=not fast)
    mode = "anchored on peaq" if live else "logged locally (dry run)"
    extra = f", {stats.lost} receipt(s) lost (run `armkit resubmit`)" if stats.lost else ""
    if stats.unprocessed:
        extra += f", {stats.unprocessed} not processed (anchor worker stopped; check the log, then `armkit resubmit`)"
    click.echo(f"{stats.segments} segment(s) {mode}; {stats.submitted} submitted, {stats.failed} failed{extra}")
    if stats.failed or stats.lost or stats.unprocessed:
        sys.exit(1)


@main.command()
@click.option("--include-dry-run", is_flag=True, help="Also anchor segments recorded without --live.")
def resubmit(include_dry_run: bool) -> None:
    """Anchor segments that failed or whose receipt was lost. Checks the chain first; never anchors twice."""
    from .recorder import resubmit as _resubmit

    s = _settings()
    if not s.has_signer:
        raise click.ClickException("resubmit needs PEAQOS_PRIVATE_KEY in .env")
    statuses = ("failed", "pending", "dry-run") if include_dry_run else ("failed", "pending")
    stats = _resubmit(s, statuses=statuses)
    click.echo(f"{stats.segments} segment(s) retried; {stats.submitted} anchored, {stats.failed} failed, {stats.lost} still pending")
    if stats.failed or stats.lost:
        sys.exit(1)


@main.command()
@click.option("--machine-id", type=int, default=None, help="Defaults to KIT_MACHINE_ID.")
@click.option("--log-dir", default=None, help="Defaults to KIT_LOG_DIR.")
@click.option("--rpc-url", default=None, help="Defaults to PEAQOS_RPC_URL.")
@click.option("--registry", default=None, help="Defaults to EVENT_REGISTRY_ADDRESS.")
@click.option("--include-pending", is_flag=True, help="List dry-run segments as unanchored instead of flagging each as a run-level problem; they still fail.")
@click.option("--json", "as_json", is_flag=True)
def verify(machine_id, log_dir, rpc_url, registry, include_pending, as_json) -> None:
    """Independently verify a motion log against the chain. Needs no private key."""
    from .ledger import Ledger
    from .verify import format_report, verify as _verify

    s = _settings()
    mid = machine_id or s.require_machine_id()
    try:
        ledger = Ledger(log_dir or s.log_dir, create=False)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    reader = _reader(s, rpc_url, registry)
    report = _verify(ledger, reader, mid, include_pending=include_pending)
    click.echo(json.dumps(report.to_dict(), indent=2) if as_json else format_report(report))
    sys.exit(0 if report.all_ok else 1)


@main.command()
@click.option("--machine-id", type=int, default=None, help="Defaults to KIT_MACHINE_ID (your own identity).")
@click.option("--arm", is_flag=True, help="Read the real A0509's own identity instead (KIT_ARM_MACHINE_ID).")
@click.option("--last", type=int, default=5, help="How many recent events to print.")
def status(machine_id, arm, last) -> None:
    """Event count and recent events for a machine, read from the chain."""
    from .schema import parse_metadata

    s = _settings()
    if arm:
        if s.arm_machine_id is None:
            raise click.ClickException("KIT_ARM_MACHINE_ID is not set in .env")
        mid, label = s.arm_machine_id, "A0509 (its own identity)"
    else:
        mid, label = machine_id or s.require_machine_id(), "your machine"
    reader = _reader(s)
    total = reader.event_count(mid)
    click.echo(f"{label} {mid}: {total} event(s) on chain {reader.chain_id()}")
    for ev in reader.events(mid, offset=max(0, total - last)):
        meta = parse_metadata(ev.metadata)
        if meta:
            desc = f"segment {meta['i']} {meta['ms']} ms {meta['n']} samples"
        else:
            desc = f"type {ev.event_type} value {ev.value} trust {ev.trust_level} metadata {ev.metadata[:40]!r}"
        click.echo(f"  #{ev.index:<5} ts {ev.timestamp}  hash {ev.data_hash[:18]}…  {desc}")


if __name__ == "__main__":
    main()
