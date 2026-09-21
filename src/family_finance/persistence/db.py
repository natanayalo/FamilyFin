"""SQLAlchemy 2.0 database gateway for the local application."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class _CompatResult:
    """Mapping result adapter retained for the Phase 1 service call sites."""

    def __init__(self, result) -> None:
        self._result = result
        self.lastrowid = getattr(result, "lastrowid", None)

    def fetchone(self):
        return self._result.mappings().first()

    def fetchall(self):
        return self._result.mappings().all()


class ConnectionAdapter:
    """Compatibility facade over a SQLAlchemy connection.

    It accepts the existing positional parameter style, translates it to
    SQLAlchemy named binds, and returns mapping results for the Phase 1 import
    call sites. New Phase 2 persistence uses sessions and declarative rows.
    """

    def __init__(self, connection: Connection, *, close_on_exit: bool = True) -> None:
        self._connection = connection
        self._close_on_exit = close_on_exit

    def execute(self, statement: Any, parameters: Any = ()) -> _CompatResult:
        if isinstance(statement, str):
            if isinstance(parameters, dict):
                bind_parameters = parameters
            else:
                values = tuple(parameters or ())
                bind_parameters = {f"p{index}": value for index, value in enumerate(values)}
                for index in range(len(values)):
                    statement = statement.replace("?", f":p{index}", 1)
            result = self._connection.execute(text(statement), bind_parameters)
        else:
            result = self._connection.execute(statement, parameters)
        return _CompatResult(result)

    def exec_driver_sql(self, statement: str, parameters: Any = ()) -> _CompatResult:
        result = self._connection.exec_driver_sql(statement, parameters)
        return _CompatResult(result)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        if self._close_on_exit:
            self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


class Database:
    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        if read_only:
            if not self.path.is_file():
                raise FileNotFoundError(self.path)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = self._create_engine()
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
            autoflush=False,
        )
        if not read_only:
            self.initialize()

    def _create_engine(self) -> Engine:
        if self.read_only:
            # ``mode=ro`` preserves SQLite's WAL visibility.  ``immutable=1``
            # would incorrectly ignore committed frames still held in the WAL.
            url = f"sqlite:///file:{self.path.resolve().as_posix()}?mode=ro&uri=true"
        else:
            url = f"sqlite:///{self.path.resolve().as_posix()}"
        engine = create_engine(
            url,
            future=True,
            connect_args={"check_same_thread": False, "isolation_level": None},
        )

        @event.listens_for(engine, "connect")
        def _configure_sqlite(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            if self.read_only:
                cursor.execute("PRAGMA query_only = ON")
            else:
                cursor.execute("PRAGMA journal_mode = WAL")
            cursor.close()

        return engine

    def initialize(self) -> None:
        from alembic.config import Config

        from alembic import command

        project_root = Path(__file__).resolve().parents[3]
        config = Config(str(project_root / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{self.path.resolve().as_posix()}")
        command.upgrade(config, "head")

    def connect(self) -> ConnectionAdapter:
        return ConnectionAdapter(self.engine.connect())

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def write_session(self) -> Iterator[Session]:
        """Yield a SQLAlchemy session inside an explicit immediate write."""

        raw_connection = self.engine.connect()
        raw_connection.exec_driver_sql("BEGIN IMMEDIATE")
        session = Session(bind=raw_connection, expire_on_commit=False, autoflush=False)
        try:
            yield session
            session.commit()
            raw_connection.commit()
        except Exception:
            session.rollback()
            raw_connection.rollback()
            raise
        finally:
            session.close()
            raw_connection.close()

    @contextmanager
    def transaction(self) -> Iterator[ConnectionAdapter]:
        """Open an explicit SQLite ``BEGIN IMMEDIATE`` write transaction."""

        raw_connection = self.engine.connect()
        connection = ConnectionAdapter(raw_connection, close_on_exit=False)
        try:
            raw_connection.exec_driver_sql("BEGIN IMMEDIATE")
            yield connection
            raw_connection.commit()
        except Exception:
            raw_connection.rollback()
            raise
        finally:
            raw_connection.close()

    def latest_committed_batch_id(self) -> str | None:
        from family_finance.persistence.models import ImportBatchRow

        with self.session() as session:
            row = session.execute(
                select(ImportBatchRow.id)
                .where(ImportBatchRow.status.in_(("committed", "needs_review")))
                .order_by(ImportBatchRow.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        return str(row) if row else None

    def source_file_by_hash(self, sha256: str):
        from family_finance.persistence.models import SourceFileRow

        with self.session() as session:
            row = session.execute(
                select(SourceFileRow).where(SourceFileRow.sha256 == sha256)
            ).scalar_one_or_none()
        return _row_mapping(row) if row else None

    def open_reconciliation_cases(self):
        from family_finance.persistence.models import ReconciliationCaseRow

        with self.session() as session:
            rows = session.execute(
                select(ReconciliationCaseRow)
                .where(ReconciliationCaseRow.status == "open")
                .order_by(ReconciliationCaseRow.created_at)
            ).scalars().all()
        return [_row_mapping(row) for row in rows]

    def count(self, table: str) -> int:
        if table not in {
            "transactions",
            "source_records",
            "reconciliation_cases",
            "import_batches",
            "classification_rules",
            "analysis_overrides",
        }:
            raise ValueError(table)
        from family_finance.persistence.models import (
            AnalysisOverrideRow,
            ClassificationRuleRow,
            ImportBatchRow,
            ReconciliationCaseRow,
            SourceRecordRow,
            TransactionRow,
        )

        models = {
            "transactions": TransactionRow,
            "source_records": SourceRecordRow,
            "reconciliation_cases": ReconciliationCaseRow,
            "import_batches": ImportBatchRow,
            "classification_rules": ClassificationRuleRow,
            "analysis_overrides": AnalysisOverrideRow,
        }
        with self.session() as session:
            return int(session.execute(select(func.count()).select_from(models[table])).scalar_one())


def _row_mapping(row: Any) -> dict[str, Any]:
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


__all__ = ["ConnectionAdapter", "Database", "json_dumps", "text", "utc_now"]
