import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_fresh_database_migrates_to_head(tmp_path: Path) -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "migration-test.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database_path}"

    command = [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"]
    subprocess.run(command, cwd=backend_dir, env=env, check=True, capture_output=True, text=True)
    subprocess.run(command, cwd=backend_dir, env=env, check=True, capture_output=True, text=True)

    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert revision == ("0003_scan_schedule_metrics",)
    assert {"scan_runs", "monitored_regions", "scan_requests", "scan_schedule"} <= tables
