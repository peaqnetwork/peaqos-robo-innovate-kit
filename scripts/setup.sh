#!/usr/bin/env bash
# One-time setup for a team: write .env, create a wallet, activate the robot's peaqID.
#
#   PEAQOS_RPC_URL=https://<hackathon-endpoint> TEAM=blue bash scripts/setup.sh
#
# Safe to re-run: an existing .env with a key is kept (so a funded wallet is never
# lost), and an existing KIT_MACHINE_ID skips activation.
# Needs: the kit installed (pip install -e .), and a mentor to fund the wallet it
# prints before the activate step. Fund 1.5 PEAQ: bond ~0.5 (USD-priced, moves) +
# 0.05 headroom the CLI insists on + ~0.09 activation gas + ~0.04 per event.
set -euo pipefail
KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TEAM="${TEAM:?set TEAM=<short team name>, it becomes part of the machine identity}"
if [[ ! "$TEAM" =~ ^[a-z0-9-]{1,32}$ ]]; then
  echo "TEAM must be 1-32 characters of a-z, 0-9 and '-' (it goes into the DID document URL and the machine identity)" >&2
  exit 2
fi
MACHINE_TYPE="${MACHINE_TYPE:-robo-innovate-2026-a0509}"
: "${PEAQOS_RPC_URL:?set PEAQOS_RPC_URL to the hackathon endpoint mentors handed out}"

mask_url() { python3 - "$1" <<'EOF'
import sys; from urllib.parse import urlsplit
u = urlsplit(sys.argv[1]); print(f"{u.scheme}://{u.hostname}" + ("/…" if u.path.strip("/") else ""))
EOF
}

env_get() { python3 - "$1" <<'EOF'
import sys; from dotenv import dotenv_values
print(dotenv_values(".env").get(sys.argv[1]) or "")
EOF
}

# ---------------------------------------------------------------- 1/5 .env
if [[ -f .env && -n "$(env_get PEAQOS_PRIVATE_KEY)" ]]; then
  echo "== 1/5 .env exists with a key; keeping it (RPC: $(mask_url "$(env_get PEAQOS_RPC_URL)"))"
  if [[ -n "${PEAQOS_PRIVATE_KEY:-}" && "$PEAQOS_PRIVATE_KEY" != "$(env_get PEAQOS_PRIVATE_KEY)" ]]; then
    echo "PEAQOS_PRIVATE_KEY in your shell differs from the key in .env. Unset it (unset PEAQOS_PRIVATE_KEY) so setup uses one wallet." >&2
    exit 2
  fi
  chmod 600 .env
else
  echo "== 1/5 writing .env for peaq mainnet (RPC: $(mask_url "$PEAQOS_RPC_URL"))"
  if [[ -z "${PEAQOS_PRIVATE_KEY:-}" ]]; then
    # Non-interactive `peaqos init` takes a private key, not a vault wallet. A fresh
    # key for a wallet that will hold ~1.5 PEAQ for a week is fine; .env is chmod 600.
    echo "   generating a new team key"
    PEAQOS_PRIVATE_KEY="$(python3 -c 'from eth_account import Account; print("0x" + Account.create().key.hex().removeprefix("0x"))')"
    export PEAQOS_PRIVATE_KEY
  fi
  # `peaqos init` prints the full RPC URL (whoami); a private endpoint keeps its token in the path
  PEAQOS_NETWORK=mainnet peaqos init --non-interactive --force 2>&1 | sed -E 's#((https?|wss?)://[^/[:space:]]+)/[^[:space:]]+#\1/…#g'
  chmod 600 .env
  cat >> .env <<EOF

# ---- peaqos-arm-kit ----
KIT_MACHINE_ID=
KIT_ARM_MACHINE_ID=15083021071335353053994705927780059101231441765380432097794409355707727094755
KIT_JOINT_SOURCE=synthetic
KIT_ROS2_TOPIC=/dsr01/joint_states
KIT_LOG_DIR=./motion-log
KIT_TRUST_LEVEL=0
EOF
fi

