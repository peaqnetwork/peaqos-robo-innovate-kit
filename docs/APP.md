# The app: what one event is, and how a judge reads it

## One event = one motion segment

The segmenter watches joint speed. When any joint exceeds `KIT_VELOCITY_THRESHOLD` (default 0.02 rad/s) a segment opens; it closes once every joint has been below the threshold for `KIT_SETTLE_SECONDS` (0.4 s). Segments whose active motion is shorter than `KIT_MIN_SEGMENT_SECONDS` are dropped as jitter. A segment longer than `KIT_MAX_SEGMENT_SECONDS` is split, so one long move becomes several events rather than one oversized payload.

If the controller publishes joint velocities they are used directly; otherwise positions are differentiated.

## What goes where

| Where | What | Why |
|---|---|---|
| `motion-log/segments/NNNNNN.json` | the full segment: schema id, machine id, **declared source** (`ros2:/dsr01/joint_states`, `csv:<file>`, `synthetic`), segment index, start/end time (source clock), joint names, every sample as `[t_rel_s, q1..qN]`, start and end pose | this is `raw_data`. It never leaves the robot PC unless the team hands it over. |
| on chain `dataHash` | keccak256 of that file, byte for byte | the anchor. Change one digit in the file and it no longer matches. |
| on chain `metadata` | `{"s":"joint_motion/0.1","i":<segment>,"ms":<duration>,"n":<samples>,"j":<joints>,"d":[joint deltas]}` | so the chain alone says what each event was, and the verifier can cross-check the file against it |
| on chain `value` | duration in milliseconds | activity events need an integer; duration is the honest one |
| on chain `timestamp` | time the segment closed, capped at the latest block time, minus 5 s | the registry rejects timestamps ahead of the block, and laptop clocks drift |
| on chain `trustLevel` | 0 (self-reported) by default | 1 and 2 mean "on-chain verifiable" and "hardware-signed". Only claim them if you can show why. |
| `motion-log/ledger.jsonl` | append-only: a line when a segment is recorded, another when its status changes (hash, metadata, raw file, status, tx hash); the last line per segment wins | the index a judge starts from |

Canonical form: UTF-8 JSON, keys sorted, no whitespace, positions rounded to 1e-5 rad, times to 1 ms. Same segment in, same bytes out, on any machine, which is what makes the hash reproducible.

## Declared input source

The `source` field is part of the hashed document, so it is fixed at recording time and shown by `armkit verify`. Synthetic and CSV are for building and testing; the run a team hands in comes from the Doosan emulator, a ROS 2 simulator or a real robot, and the source field is how the team declares which. Judges read it off the verifier output.

## What the verifier checks

`armkit verify` needs the log folder, the machine ID and an RPC URL. No private key.

It checks the connection is peaq mainnet (3338) and the log is not empty, then for every segment in the ledger:

1. Does the raw file still hash to the value the ledger claims? Catches a log edited after the fact.
2. Is the document well-formed for this machine: right schema, this `machine_id`, sample rows of the right width, finite values, time increasing, poses matching the first and last sample? Catches nonsense that happens to hash correctly.
3. Is there an on-chain event for this machine with exactly that hash? Catches a segment that was never anchored. Segments the ledger marks `failed`, `pending` or `dry-run` fail here. `--include-pending` only stops each dry-run segment being reported as a run-level problem; they still fail.
4. Does the on-chain summary agree with the file: sample count, joint count, duration, segment index, joint deltas, and `value`? Catches a hash reused under a different description.

Then it lists every `joint_motion` event on chain for the machine that has no matching segment in the log and fails the run on it, so a team cannot quietly drop a move from the log it hands in. Events with other metadata on the same machine are listed as information and not judged. This means earlier motion test events under the same identity fail a final hand-in: keep dry runs in their own folder, use a fresh identity for the final run, or hand in the complete log.

`armkit verify --json` gives the same report as JSON for scoring scripts.

## Your run versus the arm's demo

The pendant module on the real A0509 anchors its demo movements the same way: a hash and a summary on chain under the arm's peaqID. The difference is that its raw motion data stays on the controller, so nobody outside can recompute the hash. For the arm, "verified" means "the transaction exists and came from the arm's identity". For your run, `armkit verify` goes all the way: the raw log is in your hands, the hash is recomputed, and every segment is accounted for. That gap is the point of the challenge, not a flaw in it: show what full verifiability looks like.

## What this does and does not prove

It proves the log the team hands in is the same log whose hashes the robot's identity anchored, at the times the chain says. It does not by itself prove the data came from the robot rather than from a script. Making that provable is a legitimate thing to build during the week: sign the canonical bytes with the robot's DID key before hashing, and show the verifier how to check the signature against the DID document. The kit itself submits self-reported events (`trust_level` 0); if you build signing, change `_trust_level` in `peaqos_arm_kit/config.py` and explain it in your runbook.

## Things the chain will not do for you during the hackathon

- **MCR will not move.** The Machine Credit Rating stays "Provisioned" until a machine has 5 activity events or 3 revenue days spread over at least 30 days. Your events count; the score just won't change this week.
- **One transaction per event, ~0.035 to 0.045 PEAQ each.** Each segment costs gas from the team wallet. A busy arm producing a move every few seconds is fine; a 200 Hz loop submitting every sample is not. Segment, don't stream.
- **The SDK has a client-side rate limit** (sliding window per machine). The submitter backs off and retries; failures are recorded in the ledger with `status: failed` and can be resubmitted later.
