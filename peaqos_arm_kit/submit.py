"""Submit one motion event to the peaqOS EventRegistry, with backoff.

Wraps ``PeaqosClient.submit_event``. Activity event, ``value`` = segment
duration in milliseconds, ``trust_level`` from settings (0 = self-reported
unless the team can prove more). The SDK hashes ``raw_data`` with keccak256
itself; we never send the raw bytes anywhere.

Timestamp: the EventRegistry reverts with ``FutureTimestamp()`` if the event
timestamp is ahead of the block it lands in, so a laptop clock a few seconds
fast fails every quickly-mined transaction. We therefore stamp events with
the latest block's timestamp (minus a small margin) rather than local time.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from importlib import resources

from web3 import Web3

from .config import EVENT_TYPE_ACTIVITY, PEAQ_MAINNET_CHAIN_ID
from .schema import EventPayload

log = logging.getLogger("armkit.submit")

TIMESTAMP_MARGIN_SECONDS = 5
RECEIPT_POLL_SECONDS = 1.5  # web3's default is 0.1 s: ~4 RPC calls/s per laptop while a tx is pending


def _error_selectors() -> dict[str, str]:
    data = resources.files("peaq_os_sdk").joinpath("abis/EventRegistry.json").read_text("utf-8")
    loaded = json.loads(data)
    abi = loaded if isinstance(loaded, list) else loaded["abi"]
    out: dict[str, str] = {}
    for item in abi:
        if item.get("type") == "error":
            sig = f'{item["name"]}({",".join(i["type"] for i in item.get("inputs", []))})'
            out[Web3.keccak(text=sig)[:4].hex()] = item["name"]
    return out


_SELECTORS = _error_selectors()
# Tokenomics 2.0 EventRegistry errors that the SDK's shipped (1.0) ABI does not know.
_SELECTORS.setdefault("fce354b2", "NotOwnerOrController")

EXPLAIN = {
    "FutureTimestamp": "event timestamp is ahead of chain time (clock skew); the kit now uses block time",
    "NotAuthorizedSubmitter": "the signer is not this machine's owner or controller: use the wallet that activated it",
    "NotOwnerOrController": "the signer is not this machine's owner or controller: use the wallet that activated it",
    "MachineNotFound": "no machine with this ID on this registry: check KIT_MACHINE_ID and EVENT_REGISTRY_ADDRESS",
    "MachineNotBonded": "the machine's subscription bond is not in place: activation incomplete?",
    "MachineDeactivated": "the machine is deactivated",
    "MetadataTooLarge": "metadata over 4096 bytes",
    "InvalidTrustLevel": "trust_level must be 0, 1 or 2",
    "EnforcedPause": "the EventRegistry is paused",
}


_URL = re.compile(r"(https?|wss?)://([^/\s'\"]+)(/[^\s'\"]*)?")


def redact_urls(text: str) -> str:
    """Keep scheme and host, drop the path: private RPC endpoints carry their token there."""
    return _URL.sub(lambda m: f"{m.group(1)}://{m.group(2)}" + ("/…" if (m.group(3) or "").strip("/") else ""), text)


def explain_revert(exc: BaseException) -> str:
    """Turn 'Transaction reverted: (0x0ff02cef, …)' into something a human can act on."""
    text = str(exc)
    for sel, name in _SELECTORS.items():
        if sel in text or f"0x{sel}" in text:
            hint = EXPLAIN.get(name, "")
            return f"{name}()" + (f": {hint}" if hint else "")
    return text


@dataclass
class SubmitResult:
    tx_hash: str
    data_hash: bytes
    timestamp: int


class LostReceipt(Exception):
    """The transaction was broadcast but we never saw its receipt. The event may be on chain."""


def pending_tx_state(client) -> bool | None:
    """True if the signer has a sent transaction that is not mined yet; None if the RPC can't say."""
    try:
        eth, addr = client.web3.eth, client.account.address
        return eth.get_transaction_count(addr, "pending") > eth.get_transaction_count(addr, "latest")
    except Exception as exc:
        log.warning("could not check for pending transactions (%s)", redact_urls(str(exc)))
        return None


def slow_receipt_polling(client, poll_seconds: float = RECEIPT_POLL_SECONDS) -> None:
    """The SDK calls ``web3.eth.wait_for_transaction_receipt(tx_hash)`` with defaults.
    Re-bind it on this client's web3 so every wait polls at ``poll_seconds``."""
    eth = client.web3.eth
    original = eth.wait_for_transaction_receipt

    def patched(tx_hash, timeout: float = 180, poll_latency: float = poll_seconds):
        return original(tx_hash, timeout=timeout, poll_latency=poll_latency)

    eth.wait_for_transaction_receipt = patched  # type: ignore[method-assign]


