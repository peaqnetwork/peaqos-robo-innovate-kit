"""Kit settings, read from the environment after loading ``.env``.

``peaqos init`` writes the peaqOS variables; the ``KIT_*`` ones are ours.
``load_dotenv()`` runs here because ``PeaqosClient.from_env()`` does not load
``.env`` itself (SDK 0.11.2).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

PEAQ_MAINNET_CHAIN_ID = 3338
EVENT_TYPE_ACTIVITY = 1
ENV_FILE_VAR = "KIT_ENV_FILE"  # override which .env to load (the quick start uses .env.example)


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _trust_level(raw: str) -> int:
    """The kit submits self-reported events. Level 1 needs a source transaction hash the
    kit cannot supply, so every event would be rejected; refuse it up front."""
    level = int(raw)
    if level != 0:
        raise SystemExit(f"KIT_TRUST_LEVEL={level}: the kit submits self-reported events (0). If you built signing and can show it, change _trust_level in peaqos_arm_kit/config.py and explain it in your runbook.")
    return level


@dataclass(frozen=True)
class KitSettings:
    machine_id: int | None
    arm_machine_id: int | None  # the real A0509's peaqID on site, for `armkit status --arm`
    joint_source: str
    csv_path: Path
    ros2_topic: str
    log_dir: Path
    velocity_threshold: float
    min_segment_seconds: float
    settle_seconds: float
    max_segment_seconds: float
    trust_level: int
    rpc_url: str
    event_registry: str
    has_signer: bool

    @classmethod
    def load(cls, dotenv_path: str | os.PathLike[str] | None = None) -> "KitSettings":
        # find_dotenv(usecwd=True): look in the directory the team runs armkit from,
        # not where the package is installed. KIT_ENV_FILE / --env override it.
        chosen = dotenv_path or os.environ.get(ENV_FILE_VAR) or find_dotenv(usecwd=True)
        load_dotenv(chosen, override=False)
        raw_id = _env("KIT_MACHINE_ID")
        raw_arm = _env("KIT_ARM_MACHINE_ID")
        for name, raw in (("KIT_MACHINE_ID", raw_id), ("KIT_ARM_MACHINE_ID", raw_arm)):
            if raw and not raw.isdigit():
                raise SystemExit(
                    f"{name}={raw!r} in .env is not a machine ID. It must be the decimal number "
                    "printed as \"machine_id\" by `peaqos activate --json` (about 77 digits)."
                )
        return cls(
            machine_id=int(raw_id) if raw_id else None,
            arm_machine_id=int(raw_arm) if raw_arm else None,
            joint_source=_env("KIT_JOINT_SOURCE", "synthetic"),
            csv_path=Path(_env("KIT_CSV_PATH", "data/sample_joint_log.csv")),
            ros2_topic=_env("KIT_ROS2_TOPIC", "/dsr01/joint_states"),
            log_dir=Path(_env("KIT_LOG_DIR", "./motion-log")),
            velocity_threshold=float(_env("KIT_VELOCITY_THRESHOLD", "0.02")),
            min_segment_seconds=float(_env("KIT_MIN_SEGMENT_SECONDS", "0.3")),
            settle_seconds=float(_env("KIT_SETTLE_SECONDS", "0.4")),
            max_segment_seconds=float(_env("KIT_MAX_SEGMENT_SECONDS", "20")),
            trust_level=_trust_level(_env("KIT_TRUST_LEVEL", "0")),
            rpc_url=_env("PEAQOS_RPC_URL"),
            event_registry=_env("EVENT_REGISTRY_ADDRESS"),
            has_signer=bool(_env("PEAQOS_PRIVATE_KEY")),
        )

    def require_machine_id(self) -> int:
        if self.machine_id is None:
            raise SystemExit(
                "KIT_MACHINE_ID is not set. Run scripts/setup.sh (or `peaqos activate --json`) "
                "and copy the machine_id into .env."
            )
        return self.machine_id
