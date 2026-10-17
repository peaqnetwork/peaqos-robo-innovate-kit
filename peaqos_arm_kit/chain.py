"""Read-only access to the EventRegistry. No private key needed.

Used by the verifier (and by ``armkit status``) so a judge can check a team's
log with nothing but an RPC URL, the registry address and the machine ID.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources

from web3 import Web3


@dataclass(frozen=True)
class ChainEvent:
    index: int
    machine_id: int
    event_type: int
    value: int
    timestamp: int
    data_hash: str  # 0x-hex
    trust_level: int
    source_chain_id: int
    metadata: bytes
    currency: str


def _event_registry_abi() -> list:
    # The ABI ships inside the SDK package; reuse it rather than vendoring a copy.
    data = resources.files("peaq_os_sdk").joinpath("abis/EventRegistry.json").read_text("utf-8")
    loaded = json.loads(data)
    return loaded if isinstance(loaded, list) else loaded["abi"]


class EventRegistryReader:
    def __init__(self, rpc_url: str, registry_address: str) -> None:
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(registry_address), abi=_event_registry_abi()
        )

    @classmethod
    def from_client(cls, client) -> "EventRegistryReader":
        """Reuse an SDK client's web3 connection and EventRegistry contract."""
        self = cls.__new__(cls)
        self.w3 = client.web3
        self.contract = self.w3.eth.contract(address=client.event_registry.address, abi=_event_registry_abi())
        return self

    def chain_id(self) -> int:
        return self.w3.eth.chain_id

    def find_by_hash(self, machine_id: int, data_hash: str) -> list[ChainEvent]:
        """Every event of ``machine_id`` whose dataHash equals ``data_hash`` (0x-hex)."""
        want = data_hash.lower()
        return [ev for ev in self.events(machine_id) if ev.data_hash.lower() == want]

    def event_count(self, machine_id: int) -> int:
        return int(self.contract.functions.getEventCount(machine_id).call())

    def events(self, machine_id: int, *, offset: int = 0, limit: int | None = None) -> list[ChainEvent]:
        total = self.event_count(machine_id)
        if limit is None:
            limit = total - offset
        max_query = int(self.contract.functions.MAX_QUERY_LIMIT().call())
        out: list[ChainEvent] = []
        cursor = offset
        end = min(total, offset + limit)
        while cursor < end:
            page = min(max_query, end - cursor)
            rows = self.contract.functions.getEvents(machine_id, cursor, page).call()
            for i, row in enumerate(rows):
                out.append(
                    ChainEvent(
                        index=cursor + i,
                        machine_id=int(row[0]),
                        event_type=int(row[1]),
                        value=int(row[2]),
                        timestamp=int(row[3]),
                        data_hash="0x" + bytes(row[4]).hex(),
                        trust_level=int(row[5]),
                        source_chain_id=int(row[6]),
                        metadata=bytes(row[8]),
                        currency=str(row[9]),
                    )
                )
            cursor += page
        return out
