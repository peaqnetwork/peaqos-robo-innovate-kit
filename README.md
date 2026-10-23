# Every Move On Record: peaqOS starter kit

Starter kit for the peaq × Doosan track at Robo.innovate 2026 (Munich, Oct 23-28).

Give a robot its own identity on peaq, put every move it makes on record, and prove the record is real. You need Python, and either ROS 2 on Ubuntu or Docker (Mac, Windows) for the robot emulator. You don't need any blockchain experience: the kit and the peaq mentors handle that part.

## The idea in one minute

A robot's work usually lives in a log file its owner controls and can edit. That makes it hard for anyone else (a customer paying per task, an insurer, a lender) to trust what the robot did.

With peaqOS, the robot gets its own identity on peaq, a public blockchain. Every move it makes is written there as a short entry that nobody can change afterwards. The full motion data stays on your laptop. Anyone with your log can then check, move by move, that it matches what was put on record.

The words you'll see in this repo:

| Word | What it means here |
|---|---|
| **peaqID / machine ID** | Your robot's identity on peaq. You create it once per team with `scripts/setup.sh` (step 2); a mentor funds it. |
| **Segment** | One move: from when a joint starts moving until the arm is still again. |
| **Event** | One segment on record: a fingerprint (hash) of the move's data plus a short summary (duration, sample count, how far each joint moved). |
| **Motion log** | The `motion-log/` folder on your laptop: the full data of every segment. This is what you hand in. |
| **Wallet / PEAQ** | The key that is allowed to write your robot's record, and the token that pays for it. Each event costs about 0.04 PEAQ (well under one cent). Mentors fund your wallet. |
| **RPC URL** | The address your laptop uses to talk to peaq. Use the one on the printed card. |
| **Transaction** | One write to peaq, signed by your wallet. Each event is one transaction and takes a few seconds to confirm. |
| **Verify** | `armkit verify` re-hashes every segment in your log, finds it on peaq, and checks nothing was edited or left out. It needs no key, so a judge can run it. |

```
joint states ──▶ segmenter ──▶ segment file ──▶ hash ──▶ event on peaq
 (emulator /      (one per       (kept in          (keccak256)  (one per move,
  ROS 2 robot)     move)          motion-log/)                   under your peaqID)
                                                        ▲
                                    armkit verify ──────┘  re-hash the file and compare
```

You build and record with the Doosan emulator or your own ROS 2 robot, where you hold the raw log and can verify every move. On site there is also a real Doosan A0509 that runs peaqOS. When it is ready, every team gets a slot: you run its pre-configured moves, and they go on peaq under a separate arm identity a mentor creates for your team, so they never mix with your own log. Ask the mentor for that identity's machine ID; `armkit status --machine-id <arm ID>` shows those moves.

## What you need

