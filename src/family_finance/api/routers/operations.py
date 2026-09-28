"""Read-only audit and backup readiness summaries."""

from __future__ import annotations

import re
from typing import Any

from fastapi import Request

from family_finance.api.app import _envelope, authenticated_router
from family_finance.audit import AuditService
from family_finance.backup import BackupService
from family_finance.config import Settings
from family_finance.persistence.db import Database

router = authenticated_router(prefix="/operations")
_BACKUP_NAME = re.compile(r"^\d{8}T\d{6}Z(?:-[0-9a-f]{8})?$")


def _backup_health(database: Database, settings: Settings) -> dict[str, Any]:
    root = settings.automation_backup_root
    archive_status = "not_configured" if root is None else "no_verified_backup"
    last_verified_at: str | None = None
    if root is not None:
        try:
            if root.is_symlink() or (root.exists() and not root.is_dir()):
                archive_status = "unavailable"
            elif root.is_dir():
                candidates = sorted(
                    (item for item in root.iterdir() if _BACKUP_NAME.fullmatch(item.name)
                     and item.is_dir() and not item.is_symlink()),
                    key=lambda item: item.name,
                    reverse=True,
                )
                if candidates:
                    latest = candidates[0]
                    verification = BackupService(database, settings).verify(latest)
                    archive_status = "verified" if verification.passed else "verification_failed"
                    if verification.passed:
                        last_verified_at = latest.name[:16]
                else:
                    archive_status = "no_verified_backup"
            else:
                # The runner may create the configured root on its first run.
                archive_status = "not_created"
        except OSError:
            archive_status = "unavailable"

    return {
        "configured": root is not None,
        "status": archive_status,
        "last_verified_at": last_verified_at,
    }


def operations_snapshot(database: Database, settings: Settings) -> dict[str, Any]:
    audit = AuditService(database, settings).run()
    backup = _backup_health(database, settings)
    backup_ready = bool(backup["configured"] and backup["status"] != "unavailable")
    warnings = sorted({
        code
        for check in audit.checks
        for code in check.issue_codes
    })
    if not backup["configured"]:
        warnings.append("AUTOMATION_BACKUP_NOT_CONFIGURED")
    elif backup["status"] == "verification_failed":
        warnings.append("LATEST_BACKUP_VERIFICATION_FAILED")
    elif backup["status"] == "unavailable":
        warnings.append("AUTOMATION_BACKUP_DESTINATION_UNAVAILABLE")
    warnings = sorted(set(warnings))
    return {
        "audit": audit.model_dump(mode="json"),
        "backup": backup,
        "run_now_allowed": bool(audit.passed and backup_ready),
        "run_now_block_reason": (
            None if audit.passed and backup_ready
            else "AUDIT_FAILED" if not audit.passed
            else "AUTOMATION_BACKUP_NOT_CONFIGURED" if not backup["configured"]
            else "AUTOMATION_BACKUP_DESTINATION_UNAVAILABLE"
        ),
        "warnings": warnings,
    }


@router.get("/audit")
def get_audit(request: Request):
    snapshot = operations_snapshot(
        request.app.state.database, request.app.state.services.settings
    )
    return _envelope({"audit": snapshot["audit"]}, request.state.request_id)


@router.get("/backup-readiness")
def get_backup_readiness(request: Request):
    snapshot = operations_snapshot(
        request.app.state.database, request.app.state.services.settings
    )
    return _envelope(
        {
            "backup": snapshot["backup"],
            "archive_integrity": next(
                (check for check in snapshot["audit"]["checks"]
                 if check["name"] == "archive_hashes"),
                {"name": "archive_hashes", "passed": False, "issue_codes": ["CHECK_UNAVAILABLE"]},
            ),
            "run_now_allowed": snapshot["run_now_allowed"],
            "run_now_block_reason": snapshot["run_now_block_reason"],
            "warnings": snapshot["warnings"],
        },
        request.state.request_id,
    )
