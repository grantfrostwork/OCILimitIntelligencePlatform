from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.api.health import readyz
from app.worker_health import heartbeat_is_fresh, write_heartbeat


class DatabaseStub:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def execute(self, _statement) -> None:
        if self.error:
            raise self.error


def test_readyz_checks_database() -> None:
    assert readyz(DatabaseStub()) == {"status": "ready"}


def test_readyz_returns_service_unavailable_when_database_fails() -> None:
    with pytest.raises(HTTPException) as exc_info:
        readyz(DatabaseStub(SQLAlchemyError("offline")))

    assert exc_info.value.status_code == 503


def test_worker_heartbeat_detects_fresh_and_stale_files(tmp_path: Path) -> None:
    path = tmp_path / "worker-heartbeat"
    write_heartbeat(path, timestamp=100.0)

    assert heartbeat_is_fresh(path, max_age_seconds=30, timestamp=125.0)
    assert not heartbeat_is_fresh(path, max_age_seconds=30, timestamp=131.0)
    assert not heartbeat_is_fresh(tmp_path / "missing", timestamp=100.0)
