"""Read-only integrity and provenance audit for the local financial store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from family_finance.config import Settings
from family_finance.models import AuditCheck, AuditReport
from family_finance.persistence.db import Database
from family_finance.persistence.models import (
    ImportBatchRow,
    ReconciliationCaseRow,
    SourceFileRow,
    SourceRecordRow,
    TransactionRow,
    TransactionSourceRow,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class AuditService:
    def __init__(self, database: Database | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_environment()
        self.database = database
        if self.database is None and self.settings.database_path.is_file():
            self.database = Database(self.settings.database_path, read_only=True)

    def run(self) -> AuditReport:
        if self.database is None:
            return AuditReport(
                passed=False,
                checks=[AuditCheck(name="database", passed=False, issue_codes=["DATABASE_MISSING"])],
            )
        checks = [
            self._safe_check(self._integrity_check),
            self._safe_check(self._foreign_keys_check),
            self._safe_check(self._schema_check),
            self._safe_check(self._archive_hash_check),
            self._safe_check(self._source_lifecycle_check),
            self._safe_check(self._transaction_provenance_check),
            self._safe_check(self._batch_count_check),
        ]
        return AuditReport(passed=all(check.passed for check in checks), checks=checks)

    def _safe_check(self, check) -> AuditCheck:
        try:
            return check()
        except (OSError, sqlite3.DatabaseError, SQLAlchemyError):
            return AuditCheck(name="database", passed=False, issue_codes=["DATABASE_UNREADABLE"])

    def _check(self, name: str, passed: bool, *codes: str) -> AuditCheck:
        return AuditCheck(name=name, passed=passed, issue_codes=[] if passed else list(codes))

    def _integrity_check(self) -> AuditCheck:
        with self.database.engine.connect() as connection:
            result = str(connection.exec_driver_sql("PRAGMA integrity_check").scalar_one())
        return self._check("sqlite_integrity", result == "ok", "SQLITE_INTEGRITY_ERROR")

    def _foreign_keys_check(self) -> AuditCheck:
        with self.database.engine.connect() as connection:
            rows = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
        return self._check("foreign_keys", not rows, "FOREIGN_KEY_ERROR")

    def _schema_check(self) -> AuditCheck:
        project_root = Path(__file__).resolve().parents[2]
        config = Config(str(project_root / "alembic.ini"))
        head = ScriptDirectory.from_config(config).get_current_head()
        with self.database.engine.connect() as connection:
            current = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()
        return self._check("alembic_head", str(current) == str(head), "SCHEMA_REVISION_MISMATCH")

    def _archive_hash_check(self) -> AuditCheck:
        missing = False
        mismatch = False
        with self.database.session() as session:
            rows = session.execute(select(SourceFileRow)).scalars().all()
        for row in rows:
            path = Path(row.archived_path)
            if not path.is_absolute():
                path = self.settings.data_root / path
            if not path.exists():
                relocated = sorted(self.settings.archive_root.glob(f"{row.sha256}.*"))
                if relocated:
                    path = relocated[0]
            if not path.exists():
                missing = True
            elif _sha256(path) != row.sha256:
                mismatch = True
        codes = []
        if missing:
            codes.append("ARCHIVE_MISSING")
        if mismatch:
            codes.append("ARCHIVE_HASH_MISMATCH")
        return self._check("archive_hashes", not codes, *codes)

    def _source_lifecycle_check(self) -> AuditCheck:
        codes: list[str] = []
        with self.database.session() as session:
            sources = session.execute(select(SourceRecordRow)).scalars().all()
            for source in sources:
                link_count = int(
                    session.execute(
                        select(func.count())
                        .select_from(TransactionSourceRow)
                        .where(TransactionSourceRow.source_record_id == source.id)
                    ).scalar_one()
                )
                open_case_count = int(
                    session.execute(
                        select(func.count())
                        .select_from(ReconciliationCaseRow)
                        .where(
                            ReconciliationCaseRow.source_record_id == source.id,
                            ReconciliationCaseRow.status == "open",
                        )
                    ).scalar_one()
                )
                case_statuses = [row[0] for row in session.execute(
                    select(ReconciliationCaseRow.status).where(
                        ReconciliationCaseRow.source_record_id == source.id
                    )
                ).all()]
                if source.validation_state == "accepted" and link_count != 1:
                    codes.append("ACCEPTED_SOURCE_LINK_MISSING_OR_DUPLICATE")
                elif source.validation_state == "accepted" and open_case_count:
                    codes.append("ACCEPTED_SOURCE_HAS_OPEN_CASE")
                elif source.validation_state == "unresolved" and open_case_count != 1:
                    codes.append("UNRESOLVED_SOURCE_CASE_MISSING")
                elif source.validation_state == "dismissed" and (
                    link_count or case_statuses != ["dismissed"]
                ):
                    codes.append("DISMISSED_SOURCE_LIFECYCLE_INVALID")
                elif source.validation_state not in {"accepted", "unresolved", "dismissed"}:
                    codes.append("UNKNOWN_SOURCE_LIFECYCLE_STATE")
        return self._check("source_row_lifecycle", not codes, *sorted(set(codes)))

    def _transaction_provenance_check(self) -> AuditCheck:
        with self.database.session() as session:
            transactions = session.execute(select(TransactionRow.id)).all()
            missing = [
                transaction_id
                for (transaction_id,) in transactions
                if int(
                    session.execute(
                        select(func.count())
                        .select_from(TransactionSourceRow)
                        .where(TransactionSourceRow.transaction_id == transaction_id)
                    ).scalar_one()
                )
                < 1
            ]
            non_accepted_links = session.execute(
                select(TransactionSourceRow.transaction_id)
                .join(SourceRecordRow, SourceRecordRow.id == TransactionSourceRow.source_record_id)
                .where(SourceRecordRow.validation_state != "accepted")
            ).all()
        if non_accepted_links:
            missing.extend(int(row[0]) for row in non_accepted_links)
        return self._check("transaction_provenance", not missing, "TRANSACTION_PROVENANCE_MISSING")

    def _batch_count_check(self) -> AuditCheck:
        codes: list[str] = []
        with self.database.session() as session:
            batches = session.execute(select(ImportBatchRow)).scalars().all()
            for batch in batches:
                if batch.status == "duplicate":
                    continue
                expected = _statistics_total(batch.statistics_json)
                actual = int(
                    session.execute(
                        select(func.count())
                        .select_from(SourceRecordRow)
                        .where(SourceRecordRow.import_batch_id == batch.id)
                    ).scalar_one()
                )
                if expected is not None and expected != actual:
                    codes.append("BATCH_SOURCE_COUNT_MISMATCH")
        return self._check("batch_count_reconciliation", not codes, *sorted(set(codes)))


def _statistics_total(value: str) -> int | None:
    try:
        data: dict[str, Any] = json.loads(value)
        return int(data["total_records"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


__all__ = ["AuditService"]
