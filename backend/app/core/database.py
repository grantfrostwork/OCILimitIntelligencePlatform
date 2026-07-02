from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_scan_run_columns()


def _ensure_scan_run_columns() -> None:
    inspector = inspect(engine)
    if "scan_runs" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("scan_runs")}
    additions = {
        "current_stage": "VARCHAR(64) NOT NULL DEFAULT 'queued'",
        "current_service": "VARCHAR(128)",
        "services_scanned": "INTEGER NOT NULL DEFAULT 0",
        "total_limits_discovered": "INTEGER NOT NULL DEFAULT 0",
        "trigger": "VARCHAR(32) NOT NULL DEFAULT 'scheduled'",
        "batch_id": "VARCHAR(36)",
        "attempt": "INTEGER NOT NULL DEFAULT 1",
        "max_attempts": "INTEGER NOT NULL DEFAULT 1",
        "api_request_count": "INTEGER NOT NULL DEFAULT 0",
        "api_retry_count": "INTEGER NOT NULL DEFAULT 0",
        "api_throttle_count": "INTEGER NOT NULL DEFAULT 0",
        "api_concurrency_wait_seconds": "FLOAT NOT NULL DEFAULT 0",
        "api_retry_sleep_seconds": "FLOAT NOT NULL DEFAULT 0",
        "global_limits_skipped": "INTEGER NOT NULL DEFAULT 0",
    }

    with engine.begin() as connection:
        for column, definition in additions.items():
            if column not in existing:
                connection.execute(text(f"ALTER TABLE scan_runs ADD COLUMN {column} {definition}"))
