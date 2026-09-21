"""Verified online backups for the SQLite database and immutable imports."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory

from family_finance.config import Settings
from family_finance.models import AuditCheck, BackupManifest, BackupVerification
from family_finance.persistence.db import Database
from family_finance.persistence.models import SourceFileRow


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
            if str(item["relative_path"]).startswith("imports/")
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
                source_hashes = {
                    str(row[0])
                    for row in connection.execute("SELECT sha256 FROM source_files").fetchall()
                }
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
        database_path = root / database.path.name
        with database.session() as session:
            source_files = session.query(SourceFileRow).all()
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


__all__ = ["BackupService"]
