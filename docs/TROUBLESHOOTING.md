# Troubleshooting

## Install and setup

| You see | Why | Fix |
|---|---|---|
| `python3 --version` says 3.9, or `pip install -e .` fails with a setuptools error | macOS's built-in Python is 3.9; the kit needs 3.10+ | `brew install python@3.12` then `python3.12 -m venv .venv`, or `uv venv --seed -p 3.12 .venv`; then `source .venv/bin/activate` |
| `peaqos init` fails with `CERTIFICATE_VERIFY_FAILED` | python.org Python 3.13 on macOS ships without root certificates | run `/Applications/Python 3.13/Install Certificates.command`, or use Homebrew or uv Python |
| `peaqos` says `No module named 'peaq_os_cli'` | an old global `peaqos` is shadowing the one in your venv | `rehash` (zsh) or call `.venv/bin/peaqos` |
| `activate` exits 2 with `INSUFFICIENT_PEAQ` | the wallet isn't funded yet | ask a mentor for 1.5 PEAQ, then run `scripts/setup.sh` again: it keeps your key and continues |
| `activate` asks for a 2FA code | it was run without `--skip-funding` on an unfunded wallet | Ctrl-C, get funded, run `scripts/setup.sh` again |
| `KIT_MACHINE_ID is not set` | setup didn't finish, or you're not in the folder with `.env` | run `armkit` from the kit folder; if needed run `scripts/setup.sh` again |
| Windows | `setup.sh` is bash | use WSL2 Ubuntu 22.04 and clone the kit inside WSL (`~/`), not under `/mnt/c` |

## Network and ROS 2

| You see | Why | Fix |
|---|---|---|
| `armkit check` says `chain: unreachable` | wrong `PEAQOS_RPC_URL`, or the endpoint is rate-limited | use the RPC URL from the mentors' card, not a public one; if the whole room is affected, tell a mentor |
| `rclpy / sensor_msgs not importable` | your venv can't see ROS 2's Python packages | `deactivate`, source ROS, then `/usr/bin/python3 -m venv --system-site-packages .venv-ros` (see [ARM.md](ARM.md)); on a Mac use the [Docker setup](../docker/README.md) |
| other teams' `/dsr01/joint_states` show up | everyone on one Wi-Fi shares ROS 2 domain 0 | `export ROS_LOCALHOST_ONLY=1` in every terminal |
| no segments while the arm moves | the moves are below the velocity threshold | check `ros2 topic hz /dsr01/joint_states`, then lower `KIT_VELOCITY_THRESHOLD` |
| RViz: `Couldn't open X display` | there is no display (headless or container) | harmless, the driver keeps running |

## Recording

| You see | Why | Fix |
|---|---|---|
| `receipt lost … run armkit resubmit` | the transaction was sent but the RPC timed out before it confirmed | `armkit resubmit`: it checks peaq first and only sends what is really missing; if a transaction is still in flight it stops, so run it again a minute later |
| `NotOwnerOrController` or `NotAuthorizedSubmitter` | the wallet in `.env` isn't the one that created your peaqID | use the `.env` from `setup.sh`; `.venv/bin/peaqos whoami` shows the active wallet |
| `RateLimitExceeded` | too many events in a short time | segments are too short: raise `KIT_MIN_SEGMENT_SECONDS` or `KIT_SETTLE_SECONDS` |
| `armkit check` warns the balance is below 0.2 PEAQ | each event costs about 0.04 PEAQ | ask a mentor for a top-up before recording `--live` |

## Verify

| You see | Why | Fix |
|---|---|---|
| segments `not on chain` with `status: dry-run` | test runs (no `--live`) are in `motion-log/` | keep test runs in their own folder (`KIT_LOG_DIR=./dev-log`) |
| `on-chain motion events for this machine with no segment in this log` | a move under your peaqID is missing from the log | hand in the complete log; if test events are on record under this identity, start a fresh identity (new folder, new `TEAM`, `setup.sh`) |
| `hash BAD` | a segment file was edited after it was recorded | don't edit `motion-log/` |
| `doc BAD` | wrong folder, or quick-start segments (machine ID 1) in your log | verify the right `motion-log/`; keep the quick start in its own folder |
| your MCR rating says `Provisioned` | a rating needs history over a longer time | expected this week, not part of the scoring |
