# The peaqOS calls behind the kit

You only need this page if you want to go below the kit. Three things from peaqOS are used: a machine identity (peaqID), a funded wallet that owns it, and the `submit_event` call. The rest of peaqOS is out of scope this week.

## What `scripts/setup.sh` does

README step 2 runs it for you, once per team. These are the steps inside it, for when you want to go lower. Read them, don't run them: in a folder that already has your `.env`, step 2 overwrites it and your wallet key is gone.

```bash
# 1. a new wallet key for the team
export PEAQOS_PRIVATE_KEY=$(python3 -c 'from eth_account import Account; print("0x" + Account.create().key.hex().removeprefix("0x"))')

# 2. .env for peaq mainnet, with the hackathon RPC URL
PEAQOS_NETWORK=mainnet PEAQOS_RPC_URL=<RPC URL from the card> peaqos init --non-interactive --force
chmod 600 .env

# 3. the robot's own Ed25519 key and DID document, controlled by your wallet
python scripts/make_did_document.py --controller 0x<your wallet> --team <team>
#    -> arm-ed25519.key (keep it private) and did.json

# 4. wait until a mentor has sent 1.5 PEAQ: about 0.6 for activation, the rest pays for about 20 events

# 5. create the peaqID. Machine type + credential subject fix the machine ID forever.
peaqos activate \
  --machine-type robo-innovate-2026-a0509 \
  --credential-subject-hex 0x$(python3 -c "print('robo-innovate-2026/<team>/0x<your wallet, lowercase>'.encode().hex())") \
  --manufacturer 0x<your wallet> \
  --did-document ./did.json \
  --tier entry --skip-funding --yes --json
# -> "machine_id" goes into .env as KIT_MACHINE_ID
```

The credential subject includes your wallet address, so nobody else can claim your team name first. `--skip-funding` avoids the faucet flow, which asks for 2FA and is rate-limited per IP.

## The event call

The kit wraps it, but this is all it is:

```python
from dotenv import load_dotenv; load_dotenv()      # from_env() does not load .env itself
from peaq_os_sdk import PeaqosClient
client = PeaqosClient.from_env()
tx_hash, data_hash = client.submit_event(
    machine_id=MACHINE_ID, event_type=1,           # 1 = activity
    value=duration_ms,
    timestamp=segment_end_unix,                    # the kit caps this at the latest block time minus 5 s
    raw_data=canonical_bytes, trust_level=0,
    source_chain_id=3338, source_tx_hash=None,
    metadata=summary_bytes,                        # up to 4096 bytes
)
```

The SDK computes `keccak256(raw_data)` and sends only the hash. Only the machine's owner wallet, or a controller it names, can submit.

## Reading events back

`EventRegistry.getEventCount(machineId)` and `getEvents(machineId, offset, limit)` (limit up to 100) return every event with its hash and metadata. `peaqos_arm_kit/chain.py` does this with plain web3, so verifying needs no wallet.

Versions: `peaq-os-sdk` 0.11.2, `peaq-os-cli` 0.0.19, Python 3.10+, peaq mainnet (chain 3338), EventRegistry `0xA1e7F1d7B24dAb55Dc92491e6d9B89F6E925Ad1e`. Docs: [docs.peaq.xyz](https://docs.peaq.xyz).
