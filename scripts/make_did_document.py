#!/usr/bin/env python3
"""Generate the arm's Ed25519 signing key and the DID document `peaqos activate` needs.

    python scripts/make_did_document.py --controller 0xYourSignerAddress [--team blue]

Writes:
    arm-ed25519.key   hex private key, mode 0600: keep it on the robot PC
    did.json          the --did-document for activation

The key is the arm's own identity key. The kit does not use it yet (events are
trust_level 0); signing each segment with it before hashing is the natural
upgrade a team can build during the week.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def base58btc(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    pad = len(data) - len(data.lstrip(b"\0"))
    return "1" * pad + out


def multibase_ed25519(public_key: bytes) -> str:
    # multicodec ed25519-pub = 0xed01, multibase base58btc prefix 'z'
    return "z" + base58btc(b"\xed\x01" + public_key)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--controller", required=True, help="the team signer address (0x…), from `peaqos whoami`")
    p.add_argument("--team", default="team")
    p.add_argument("--key-file", default="arm-ed25519.key")
    p.add_argument("--out", default="did.json")
    args = p.parse_args()

    key_path = Path(args.key_file)
    if key_path.exists():
        priv_hex = key_path.read_text().strip()
        priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_hex.removeprefix("0x")))
        os.chmod(key_path, 0o600)
        print(f"reusing {key_path} (0600)")
    else:
        priv = Ed25519PrivateKey.generate()
        priv_hex = priv.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
        ).hex()
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # never world-readable, not even briefly
        with os.fdopen(fd, "w") as fh:
            fh.write(priv_hex + "\n")
        print(f"wrote {key_path} (0600)")

    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    doc = {
        "verificationMethods": [
            {
                "id": "#arm-ed25519",
                "methodType": "Ed25519VerificationKey2020",
                "controller": args.controller,
                "publicKeyMultibase": multibase_ed25519(pub),
            }
        ],
        "authentication": [0],
        "serviceEndpoints": [
            {
                "id": "#motion-log",
                "serviceType": "RoboInnovateMotionLog",
                "serviceEndpoint": f"https://robo-innovate.local/{args.team}/motion-log",
            }
        ],
    }
    Path(args.out).write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {args.out}")
    print(json.dumps(doc, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
