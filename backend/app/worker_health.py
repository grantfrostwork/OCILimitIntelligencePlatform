from __future__ import annotations

import os
import time
from pathlib import Path


DEFAULT_HEARTBEAT_PATH = Path("/tmp/oci-lip-worker-heartbeat")
DEFAULT_MAX_AGE_SECONDS = 120.0


def heartbeat_path() -> Path:
    return Path(os.getenv("LIP_WORKER_HEARTBEAT_PATH", str(DEFAULT_HEARTBEAT_PATH)))


def write_heartbeat(path: Path | None = None, *, timestamp: float | None = None) -> None:
    target = path or heartbeat_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(str(timestamp if timestamp is not None else time.time()), encoding="ascii")
    temporary.replace(target)


def heartbeat_is_fresh(
    path: Path | None = None,
    *,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    timestamp: float | None = None,
) -> bool:
    target = path or heartbeat_path()
    try:
        last_heartbeat = float(target.read_text(encoding="ascii"))
    except (OSError, ValueError):
        return False
    now = timestamp if timestamp is not None else time.time()
    return 0 <= now - last_heartbeat <= max_age_seconds


def main() -> None:
    raise SystemExit(0 if heartbeat_is_fresh() else 1)


if __name__ == "__main__":
    main()
