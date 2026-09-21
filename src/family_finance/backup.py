"""Verified online backups for the SQLite database and immutable imports."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory

from family_finance.config import Settings
from family_finance.forecasting import assumption_hash
from family_finance.models import (
    AuditCheck,
    BackupManifest,
    BackupVerification,
    ForecastRevisionSnapshot,
)
from family_finance.persistence.db import Database
from family_finance.persistence.models import PlanningSourceFileRow, SourceFileRow


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _schema_head() -> str:
    project_root = Path(__file__).resolve().parents[2]
    return str(ScriptDirectory.from_config(Config(str(project_root / "alembic.ini"))).get_current_head())


class BackupService:
    def __init__(self, database: Database | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_environment()
        self.database = database

    @property
    def database_path(self) -> Path:
        return self.database.path if self.database is not None else self.settings.database_path

    def _source_database(self) -> Database:
        if self.database is None:
            self.database = Database(self.settings.database_path)
        return self.database

    def create(self, destination: str | Path) -> BackupManifest:
        database = self._source_database()
        target = Path(destination).expanduser()
        if target.exists():
            raise FileExistsError("Backup destination already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
        temporary.mkdir()
        try:
            self._online_backup(temporary / database.path.name, database)
            self._copy_archives(temporary, database)
            manifest = self._manifest(temporary)
            (temporary / "manifest.json").write_text(
                manifest.model_dump_json(indent=2), encoding="utf-8"
            )
            verification = self.verify(temporary)
            if not verification.passed:
                raise RuntimeError("Backup verification failed: " + ", ".join(
                    code for check in verification.checks for code in check.issue_codes
                ))
            temporary.replace(target)
            return manifest
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    def verify(self, backup_directory: str | Path) -> BackupVerification:
        root = Path(backup_directory).expanduser()
        checks: list[AuditCheck] = []
        manifest_path = root / "manifest.json"
        try:
            manifest = BackupManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return BackupVerification(
                passed=False,
                checks=[AuditCheck(name="manifest", passed=False, issue_codes=["MANIFEST_INVALID"])],
            )

        missing_or_tampered = False
        manifest_paths = {str(item.get("relative_path", "")) for item in manifest.files}
        actual_paths = {
            item.relative_to(root).as_posix()
            for item in root.rglob("*")
            if item.is_file()
            and item.name != "manifest.json"
            and not item.name.endswith(("-wal", "-shm"))
        }
        if manifest_paths != actual_paths:
            missing_or_tampered = True
        for item in manifest.files:
            try:
                relative_path = Path(str(item["relative_path"]))
                path = (root / relative_path).resolve()
                path.relative_to(root.resolve())
                expected_size = int(item["size"])
                expected_hash = str(item["sha256"])
            except (KeyError, OSError, TypeError, ValueError):
                missing_or_tampered = True
                continue
            if not path.is_file() or path.stat().st_size != expected_size:
                missing_or_tampered = True
                continue
            if _hash_file(path) != expected_hash:
                missing_or_tampered = True
        checks.append(AuditCheck(
            name="manifest_hashes",
            passed=not missing_or_tampered,
            issue_codes=[] if not missing_or_tampered else ["BACKUP_HASH_MISMATCH"],
        ))
        revision_matches_manifest = manifest.schema_revision == _schema_head()
        checks.append(AuditCheck(
            name="manifest_schema_revision",
            passed=revision_matches_manifest,
            issue_codes=[] if revision_matches_manifest else ["SCHEMA_REVISION_MISMATCH"],
        ))

        database_path = root / self.database_path.name
        if not database_path.is_file():
            checks.append(AuditCheck(name="sqlite_integrity", passed=False, issue_codes=["BACKUP_DATABASE_MISSING"]))
            return BackupVerification(passed=False, checks=checks)

        database_checks, source_hashes = self._verify_database(database_path)
        checks.extend(database_checks)
        if not source_hashes and any(not check.passed for check in database_checks):
            return BackupVerification(passed=False, checks=checks)
        copied_hashes = {
            str(item["sha256"])
            for item in manifest.files
            if str(item["relative_path"]).startswith(("imports/", "planning-imports/"))
        }
        archive_ok = source_hashes.issubset(copied_hashes)
        checks.append(AuditCheck(
            name="archive_coverage",
            passed=archive_ok,
            issue_codes=[] if archive_ok else ["ARCHIVE_COVERAGE_MISSING"],
        ))
        return BackupVerification(passed=all(check.passed for check in checks), checks=checks)

    @staticmethod
    def _verify_database(database_path: Path) -> tuple[list[AuditCheck], set[str]]:
        uri = f"file:{database_path.resolve()}?mode=ro&immutable=1"
        try:
            with sqlite3.connect(uri, uri=True) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
                current_revision = connection.execute(
                    "SELECT version_num FROM alembic_version LIMIT 1"
                ).fetchone()
                checks = [
                    AuditCheck(
                        name="sqlite_integrity",
                        passed=integrity == "ok",
                        issue_codes=[] if integrity == "ok" else ["SQLITE_INTEGRITY_ERROR"],
                    ),
                    AuditCheck(
                        name="foreign_keys",
                        passed=not foreign_keys,
                        issue_codes=[] if not foreign_keys else ["FOREIGN_KEY_ERROR"],
                    ),
                ]
                head = _schema_head()
                revision_ok = bool(current_revision and str(current_revision[0]) == head)
                checks.append(
                    AuditCheck(
                        name="schema_revision",
                        passed=revision_ok,
                        issue_codes=[] if revision_ok else ["SCHEMA_REVISION_MISMATCH"],
                    )
                )
                checks.append(BackupService._verify_provenance(connection))
                checks.append(BackupService._verify_planning(connection))
                checks.append(BackupService._verify_forecasting(connection))
                source_hashes = {
                    str(row[0])
                    for row in connection.execute("SELECT sha256 FROM source_files").fetchall()
                }
                source_hashes.update(
                    str(row[0])
                    for row in connection.execute("SELECT sha256 FROM planning_source_files").fetchall()
                )
                return checks, source_hashes
        except (sqlite3.DatabaseError, OSError):
            return [
                AuditCheck(
                    name="sqlite_integrity",
                    passed=False,
                    issue_codes=["SQLITE_DATABASE_ERROR"],
                )
            ], set()

    def _online_backup(self, destination: Path, database: Database) -> None:
        with sqlite3.connect(str(database.path)) as source, sqlite3.connect(str(destination)) as target:
            source.backup(target)

    def _copy_archives(self, root: Path, database: Database) -> None:
        archive_target = root / "imports"
        archive_target.mkdir()
        planning_archive_target = root / "planning-imports"
        planning_archive_target.mkdir()
        database_path = root / database.path.name
        with database.session() as session:
            source_files = session.query(SourceFileRow).all()
            planning_source_files = session.query(PlanningSourceFileRow).all()
        with sqlite3.connect(str(database_path)) as connection:
            for source_file in source_files:
                source = Path(source_file.archived_path)
                if not source.is_absolute():
                    source = self.settings.data_root / source
                if not source.is_file():
                    relocated = sorted(self.settings.archive_root.glob(f"{source_file.sha256}.*"))
                    if relocated:
                        source = relocated[0]
                if not source.is_file():
                    raise FileNotFoundError("An archived import is missing")
                target = archive_target / f"{source_file.sha256}{source.suffix.lower() or '.bin'}"
                if not target.exists():
                    shutil.copy2(source, target)
                connection.execute(
                    "UPDATE source_files SET archived_path = ? WHERE sha256 = ?",
                    (f"imports/{target.name}", source_file.sha256),
                )
            for source_file in planning_source_files:
                source = Path(source_file.archived_path)
                if not source.is_absolute():
                    source = self.settings.data_root / source
                if not source.is_file():
                    relocated = sorted(self.settings.planning_archive_root.glob(f"{source_file.sha256}.*"))
                    if relocated:
                        source = relocated[0]
                if not source.is_file():
                    raise FileNotFoundError("A planning source archive is missing")
                target = planning_archive_target / f"{source_file.sha256}{source.suffix.lower() or '.csv'}"
                if not target.exists():
                    shutil.copy2(source, target)
                connection.execute(
                    "UPDATE planning_source_files SET archived_path = ? WHERE sha256 = ?",
                    (f"planning-imports/{target.name}", source_file.sha256),
                )
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode=DELETE")

    def _manifest(self, root: Path) -> BackupManifest:
        files: list[dict[str, Any]] = []
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix()
            if relative == "manifest.json" or path.name.endswith(("-wal", "-shm")):
                continue
            files.append({
                "relative_path": relative,
                "size": path.stat().st_size,
                "sha256": _hash_file(path),
            })
        return BackupManifest(
            created_at=datetime.now(UTC),
            schema_revision=_schema_head(),
            files=files,
        )

    @staticmethod
    def _verify_provenance(connection: sqlite3.Connection) -> AuditCheck:
        missing = connection.execute(
            """
            SELECT t.id FROM transactions t
            LEFT JOIN transaction_sources ts ON ts.transaction_id = t.id
            GROUP BY t.id HAVING COUNT(ts.source_record_id) < 1
            """
        ).fetchall()
        invalid_state_links = connection.execute(
            """
            SELECT ts.transaction_id
            FROM transaction_sources ts
            JOIN source_records sr ON sr.id = ts.source_record_id
            WHERE sr.validation_state != 'accepted'
            """
        ).fetchall()
        missing.extend(invalid_state_links)
        return AuditCheck(
            name="transaction_provenance",
            passed=not missing,
            issue_codes=[] if not missing else ["TRANSACTION_PROVENANCE_MISSING"],
        )

    @staticmethod
    def _verify_planning(connection: sqlite3.Connection) -> AuditCheck:
        invalid = []
        scenarios = connection.execute(
            "SELECT id, current_revision_number FROM planning_scenarios"
        ).fetchall()
        for scenario_id, current_revision in scenarios:
            numbers = [
                int(row[0])
                for row in connection.execute(
                    "SELECT revision_number FROM planning_scenario_revisions "
                    "WHERE scenario_id = ? ORDER BY revision_number",
                    (scenario_id,),
                ).fetchall()
            ]
            if numbers != list(range(1, int(current_revision) + 1)):
                invalid.append("PLANNING_REVISION_SEQUENCE_INVALID")
        bad_amounts = connection.execute(
            "SELECT id FROM planning_items WHERE CAST(amount AS NUMERIC) < 0 "
            "OR amount IS NULL OR amount = ''"
        ).fetchall()
        if bad_amounts:
            invalid.append("PLANNING_AMOUNT_INVALID")
        return AuditCheck(
            name="planning_invariants",
            passed=not invalid,
            issue_codes=sorted(set(invalid)),
        )

    @staticmethod
    def _verify_forecasting(connection: sqlite3.Connection) -> AuditCheck:
        invalid: list[str] = []
        forecasts = connection.execute(
            "SELECT id, scenario_id, source_revision_id, source_revision_number, horizon_months, current_revision_number "
            "FROM savings_forecasts"
        ).fetchall()
        for forecast_id, scenario_id, source_revision_id, source_revision_number, horizon_months, current_revision in forecasts:
            if int(horizon_months) != 36:
                invalid.append("FORECAST_HORIZON_INVALID")
            source = connection.execute(
                "SELECT scenario_id, revision_number FROM planning_scenario_revisions WHERE id = ?",
                (source_revision_id,),
            ).fetchone()
            if not source or source[0] != scenario_id or int(source[1]) != int(source_revision_number):
                invalid.append("FORECAST_SOURCE_PLAN_REFERENCE_INVALID")
            numbers = [
                int(row[0])
                for row in connection.execute(
                    "SELECT revision_number FROM savings_forecast_revisions WHERE forecast_id = ? ORDER BY revision_number",
                    (forecast_id,),
                ).fetchall()
            ]
            if numbers != list(range(1, int(current_revision) + 1)):
                invalid.append("FORECAST_REVISION_SEQUENCE_INVALID")
            for revision_id, revision_source_id, revision_source_number, stored_hash, assumptions in connection.execute(
                "SELECT id, source_revision_id, source_revision_number, assumption_hash, assumptions_json "
                "FROM savings_forecast_revisions WHERE forecast_id = ?",
                (forecast_id,),
            ).fetchall():
                if revision_source_id != source_revision_id or int(revision_source_number) != int(source_revision_number):
                    invalid.append("FORECAST_SOURCE_PLAN_REFERENCE_INVALID")
                try:
                    snapshot = ForecastRevisionSnapshot.model_validate(json.loads(assumptions))
                    if assumption_hash(snapshot) != stored_hash:
                        invalid.append("FORECAST_ASSUMPTION_HASH_INVALID")
                except (TypeError, ValueError, json.JSONDecodeError):
                    invalid.append("FORECAST_ASSUMPTIONS_INVALID")
                roles = [
                    str(row[0])
                    for row in connection.execute(
                        "SELECT role FROM savings_forecast_cases WHERE revision_id = ? ORDER BY role",
                        (revision_id,),
                    ).fetchall()
                ]
                if roles != ["baseline", "conservative", "optimistic"]:
                    invalid.append("FORECAST_CASE_SET_INVALID")
                case_rows = connection.execute(
                    "SELECT id, annual_return_rate, sweep_enabled, sweep_pool_id "
                    "FROM savings_forecast_cases WHERE revision_id = ?",
                    (revision_id,),
                ).fetchall()
                for case_id, annual_return_rate, sweep_enabled, sweep_pool_id in case_rows:
                    try:
                        rate = Decimal(str(annual_return_rate))
                        if not rate.is_finite() or rate <= Decimal(-1):
                            invalid.append("FORECAST_RETURN_RATE_INVALID")
                    except (InvalidOperation, TypeError, ValueError):
                        invalid.append("FORECAST_RETURN_RATE_INVALID")
                    pool_ids = {
                        str(row[0])
                        for row in connection.execute(
                            "SELECT id FROM savings_forecast_pools WHERE case_id = ?",
                            (case_id,),
                        ).fetchall()
                    }
                    if not pool_ids:
                        invalid.append("FORECAST_POOL_SET_EMPTY")
                    if bool(sweep_enabled) and str(sweep_pool_id) not in pool_ids:
                        invalid.append("FORECAST_SWEEP_POOL_INVALID")
                    for pool_id, source_item_id in connection.execute(
                        "SELECT pool_id, source_item_id FROM savings_forecast_routings WHERE case_id = ?",
                        (case_id,),
                    ).fetchall():
                        if str(pool_id) not in pool_ids:
                            invalid.append("FORECAST_ROUTING_POOL_INVALID")
                        item = connection.execute(
                            "SELECT revision_id, kind FROM planning_items WHERE id = ?",
                            (source_item_id,),
                        ).fetchone()
                        if not item or item[0] != source_revision_id or item[1] not in {"savings_contribution", "savings_withdrawal"}:
                            invalid.append("FORECAST_ROUTING_SOURCE_INVALID")
                    for event_type, pool_id in connection.execute(
                        "SELECT event_type, pool_id FROM savings_forecast_events WHERE case_id = ?",
                        (case_id,),
                    ).fetchall():
                        if event_type in {"contribution", "withdrawal"} and str(pool_id) not in pool_ids:
                            invalid.append("FORECAST_EVENT_POOL_INVALID")
        return AuditCheck(
            name="forecast_invariants",
            passed=not invalid,
            issue_codes=sorted(set(invalid)),
        )


__all__ = ["BackupService"]
