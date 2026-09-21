"""Small SQLite gateway for the local import vertical slice."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        from alembic.config import Config

        from alembic import command

        project_root = Path(__file__).resolve().parents[3]
        config = Config(str(project_root / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{self.path.resolve().as_posix()}")
        command.upgrade(config, "head")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def latest_committed_batch_id(self) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM import_batches WHERE status IN ('committed', 'needs_review') "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            return str(row["id"]) if row else None

    def source_file_by_hash(self, sha256: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM source_files WHERE sha256 = ?", (sha256,)
            ).fetchone()

    def open_reconciliation_cases(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM reconciliation_cases WHERE status = 'open' ORDER BY created_at"
            ).fetchall()

    def count(self, table: str) -> int:
        if table not in {
            "transactions",
            "source_records",
            "reconciliation_cases",
            "import_batches",
        }:
            raise ValueError(table)
        with self.connect() as connection:
            row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
            return int(row["count"])