- Python 3.10 or newer (macOS's built-in `python3` is 3.9: use `brew install python@3.12`)
- A robot that publishes ROS 2 joint states: the Doosan A0509 emulator (recommended, see [docs/ARM.md](docs/ARM.md); on a Mac use the Docker setup in [docker/README.md](docker/README.md)), or your own ROS 2 robot or simulator
- From the peaq mentors at the event: the RPC URL (printed card on your table) and PEAQ for your wallet (step 2)

## 1. Try it in five minutes (no robot, nothing sent)

On a Mac, `brew install python@3.12` first. On Ubuntu 22.04, use `python3` where it says `python3.12`.

```bash
git clone https://github.com/peaqnetwork/peaqos-robo-innovate-kit.git
cd peaqos-robo-innovate-kit
python3.12 -m venv .venv && source .venv/bin/activate
pip install -U pip && pip install -e ".[dev]"
pytest
```

`pytest` runs 40 tests. Then a fake six-axis arm, in its own log folder, with nothing sent anywhere:

```bash
export KIT_ENV_FILE=.env.example KIT_MACHINE_ID=1 KIT_LOG_DIR=./demo-log
armkit record --source synthetic --fast
cat demo-log/ledger.jsonl
armkit verify --include-pending
unset KIT_ENV_FILE KIT_MACHINE_ID KIT_LOG_DIR
```

`ledger.jsonl` is the index of your log: a line per move, plus one per status update. `armkit verify` shows what the verifier checks; it fails here because nothing is on peaq yet. The `unset` line matters: without it, `armkit` keeps using the demo settings in this terminal.

## 2. Get your robot's identity (once per team)

One person runs this, once, on the laptop that will record your hand-in run, in this folder with the venv active. Your team name is 1-28 characters of a-z, 0-9 and `-`; it becomes part of your robot's identity for good. The RPC URL is on the printed card.

```bash
TEAM=<your-team> PEAQOS_RPC_URL=<RPC URL from the card> scripts/setup.sh
```

It writes `.env` (your settings and wallet key), `did.json` and `arm-ed25519.key` (the robot's own key), then prints `your team wallet: 0x...` and waits. Put that address in the team sheet (QR code on your table) and tell a peaq mentor. While you wait, start step 3 in another terminal. When the mentor says it's funded, press Enter: the script creates your peaqID and prints `done`. Then:

```bash
armkit check
```

It works when `machine id` is a long number, `chain id` is 3338, `balance` is about 0.85 PEAQ and `events on chain` is 0. `chain: unreachable` instead: see [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

Run `setup.sh` once per team, in this folder. Running it again here is safe (it keeps your key); running it in another folder creates a second identity. The three files are git-ignored: keep them private, and never delete `.env`, it holds your wallet key and there is no reset.

## 3. Start your robot

Run the Doosan emulator ([docs/ARM.md](docs/ARM.md), or [docker/README.md](docker/README.md) on a Mac) so it publishes `/dsr01/joint_states`. Any other ROS 2 `JointState` topic works too (set `KIT_ROS2_TOPIC`).

If the emulator runs on your own laptop, run `export ROS_LOCALHOST_ONLY=1` in every terminal so you don't record another team's robot on the shared Wi-Fi. A robot on another computer can't be seen with that setting: give your robot and your laptop the same `ROS_DOMAIN_ID` (a number from 1 to 101 that no other team uses) instead.

## 4. Record

Recording needs ROS 2's Python packages. On a Mac or Windows, run the record commands inside Docker as shown in [docker/README.md](docker/README.md). On Ubuntu, use the `.venv-ros` venv from [docs/ARM.md](docs/ARM.md#recording-from-ros-2-on-ubuntu). `setup.sh`, `armkit check` and `armkit verify` work from your normal `.venv`.

Test run, nothing sent to peaq (free, unlimited):

```bash
KIT_JOINT_SOURCE=ros2 KIT_LOG_DIR=./dev-log armkit record
```

Record the run you want judged:

```bash
KIT_JOINT_SOURCE=ros2 armkit record --live
```

Each move becomes one event under your peaqID, and its full data goes into `motion-log/`. Ctrl-C closes the move in progress and waits for the last events to land. If a move shows `receipt lost`, run `armkit resubmit`: it checks peaq first, skips moves that already landed, and stops if a transaction is still in flight (run it again a minute later), so no move is recorded twice.

Three rules, because every move the kit puts on record under your peaqID has to be in the log you hand in:

- Test runs go in their own folder (`KIT_LOG_DIR=./dev-log`). Only the run you want judged uses `--live`.
- Never delete `motion-log/`.
- Never record `--live` from two folders or two laptops with the same identity.

You can stop and start `armkit record --live` as often as you like: every session adds to the same `motion-log/`.

## 5. Verify and hand in

```bash
armkit verify
```

`RESULT: all segments verified` means your log matches peaq exactly. Events you add yourself in another format (an extension) are listed as `[info]` and don't fail the run. Hand the judges your machine ID, your wallet address, `motion-log/` as a zip, and your repo. They run the same command with the official kit.

## How you're judged

| Criterion | Weight | What the judges look at |
|---|---|---|
| Verified run | pass/fail | `armkit verify` passes on the log you hand in. Required to score at all. |
| Recording quality | 30% | One event per real move (not per sample, not per hour), a complete log, honest summaries. |
| Build on top | 40% | What you built on a robot that can prove what it did. Usefulness to someone who relies on the record counts more than novelty. |
| Identity and setup | 10% | Your own peaqID, set up correctly, written only by your team's wallet. |
| Reproducibility | 20% | A repo and runbook another team could follow to repeat your run and your build. |

Hard fail: a log that fails verification (edited, incomplete, or not on peaq); events under an identity your team doesn't control; motion presented as coming from a robot or simulator it didn't come from. The synthetic arm and CSV replay are for building only: the run you hand in comes from the emulator, a ROS 2 simulator or a real robot, and every segment records its source (`ros2:<topic>`, `csv:<file>` or `synthetic`).

A passing verify proves your log wasn't changed after it went on record. Where the motion came from is yours to show in your demo.

## Build on it

The kit is the starting point. Ideas that fit the week:

- Sign each segment with the robot's own key and teach the verifier to check the signature ([docs/APP.md](docs/APP.md))
- Smarter segmentation: per joint, per tool path, per task
- A second robot with its own identity, and events that reference each other
- Replay a logged run into the emulator and check it reproduces the motion within a tolerance you define
- The dashboard a fleet operator, insurer or customer would actually use

## Commands

| Command | What it does |
|---|---|
| `armkit check` | Shows your configuration, wallet balance and whether peaq is reachable |
| `armkit record` | Writes moves to the local log only; add `--live` to put each one on peaq |
| `armkit resubmit` | Retries moves that failed or lost their receipt, without recording any move twice |
| `armkit verify` | Checks your motion log against peaq |
| `armkit status` | Shows your latest events on peaq (`--machine-id` for another identity, such as your arm-slot one; `--arm` for the real A0509's own identity) |

## What's in the repo

| Path | What |
|---|---|
| `peaqos_arm_kit/` | The kit: joint-state sources (`ros2`, `csv`, `synthetic`), segmenter, event format, motion log, submitter, verifier, `armkit` CLI |
| `scripts/setup.sh` | Creates your team wallet and peaqID (step 2) |
| `scripts/fund_teams.py` | Mentor tool for funding team wallets |
| `docker/` | Container for ROS 2 Humble and the Doosan emulator, including Apple Silicon Macs |
| `docs/ARM.md` | Running the Doosan emulator or your own ROS 2 robot |
| `docs/APP.md` | The event format and exactly what verification proves |
| `docs/PEAQOS.md` | The peaqOS calls behind the kit, for when you want to go lower |
| `docs/TROUBLESHOOTING.md` | Common errors and fixes |

Stuck? Check [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md), or find a peaq mentor.

Built with `peaq-os-sdk` 0.11.2 and `peaq-os-cli` 0.0.19 on peaq mainnet (chain 3338). Docs: [docs.peaq.xyz](https://docs.peaq.xyz). License: Apache 2.0.