class EventSubmitter:
    def __init__(self, client, *, machine_id: int, trust_level: int = 0, max_attempts: int = 5, base_delay: float = 2.0) -> None:
        self.client = client
        self.machine_id = machine_id
        self.trust_level = trust_level
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        slow_receipt_polling(client)

    def already_on_chain(self, data_hash: bytes) -> str | None:
        """If an event with this hash already exists for the machine, return a pseudo tx ref."""
        from .chain import EventRegistryReader

        reader = EventRegistryReader.from_client(self.client)
        found = reader.find_by_hash(self.machine_id, "0x" + data_hash.hex())
        return f"on-chain:event#{found[0].index}" if found else None

    def _settle_before_retry(self, payload: EventPayload, ts: int, reason: str) -> SubmitResult | None:
        """A failed call may still have broadcast the transaction. Check the mempool before the
        chain, so a transaction mined in between is still found, and never retry while one
        from this wallet could still land: a second anchor fails verification for good."""
        pending = pending_tx_state(self.client)
        ref = self.already_on_chain(payload.data_hash)
        if ref:
            return SubmitResult(tx_hash=ref, data_hash=payload.data_hash, timestamp=ts)
        if pending is not False:
            raise LostReceipt(f"{reason} (a transaction from this wallet may still be pending; run `armkit resubmit` in a minute)")
        return None

    def _chain_timestamp(self, fallback: int) -> int:
        try:
            block_ts = int(self.client.web3.eth.get_block("latest")["timestamp"])
        except Exception as exc:  # pragma: no cover - RPC hiccup
            log.warning("could not read latest block time (%s); using local clock minus margin", exc)
            block_ts = int(time.time())
        return min(fallback, block_ts) - TIMESTAMP_MARGIN_SECONDS

    def submit(self, payload: EventPayload) -> SubmitResult:
        from peaq_os_sdk.exceptions import RateLimitExceeded, RpcError

        delay = self.base_delay
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            ts = self._chain_timestamp(payload.timestamp)
            try:
                tx_hash, data_hash = self.client.submit_event(
                    machine_id=self.machine_id,
                    event_type=EVENT_TYPE_ACTIVITY,
                    value=int(payload.value),
                    timestamp=ts,
                    raw_data=payload.raw_data,
                    trust_level=int(self.trust_level),
                    source_chain_id=PEAQ_MAINNET_CHAIN_ID,
                    source_tx_hash=None,
                    metadata=payload.metadata,
                )
                if not tx_hash.startswith("0x"):
                    tx_hash = "0x" + tx_hash
                return SubmitResult(tx_hash=tx_hash, data_hash=data_hash, timestamp=ts)
            except RateLimitExceeded as exc:
                last_exc = exc
                log.warning("SDK rate limit hit (attempt %d/%d): %s", attempt, self.max_attempts, exc)
            except RpcError as exc:
                last_exc = exc
                reason = explain_revert(exc)
                lowered = reason.lower()
                if any(k in lowered for k in ("timeout", "not in the chain after", "receipt")):
                    # Broadcast may have succeeded. Never blindly retry: that is how a
                    # segment ends up anchored twice. Check the chain first.
                    ref = self.already_on_chain(payload.data_hash)
                    if ref:
                        return SubmitResult(tx_hash=ref, data_hash=payload.data_hash, timestamp=ts)
                    raise LostReceipt(reason) from exc
                retryable = any(k in lowered for k in ("rate", "429", "temporar", "connection", "futuretimestamp"))
                if not retryable:
                    raise RuntimeError(reason) from exc
                settled = self._settle_before_retry(payload, ts, reason)
                if settled:
                    return settled
                log.warning("RPC error (attempt %d/%d): %s", attempt, self.max_attempts, reason)
            except Exception as exc:  # HTTP/transport errors from web3/requests
                from web3.exceptions import TimeExhausted

                last_exc = exc
                text = str(exc).lower()
                # web3's TimeExhausted ("... is not in the chain after N seconds") means the
                # tx was broadcast and may still be mined: never resend it automatically.
                if isinstance(exc, TimeExhausted) or any(k in text for k in ("timeout", "timed out", "not in the chain after")):
                    ref = self.already_on_chain(payload.data_hash)
                    if ref:
                        return SubmitResult(tx_hash=ref, data_hash=payload.data_hash, timestamp=ts)
                    raise LostReceipt(str(exc)) from exc
                settled = self._settle_before_retry(payload, ts, redact_urls(str(exc)))
                if settled:
                    return settled
                log.warning("transport error (attempt %d/%d): %s", attempt, self.max_attempts, exc)
            if attempt < self.max_attempts:
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
        assert last_exc is not None
        raise RuntimeError(explain_revert(last_exc)) from last_exc


def make_client():
    """Build the SDK client from the environment (``.env`` already loaded by KitSettings).
    Needs ``PEAQOS_PRIVATE_KEY``; the OWS vault path is not supported by the kit."""
    from peaq_os_sdk import PeaqosClient

    return PeaqosClient.from_env()
