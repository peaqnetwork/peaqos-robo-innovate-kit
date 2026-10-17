# peaqOS for this challenge

You need three things from peaqOS: a **machine identity** for the arm (a peaqID, which is also a machine ID the EventRegistry knows), a **funded wallet** that owns it, and the **`submit_event`** call. Everything else in the SDK (Stream, Scale, Verify, Solana) is out of scope this week.

## Setup, step by step (what `scripts/setup.sh` does)

```bash
# 1. a key for the team wallet (the kit needs PEAQOS_PRIVATE_KEY; the CLI's OWS vault is not wired in)
export PEAQOS_PRIVATE_KEY=$(python3 -c 'from eth_account import Account; print("0x" + Account.create().key.hex().removeprefix("0x"))')

# 2. .env for peaq mainnet, pointing at the hackathon RPC endpoint
PEAQOS_NETWORK=mainnet PEAQOS_RPC_URL=https://<hackathon-endpoint> peaqos init --non-interactive
chmod 600 .env

# 3. the arm's DID document: its own Ed25519 key, controlled by your signer
peaqos whoami                                   # shows the signer address
python scripts/make_did_document.py --controller 0x<signer> --team blue
#    -> arm-ed25519.key (keep it on the robot PC) and did.json

# 4. get the wallet funded: 1.5 PEAQ. The Entry bond is ~0.5 PEAQ (priced in USD, so it moves;
#    0.5058 on Oct 15), the CLI insists on 0.05 headroom, activation gas was ~0.09, and each
#    event costs ~0.035-0.045. 1.5 covers activation plus ~20 events; mentors top up after that.

# 5. activate the arm's identity. machine-type + credential-subject fix the ID forever.
peaqos activate \
  --machine-type robo-innovate-2026-a0509 \
  --credential-subject-hex 0x$(python3 -c "print('robo-innovate-2026/blue/0x<signer, lowercase>'.encode().hex())") \
  --manufacturer 0x<signer> \
  --did-document ./did.json \
  --tier entry --skip-funding --yes --json
# -> copy "machine_id" into .env as KIT_MACHINE_ID
```

`--manufacturer` is recorded on chain and never verified; Doosan has no peaq address, so the team signer stands in. `--dry-run` shows the machine ID and the bond quote but exits 2 with `INSUFFICIENT_PEAQ` on an unfunded wallet, so you cannot fully preview before funding: that is a known CLI limitation, not a mistake on your side.

Why `--skip-funding`: without it, a wallet below the bond triggers the Gas Station faucet flow, which enrols 2FA interactively and is rate-limited per IP. Ten people on one venue network should not go through that. Get funded first, then activate.

Why mainnet: the agung testnet has no Tokenomics 2.0 EventRegistry, so events cannot be submitted there.

## The event call

The kit wraps it, but this is all it is:

```python
import time
from dotenv import load_dotenv; load_dotenv()      # from_env() does not load .env itself
from peaq_os_sdk import PeaqosClient
client = PeaqosClient.from_env()
tx_hash, data_hash = client.submit_event(
    machine_id=MACHINE_ID, event_type=1,           # 1 = activity
    value=duration_ms,
    timestamp=min(int(time.time()), client.web3.eth.get_block("latest")["timestamp"]) - 5,  # never ahead of the chain
    raw_data=canonical_bytes, trust_level=0,
    source_chain_id=3338, source_tx_hash=None,
    metadata=summary_bytes,                        # <= 4096 bytes
)
```

The SDK computes `keccak256(raw_data)` and sends only the hash. The caller must be the machine's owner wallet, or a controller it names: for the kit, the wallet that activated it.

## Reading back

`EventRegistry.getEventCount(machineId)` and `getEvents(machineId, offset, limit)` (limit ≤ 100) return every event with its hash and metadata. `peaqos_arm_kit/chain.py` does this with plain web3 and the ABI shipped in the SDK, so a verifier needs no peaqOS account at all.

## Your identity, in one line

Same `--machine-type` and `--credential-subject-hex` always derive the same machine ID. The kit's credential subject is `robo-innovate-2026/<team>/<signer address>`, so a team name cannot be claimed by someone else first. If you lose `.env` but keep the wallet, re-run `activate --dry-run` with the same values: the preview shows the same machine ID.

## Versions

`peaq-os-sdk 0.11.2`, `peaq-os-cli 0.0.19` (needs click ≥ 8.4). Python 3.10 or newer. Older SDK/CLI combinations will not have the 2.0 event path; `pip install -e .` pins them.
