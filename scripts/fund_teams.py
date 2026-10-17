#!/usr/bin/env python3
"""Mentor tool: top up team wallets from a treasury wallet to a target balance.

    read -rs TREASURY_PRIVATE_KEY && export TREASURY_PRIVATE_KEY   # paste the key; not echoed, not in shell history
    export PEAQOS_RPC_URL=https://...
    python scripts/fund_teams.py 0xTeamA 0xTeamB            # dry run: shows what it would send
    python scripts/fund_teams.py 0xTeamA 0xTeamB --send     # really sends, after a y/N prompt

Sends only the difference between the current balance and --target (default 1.5
PEAQ, capped at --max-target 5), so it is safe to re-run during the week; it refuses
to plan while a treasury transfer is still pending. Checks
the chain id (3338), checks each receipt's status, and keeps going if one
transfer times out.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from web3 import Web3

PEAQ_MAINNET = 3338


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("addresses", nargs="+", help="team wallet addresses (0x…)")
    p.add_argument("--target", type=float, default=1.5, help="target balance in PEAQ (default 1.5)")
    p.add_argument("--max-target", type=float, default=5.0, help="refuse targets above this (default 5)")
    p.add_argument("--send", action="store_true", help="actually send; without it this is a dry run")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt (CI use)")
    p.add_argument("--chain-id", type=int, default=PEAQ_MAINNET)
    args = p.parse_args()

    if args.target > args.max_target:
        print(f"--target {args.target} exceeds --max-target {args.max_target}", file=sys.stderr)
        return 2
    rpc = os.environ.get("PEAQOS_RPC_URL")
    key = os.environ.get("TREASURY_PRIVATE_KEY")
    if not rpc or not key:
        print("set PEAQOS_RPC_URL and TREASURY_PRIVATE_KEY in the environment", file=sys.stderr)
        return 2

    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 30}))
    chain_id = w3.eth.chain_id
    if chain_id != args.chain_id:
        print(f"connected to chain {chain_id}, expected {args.chain_id}; refusing", file=sys.stderr)
        return 2
    treasury = w3.eth.account.from_key(key)
    target_wei = w3.to_wei(args.target, "ether")
    tbal = w3.eth.get_balance(treasury.address)
    print(f"chain {chain_id}  treasury {treasury.address}  balance {w3.from_wei(tbal, 'ether')} PEAQ")

    if w3.eth.get_transaction_count(treasury.address, "pending") > w3.eth.get_transaction_count(treasury.address, "latest"):
        # its balance change isn't visible yet, so planning now would send the same top-up twice
        print("a transfer from the treasury is still pending; wait until it is mined (check the explorer), then run this again", file=sys.stderr)
        return 2
    plan = []
    seen: set[str] = set()
    for raw in args.addresses:
        to = Web3.to_checksum_address(raw)
        if to in seen:
            print(f"{to}: listed twice, skipping the duplicate")
            continue
        seen.add(to)
        if int(to, 16) == 0:
            print("refusing to fund the zero address", file=sys.stderr)
            return 2
        have = w3.eth.get_balance(to)
        need = target_wei - have
        if need <= 0:
            print(f"{to}: {w3.from_wei(have, 'ether')} PEAQ, nothing to send")
        else:
            print(f"{to}: {w3.from_wei(have, 'ether')} -> send {w3.from_wei(need, 'ether')} PEAQ")
            plan.append((to, need))
    total = sum(n for _, n in plan)
    print(f"total to send: {w3.from_wei(total, 'ether')} PEAQ to {len(plan)} wallet(s)")
    if not plan:
        return 0
    gas_reserve = len(plan) * 21000 * w3.eth.gas_price * 2
    if total + gas_reserve > tbal:
        print(f"treasury balance is too low for this plan plus gas ({w3.from_wei(total + gas_reserve, 'ether')} PEAQ needed)", file=sys.stderr)
        return 2
    if not args.send:
        print("dry run: add --send to transfer")
        return 0
    if not args.yes and input("send now? [y/N] ").strip().lower() != "y":
        print("aborted")
        return 1

    nonce = w3.eth.get_transaction_count(treasury.address, "pending")
    failures = 0
    for to, need in plan:
        tx = {
            "to": to, "value": need, "nonce": nonce, "chainId": chain_id, "gas": 21000,
            "maxFeePerGas": w3.eth.gas_price * 2, "maxPriorityFeePerGas": w3.to_wei(1, "gwei"),
        }
        signed = treasury.sign_transaction(tx)
        raw_tx = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        try:
            tx_hash = w3.eth.send_raw_transaction(raw_tx)
            nonce += 1
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120, poll_latency=1.5)
            if receipt["status"] != 1:
                failures += 1
                print(f"{to}: tx {tx_hash.hex()} REVERTED")
            else:
                print(f"{to}: funded, tx {tx_hash.hex()}")
        except Exception as exc:  # timeout or RPC error: report and continue with the next team
            failures += 1
            msg = re.sub(r"((?:https?|wss?)://[^/\s'\"]+)/[^\s'\"]+", r"\1/…", str(exc))  # private RPC token
            print(f"{to}: FAILED ({type(exc).__name__}: {msg}); check the explorer before retrying")
            nonce = w3.eth.get_transaction_count(treasury.address, "pending")  # resync, counting a send still in the mempool
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
