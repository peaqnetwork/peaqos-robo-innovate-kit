# Troubleshooting

## Install and setup

| You see | Why | Fix |
|---|---|---|
| `python3 --version` says 3.9, or `pip install -e .` fails with a setuptools error | macOS's built-in Python is 3.9; the kit needs 3.10+ | `brew install python@3.12` then `python3.12 -m venv .venv`, or `uv venv --seed -p 3.12 .venv`; then `source .venv/bin/activate` |
| `peaqos` says `No module named 'peaq_os_cli'` | an old global `peaqos` is shadowing the one in your venv | `rehash` (zsh) or call `.venv/bin/peaqos` |
| `ModuleNotFoundError: No module named 'eth_account'` (or `'dotenv'`) from `setup.sh` | the venv isn't active | `source .venv/bin/activate`, then the same `setup.sh` line again |
| `armkit check` shows machine id 1, `demo-log`, or signer `no` | quick-start settings are still set in this terminal | `unset KIT_ENV_FILE KIT_MACHINE_ID KIT_LOG_DIR`, or open a new terminal |
| `TEAM must be 1-32 characters` | the team name has capitals, spaces or other characters | use only a-z, 0-9 and `-` |
| `INSUFFICIENT_PEAQ` at activation | the wallet isn't funded yet | ask a mentor to fund the address in the team sheet, then run the same `setup.sh` line again in the same folder: it keeps your key, shows the wallet again and waits for Enter |
| `activation failed` with another error above it | not a funding problem | show a mentor the error; your key in `.env` is kept |
| `armkit check` shows the wrong `rpc` | `setup.sh` keeps the RPC URL from its first run | edit the `PEAQOS_RPC_URL=` line in `.env` to the URL on the card |
| `KIT_MACHINE_ID is not set` | you're not in the folder where you ran `setup.sh`, or it didn't finish | run `armkit` from that folder; if `setup.sh` stopped early, run it again there |
| Windows | ROS 2 and the emulator need Linux | use WSL2 Ubuntu 22.04, clone the kit inside WSL (`~/`, not `/mnt/c`), then follow the [Docker setup](../docker/README.md) |

## Network and ROS 2

| You see | Why | Fix |
|---|---|---|
| `armkit check` says `chain: unreachable` | wrong `PEAQOS_RPC_URL`, or the endpoint is down | use the RPC URL from the printed card, not a public one; if the whole room is affected, tell a mentor |
| `rclpy / sensor_msgs not importable` | your venv can't see ROS 2's Python packages | `deactivate`, source ROS, then `/usr/bin/python3 -m venv --system-site-packages .venv-ros` (see [ARM.md](ARM.md)); on a Mac use the [Docker setup](../docker/README.md) |
| other teams' `/dsr01/joint_states` show up | everyone on one Wi-Fi shares ROS 2 domain 0 | `export ROS_LOCALHOST_ONLY=1` in every terminal |
| no segments while the arm moves | the moves are below the velocity threshold | check `ros2 topic hz /dsr01/joint_states`, then lower `KIT_VELOCITY_THRESHOLD` |
| RViz: `Couldn't open X display` | there is no display (headless or container) | harmless, the driver keeps running |

## Recording

| You see | Why | Fix |
|---|---|---|
| `receipt lost … run armkit resubmit` | the transaction was sent but the RPC timed out before it confirmed | `armkit resubmit`: it checks peaq first and only sends what is really missing; if a transaction is still in flight it stops, so run it again a minute later |
| `NotOwnerOrController` or `NotAuthorizedSubmitter` | the wallet in `.env` isn't the one that created your peaqID | run `armkit` from the folder where you ran `setup.sh`; `.venv/bin/peaqos whoami` shows the active wallet |
| an RPC error mentioning `rate` or `429` | the endpoint is rate-limited | the kit retries by itself; if moves still fail, run `armkit resubmit` later and tell a mentor |
| `armkit check` warns the balance is below 0.2 PEAQ | each event costs about 0.04 PEAQ | ask a mentor for a top-up before recording `--live` |

## Verify

| You see | Why | Fix |
|---|---|---|
| segments `not on chain` with `status: dry-run` | test runs (no `--live`) are in `motion-log/` | keep test runs in their own folder (`KIT_LOG_DIR=./dev-log`) |
| `on-chain motion events for this machine with no segment in this log` | a move under your peaqID is missing from the log | hand in the complete log. If `--live` test events are under this identity, they can't be removed: a mentor helps you make a new identity (`TEAM=<team>-2` in a fresh kit folder) and you record a new hand-in run under it |
| `hash BAD` | a segment file was edited after it was recorded | don't edit `motion-log/` |
| `doc BAD` | wrong folder, or quick-start segments (machine ID 1) in your log | verify the right `motion-log/`; keep the quick start in its own folder |
| your MCR rating says `Provisioned` | a rating needs history over a longer time | expected this week, not part of the scoring |