# `peaqos init` fetches the legacy contract addresses from GitHub and, if that
# fetch fails, writes them EMPTY and still exits 0 (CLI 0.0.19). Fill in the
# pinned mainnet values so activation does not stop on "Missing required env var".
python3 - <<'EOF'
import re, pathlib
import os
def save(p, t):  # write a temp file and rename it, so a crash never leaves .env (and its key) half-written
    tmp = p.with_name(".env.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(t); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)
pinned = {
    "IDENTITY_REGISTRY_ADDRESS": "0xb53Af985765031936311273599389b5B68aC9956",
    "IDENTITY_STAKING_ADDRESS":  "0x11c05A650704136786253e8685f56879A202b1C7",
    "EVENT_REGISTRY_ADDRESS":    "0xA1e7F1d7B24dAb55Dc92491e6d9B89F6E925Ad1e",
    "MACHINE_NFT_ADDRESS":       "0x2943F80e9DdB11B9Dd275499C661Df78F5F691F9",
    "DID_REGISTRY_ADDRESS":      "0x0000000000000000000000000000000000000800",
    "BATCH_PRECOMPILE_ADDRESS":  "0x0000000000000000000000000000000000000805",
}
p = pathlib.Path(".env"); t = p.read_text(); filled = []
for k, v in pinned.items():
    m = re.search(rf"^{k}=(.*)$", t, re.M)
    if m is None:
        t += f"\n{k}={v}"; filled.append(k)
    elif not m.group(1).strip():
        t = t[:m.start(1)] + v + t[m.end(1):]; filled.append(k)
save(p, t)
if filled:
    print("   peaqos init left these empty (address download failed); filled pinned mainnet values: " + ", ".join(filled))
EOF
echo "   if peaqos init printed a 'whoami verification failed' warning above, ignore it: armkit check at the end is the check that counts"

unset PEAQOS_PRIVATE_KEY  # from here on the key comes from .env only, so every step uses the same wallet
SIGNER="$(python3 -c 'import os; from dotenv import load_dotenv; load_dotenv(".env"); from eth_account import Account; print(Account.from_key(os.environ["PEAQOS_PRIVATE_KEY"]).address)')"

# ---------------------------------------------------------------- 2/5 DID document
echo "== 2/5 the robot's DID document (its own Ed25519 key)"
python3 "$KIT_DIR/scripts/make_did_document.py" --controller "$SIGNER" --team "$TEAM" >/dev/null
echo "   arm-ed25519.key + did.json written (reused if they already existed)"

# ---------------------------------------------------------------- 3/5 funding
if [[ -n "$(env_get KIT_MACHINE_ID)" ]]; then
  echo "== 3/5 KIT_MACHINE_ID already set ($(env_get KIT_MACHINE_ID)); skipping activation"
  echo "done. next: armkit check"
  exit 0
fi

echo "== 3/5 your team wallet: $SIGNER"
echo "   Ask a mentor to fund it with 1.5 PEAQ (mentors: scripts/fund_teams.py), then press Enter."
read -r || { echo "no input at the funding prompt; re-run this script once the wallet is funded (your key is kept)" >&2; exit 1; }

# The credential subject fixes the machine ID forever. It includes the team wallet
# address so nobody can take a team's name first and own that ID.
SUBJECT_HEX="0x$(python3 -c 'import sys; print(("robo-innovate-2026/" + sys.argv[1] + "/" + sys.argv[2].lower()).encode().hex())' "$TEAM" "$SIGNER")"

# ---------------------------------------------------------------- 4/5 activate
echo "== 4/5 activating the robot identity (Entry tier) for team $TEAM"
# --manufacturer is recorded on chain and never verified; Doosan has no peaq address,
# so the team signer stands in for it.
set +e
OUT="$(peaqos activate \
  --machine-type "$MACHINE_TYPE" \
  --credential-subject-hex "$SUBJECT_HEX" \
  --manufacturer "$SIGNER" \
  --did-document ./did.json \
  --tier entry --skip-funding --yes --json 2>&1)"
RC=$?
set -e
echo "$OUT"
if [[ $RC -ne 0 ]]; then
  echo
  echo "activation failed (exit $RC). Your key is still in .env: do NOT delete it." >&2
  echo "Fix the cause above (usually funding) and re-run this script; it resumes here." >&2
  exit $RC
fi
MACHINE_ID="$(printf '%s' "$OUT" | python3 -c 'import json,sys,re
raw = sys.stdin.read(); m = re.search(r"\{.*\}", raw, re.S)
print(json.loads(m.group(0))["machine_id"] if m else "")')"
if [[ -z "$MACHINE_ID" ]]; then
  echo "activation output had no machine_id; see above" >&2; exit 1
fi

# ---------------------------------------------------------------- 5/5 store
echo "== 5/5 writing KIT_MACHINE_ID=$MACHINE_ID"
python3 - "$MACHINE_ID" <<'EOF'
import re, sys, pathlib
import os
def save(p, t):  # write a temp file and rename it, so a crash never leaves .env (and its key) half-written
    tmp = p.with_name(".env.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(t); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)
p = pathlib.Path(".env"); t = p.read_text()
line = f"KIT_MACHINE_ID={sys.argv[1]}"
if re.search(r"^KIT_MACHINE_ID=.*$", t, flags=re.M):
    t = re.sub(r"^KIT_MACHINE_ID=.*$", line, t, flags=re.M)
else:  # an .env from a plain `peaqos init` has no kit block yet
    t = t.rstrip("\n") + "\n\n# ---- peaqos-arm-kit ----\n" + line + "\n"
save(p, t)
EOF
grep -q "^KIT_MACHINE_ID=$MACHINE_ID$" .env || { echo "could not write KIT_MACHINE_ID to .env; add it by hand: KIT_MACHINE_ID=$MACHINE_ID" >&2; exit 1; }

echo
echo "done. next: armkit check, then try it without spending PEAQ: KIT_LOG_DIR=./dev-log armkit record --source synthetic --fast"
echo "      (motion-log/ is for the run you hand in; keep test runs out of it)"
