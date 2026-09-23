"""Safe, local-only recurring FamilyBiz import automation."""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from family_finance.audit import AuditService
from family_finance.backup import BackupService
from family_finance.config import Settings
from family_finance.logging import JsonEventLogger
from family_finance.models import (
    AutomationFileResult,
    AutomationRunResult,
    ImportPreflight,
)
from family_finance.persistence.db import Database, json_dumps, utc_now
from family_finance.persistence.models import (
    AutomationFileOutcomeRow,
    AutomationRunRow,
)
from family_finance.services import (
    ImportAmbiguityError,
    ImportService,
)


class AutomationBusyError(RuntimeError):
    """Another local automation process owns the single-process lock."""


class AutomationService:
    def __init__(
        self,
        settings: Settings | None = None,
        database: Database | None = None,
        import_service: ImportService | None = None,
    ) -> None:
        self.settings = settings or Settings.from_environment()
        self.settings.ensure_directories()
        self.database = database or Database(self.settings.database_path)
        self.import_service = import_service or ImportService(
            self.settings, database=self.database
        )
        self.logger = JsonEventLogger(self.settings.log_path)

    def run(self, *, dry_run: bool = False) -> AutomationRunResult:
        """Run one idempotent inbox pass and return privacy-safe status data."""
        run_id = str(uuid.uuid4())
        started = datetime.now(UTC)
        files: list[AutomationFileResult] = []
        issue_codes: list[str] = []
        counts: dict[str, int] = {}
        audit_passed = False
        backup_path: str | None = None
        status = "failed"
        if not dry_run:
            self._insert_run(run_id, started, dry_run)
        try:
            with self._process_lock():
                audit = AuditService(self.database, self.settings).run()
                audit_passed = audit.passed
                if not audit_passed:
                    issue_codes.extend(
                        sorted({code for check in audit.checks for code in check.issue_codes})
                    )
                    status = "blocked_audit"
                    return self._finish(
                        run_id, started, status, dry_run, audit_passed, backup_path,
                        files, counts, issue_codes,
                    )
                if self.settings.automation_backup_root is None:
                    issue_codes.append("AUTOMATION_BACKUP_NOT_CONFIGURED")

                paths = self._inbox_files()
                # A backup is a run-level precondition for the first mutation.
                # Dry runs do not mutate the database and therefore do not need one.
                if paths and not dry_run and self.settings.automation_backup_root is not None:
                    try:
                        backup_path = str(self._create_backup())
                    except Exception:  # noqa: BLE001
                        issue_codes.append("AUTOMATION_BACKUP_FAILED")
                        status = "blocked_backup"
                        return self._finish(
                            run_id, started, status, dry_run, audit_passed, backup_path,
                            files, counts, issue_codes,
                        )

                for path in paths:
                    result = self._process_file(path, dry_run=dry_run)
                    files.append(result)
                    counts[result.status] = counts.get(result.status, 0) + 1
                    if result.reason_code:
                        issue_codes.append(result.reason_code)
                    # A successful commit is followed by a full audit.  This
                    # makes a bad write stop the remainder of the run.
                    if result.status == "committed" and not dry_run:
                        after_commit = AuditService(self.database, self.settings).run()
                        if not after_commit.passed:
                            issue_codes.extend(
                                sorted({
                                    code
                                    for check in after_commit.checks
                                    for code in check.issue_codes
                                })
                            )
                            status = "failed_audit"
                            break

                if dry_run:
                    status = "dry_run"
                elif status != "failed_audit":
                    non_configuration_issues = set(issue_codes) - {
                        "AUTOMATION_BACKUP_NOT_CONFIGURED"
                    }
                    status = (
                        "completed_with_warnings"
                        if non_configuration_issues
                        else "completed"
                    )
                # Attention files are a successful, non-mutating outcome of an
                # automation pass. Refreshing insights must not depend on all
                # inbox files being auto-committable.
                if (
                    not dry_run
                    and audit_passed
                    and status not in {"blocked_backup", "failed_audit"}
                ):
                    try:
                        insight_service = self.import_service.insights_service
                        insight_service.reconcile_alerts()
                        insight_service.generate_previous_month_summary()
                    except Exception:  # noqa: BLE001
                        # Insight refresh is visible as an issue, but cannot
                        # turn a successfully committed import into a rollback.
                        issue_codes.append("INSIGHTS_REFRESH_FAILED")
                        if status == "completed":
                            status = "completed_with_warnings"
                return self._finish(
                    run_id, started, status, dry_run, audit_passed, backup_path,
                    files, counts, issue_codes,
                )
        except AutomationBusyError:
            status = "busy"
            issue_codes.append("AUTOMATION_LOCK_BUSY")
            return self._finish(
                run_id, started, status, dry_run, audit_passed, backup_path,
                files, counts, issue_codes,
            )
        except Exception:  # noqa: BLE001
            issue_codes.append("AUTOMATION_RUN_FAILED")
            return self._finish(
                run_id, started, status, dry_run, audit_passed, backup_path,
                files, counts, issue_codes,
            )

    def preflight_attention(self, path: str | Path) -> ImportPreflight:
        target = self._safe_inbox_or_review_path(path)
        return self.import_service.preflight_import(target.read_bytes(), target.name)

    def commit_attention(self, path: str | Path) -> object:
        """Explicitly commit an attention file, allowing reconciliation cases."""
        target = self._safe_inbox_or_review_path(path)
        payload = target.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        preview = self.import_service.preflight_import(payload, target.name)
        if preview.action == "needs_review" and preview.duplicate_file is False:
            result = self.import_service.commit_import(
                payload, preview.preview_token, target.name
            )
            if result.status.value in {"committed", "duplicate", "needs_review"}:
                managed = self._move_managed(target, "processed", result.batch_id)
                self._update_attention_outcome(target, managed, digest, result)
            return result
        if preview.action == "duplicate":
            result = self.import_service.commit_import(
                payload, preview.preview_token, target.name
            )
            managed = self._move_managed(target, "processed", result.batch_id)
            self._update_attention_outcome(target, managed, digest, result)
            return result
        raise ValueError("Only valid attention files can be committed for reconciliation")

    def list_attention_files(self) -> list[Path]:
        return sorted(
            item for item in self.settings.automation_needs_review_root.rglob("*.xlsx")
            if item.is_file() and not item.is_symlink()
        )

    def _process_file(self, path: Path, *, dry_run: bool) -> AutomationFileResult:
        if path.is_symlink() or not path.is_file():
            return AutomationFileResult(
                source_path=str(path), status="needs_review", reason_code="SYMLINK_OR_NOT_REGULAR"
            )
        if not self._is_stable(path):
            if dry_run:
                return AutomationFileResult(
                    source_path=str(path), status="unstable", reason_code="UNSTABLE_FILE"
                )
            return self._move_attention(
                path, "UNSTABLE_FILE", size_bytes=self._safe_size(path)
            )
        try:
            payload = path.read_bytes()
        except OSError:
            if dry_run:
                return AutomationFileResult(
                    source_path=str(path), status="invalid", reason_code="FILE_READ_FAILED"
                )
            return self._move_attention(path, "FILE_READ_FAILED")
        digest = hashlib.sha256(payload).hexdigest()
        try:
            preflight = self.import_service.preflight_import(payload, path.name)
        except Exception:  # noqa: BLE001
            if dry_run:
                return AutomationFileResult(
                    source_path=str(path), sha256=digest, status="invalid",
                    reason_code="SCHEMA_INVALID", size_bytes=len(payload),
                )
            return self._move_attention(path, "SCHEMA_INVALID", sha256=digest, size_bytes=len(payload))
        if dry_run:
            return AutomationFileResult(
                source_path=str(path), sha256=digest, status=("duplicate" if preflight.duplicate_file else ("needs_review" if preflight.ambiguous_count else "ready")),
                reason_code="AMBIGUOUS_MATCH" if preflight.ambiguous_count else None,
                size_bytes=len(payload), preflight=preflight,
            )
        if preflight.duplicate_file:
            # Record a normal duplicate batch through the authoritative service,
            # then archive the input as a successful no-op.
            result = self.import_service.commit_import(payload, preflight.preview_token, path.name)
            managed = self._move_managed(path, "processed", result.batch_id)
            return AutomationFileResult(
                source_path=str(path), sha256=digest, status="duplicate",
                batch_id=result.batch_id, managed_path=str(managed), size_bytes=len(payload),
                preflight=preflight,
            )
        if preflight.ambiguous_count:
            return self._move_attention(path, "AMBIGUOUS_MATCH", digest, len(payload), preflight)
        try:
            result = self.import_service.commit_import(
                payload, preflight.preview_token, path.name, require_unambiguous=True
            )
        except ImportAmbiguityError:
            return self._move_attention(path, "AMBIGUOUS_MATCH", digest, len(payload), preflight)
        except ValueError:
            return self._move_attention(path, "COMMIT_REJECTED", digest, len(payload), preflight)
        managed = self._move_managed(path, "processed", result.batch_id)
        return AutomationFileResult(
            source_path=str(path), sha256=digest, status="committed",
            batch_id=result.batch_id, managed_path=str(managed), size_bytes=len(payload),
            preflight=preflight,
        )

    def _inbox_files(self) -> list[Path]:
        return sorted(
            path for path in self.settings.automation_inbox_root.iterdir()
            if path.suffix.casefold() == ".xlsx" and (path.is_symlink() or path.is_file())
        )

    def _is_stable(self, path: Path) -> bool:
        try:
            first = path.stat()
            if path.is_symlink() or not path.is_file():
                return False
            time.sleep(max(0.0, self.settings.automation_stability_delay_seconds))
            second = path.stat()
            return (
                first.st_size == second.st_size
                and first.st_mtime_ns == second.st_mtime_ns
                and first.st_ino == second.st_ino
            )
        except OSError:
            return False

    @staticmethod
    def _safe_size(path: Path) -> int | None:
        try:
            return path.stat().st_size
        except OSError:
            return None

    def _create_backup(self) -> Path:
        root = self.settings.automation_backup_root
        if root is None:
            raise RuntimeError("Automation backup root is not configured")
        root.mkdir(parents=True, exist_ok=True)
        target = root / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = target if not target.exists() else root / f"{target.name}-{uuid.uuid4().hex[:8]}"
        return BackupService(self.database, self.settings).create(target) and target

    def _move_attention(
        self,
        path: Path,
        reason: str,
        sha256: str | None = None,
        size_bytes: int | None = None,
        preflight: ImportPreflight | None = None,
    ) -> AutomationFileResult:
        managed = self._move_managed(path, "needs-review", sha256 or uuid.uuid4().hex)
        return AutomationFileResult(
            source_path=str(path), sha256=sha256, status="needs_review",
            reason_code=reason, managed_path=str(managed), size_bytes=size_bytes,
            preflight=preflight,
        )

    def _move_managed(self, source: Path, tree: str, identity: str) -> Path:
        now = datetime.now(UTC)
        root = (
            self.settings.automation_processed_root
            if tree == "processed" else self.settings.automation_needs_review_root
        ) / now.strftime("%Y-%m")
        root.mkdir(parents=True, exist_ok=True)
        target = root / source.name
        if target.exists():
            target = root / f"{identity}-{source.name}"
        temporary = root / f".{target.name}.tmp-{uuid.uuid4().hex}"
        try:
            payload = source.read_bytes()
            temporary.write_bytes(payload)
            if _sha256(temporary) != _sha256(source):
                raise OSError("Managed file hash verification failed")
            os.replace(temporary, target)
            source.unlink()
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return target

    def _update_attention_outcome(
        self, source: Path, managed: Path, digest: str, result: object
    ) -> None:
        """Keep the audit trail aligned when an attention file is reviewed."""
        with self.database.write_session() as session:
            outcomes = (
                session.query(AutomationFileOutcomeRow)
                .filter(AutomationFileOutcomeRow.managed_path == str(source))
                .all()
            )
            if not outcomes:
                outcomes = (
                    session.query(AutomationFileOutcomeRow)
                    .filter(
                        AutomationFileOutcomeRow.sha256 == digest,
                        AutomationFileOutcomeRow.managed_path.is_not(None),
                    )
                    .order_by(AutomationFileOutcomeRow.created_at.desc())
                    .limit(1)
                    .all()
                )
            for outcome in outcomes:
                outcome.sha256 = digest
                outcome.managed_path = str(managed)
                outcome.status = result.status.value
                outcome.import_batch_id = result.batch_id

    def _safe_inbox_or_review_path(self, value: str | Path) -> Path:
        target = Path(value).expanduser().resolve()
        roots = [self.settings.automation_inbox_root.resolve(), self.settings.automation_needs_review_root.resolve()]
        if not any(_under_root(target, root) for root in roots) or not target.is_file() or target.is_symlink():
            raise ValueError("Attention file is outside the automation file trees")
        return target

    @contextmanager
    def _process_lock(self) -> Iterator[None]:
        lock_path = self.settings.automation_lock_path
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+")
        try:
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError) as exc:
                handle.close()
                raise AutomationBusyError from exc
            try:
                yield
            finally:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            if not handle.closed:
                handle.close()

    def _insert_run(self, run_id: str, started: datetime, dry_run: bool) -> None:
        with self.database.write_session() as session:
            session.add(AutomationRunRow(
                id=run_id, started_at=started.isoformat(), status="running",
                dry_run=dry_run, audit_passed=False,
            ))

    def _finish(self, run_id, started, status, dry_run, audit_passed, backup_path, files, counts, issue_codes):
        finished = datetime.now(UTC)
        issue_codes = sorted(set(issue_codes))
        if not dry_run:
            with self.database.write_session() as session:
                run = session.get(AutomationRunRow, run_id)
                if run:
                    run.finished_at = finished.isoformat()
                    run.status = status
                    run.audit_passed = audit_passed
                    run.backup_path = backup_path
                    run.counts_json = json_dumps(counts)
                    run.issue_codes_json = json_dumps(issue_codes)
                for item in files:
                    session.add(AutomationFileOutcomeRow(
                        id=str(uuid.uuid4()), run_id=run_id, source_path=item.source_path,
                        sha256=item.sha256, status=item.status, reason_code=item.reason_code,
                        import_batch_id=item.batch_id, managed_path=item.managed_path,
                        size_bytes=item.size_bytes, created_at=utc_now(),
                    ))
        result = AutomationRunResult(
            run_id=run_id, status=status, dry_run=dry_run, audit_passed=audit_passed,
            backup_path=backup_path, files=files, counts=counts,
            issue_codes=issue_codes, started_at=started, finished_at=finished,
        )
        self.logger.event("automation_run", status=status, counts=counts, issue_codes=issue_codes)
        return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


__all__ = ["AutomationBusyError", "AutomationService"]
