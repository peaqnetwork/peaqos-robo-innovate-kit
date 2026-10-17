# What one event is, and what verify proves

## One event = one move

The segmenter watches joint speed. A segment opens when any joint moves faster than `KIT_VELOCITY_THRESHOLD` (default 0.02 rad/s) and closes once every joint has been below it for `KIT_SETTLE_SECONDS` (0.4 s). Moves shorter than `KIT_MIN_SEGMENT_SECONDS` (0.3 s) are dropped as jitter. A move longer than `KIT_MAX_SEGMENT_SECONDS` (20 s) is split into several segments.

If the robot publishes joint velocities they are used; otherwise the kit differentiates positions.

## What goes where

| Where | What |
|---|---|
| `motion-log/segments/NNNNNN.json` | The full segment: schema, machine ID, declared source (`ros2:/dsr01/joint_states`, `csv:<file>` or `synthetic`), segment index, start and end time, joint names, every sample as `[t_rel_s, q1..qN]`, start and end pose. Stays on your laptop until you hand it in. |
| `motion-log/ledger.jsonl` | The index: a line when a segment is recorded and another when its status changes (the last line per segment counts). |
| on peaq: `dataHash` | keccak256 of the segment file, byte for byte. Change one digit and it no longer matches. |
| on peaq: `metadata` | A short summary: `{"s":"joint_motion/0.1","i":<segment>,"ms":<duration>,"n":<samples>,"j":<joints>,"d":[joint deltas]}` |
| on peaq: `value` | Duration in milliseconds |
| on peaq: `timestamp` | When the segment closed, never ahead of the latest block (minus 5 s, since laptop clocks drift) |
| on peaq: `trustLevel` | 0 (self-reported). 1 means onchain verifiable, 2 means hardware-signed: only claim them if you can show why. |

Segment files are canonical JSON (keys sorted, no whitespace, positions rounded to 1e-5 rad, times to 1 ms), so the same segment always gives the same bytes and the same hash.

The `source` field is inside the hashed file, so it is fixed when you record. `armkit verify` shows it; judges read your declared source from there.

## What `armkit verify` checks

It needs the log folder, the machine ID and an RPC URL, and no private key. It checks that it is talking to peaq mainnet (chain 3338) and that the log isn't empty, then for every segment:

1. The file still hashes to the value in the ledger (catches an edited log).
2. The file is well-formed for this machine: right schema and machine ID, consistent samples, time increasing (catches nonsense that happens to hash).
3. An event with exactly that hash exists under your machine ID (catches a segment that was never put on record; `failed`, `pending` and `dry-run` segments fail here).
4. The on-chain summary matches the file (catches a hash reused with a different description).

Finally it lists every motion event on peaq under your machine ID that has no segment in the log, and fails the run on it. So every move you put on record must be in the log you hand in. Events with other metadata are listed as information only.

`armkit verify --json` gives the same report as JSON.

## What it proves, and what it doesn't

A passing verify proves the log you hand in is exactly the log your robot's identity put on record, at the times peaq shows. It does not prove the motion came from a robot rather than a script. Making that provable is a good thing to build: sign each segment with the robot's own key (the Ed25519 key `setup.sh` creates, listed in its DID document) and teach the verifier to check the signature. The kit only submits `trust_level` 0; if you build signing, change `_trust_level` in `peaqos_arm_kit/config.py` and explain it in your runbook.

## Things to know this week

- **Each event is one transaction**, about 0.04 PEAQ from your wallet. A move every few seconds is fine; submitting every sample of a 100 Hz topic is not.
- **The SDK limits how fast one machine can submit.** The kit backs off and retries; anything that still fails is marked `failed` in the ledger and `armkit resubmit` sends it later.
- **Your MCR rating stays `Provisioned`.** A rating needs history over a longer time. It isn't part of the scoring.
