"""Authenticated automation status, history, and safe dry-run routes."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Query, Request
from sqlalchemy import select

from family_finance.api.app import ApiError, _envelope, authenticated_router
from family_finance.api.audit import record_actor_audit
from family_finance.api.routers.operations import operations_snapshot
from family_finance.api.schemas.operations import AutomationRunBody
from family_finance.automation import AutomationService
from family_finance.persistence.models import AutomationRunRow

router = authenticated_router(prefix="/automation")


def _json_object(value: str | None, fallback: Any) -> Any:
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(fallback)) else fallback
    except (TypeError, ValueError):
        return fallback


def _run_summary(row: AutomationRunRow) -> dict[str, Any]:
    counts = _json_object(row.counts_json, {})
    issue_codes = _json_object(row.issue_codes_json, [])
    return {
        "id": row.id,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "status": row.status,
        "dry_run": bool(row.dry_run),
        "audit_passed": bool(row.audit_passed),
        "backup_created": bool(row.backup_path),
        "counts": {
            str(key): value for key, value in counts.items()
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        },
        "issue_codes": [item for item in issue_codes if isinstance(item, str)][:100],
    }


def _inbox_summary(settings) -> dict[str, int]:
    inbox_root = settings.automation_inbox_root
    review_root = settings.automation_needs_review_root
    inbox = (
        [path for path in inbox_root.iterdir()
         if path.suffix.casefold() == ".xlsx" and (path.is_symlink() or path.is_file())]
        if inbox_root.is_dir() else []
    )
    review = (
        [path for path in review_root.rglob("*.xlsx")
         if path.is_file() and not path.is_symlink()]
        if review_root.is_dir() else []
    )
    return {
        "inbox_file_count": len(inbox),
        "review_file_count": len(review),
    }


@router.get("/status")
def get_status(request: Request):
    database = request.app.state.database
    settings = request.app.state.services.settings
    with database.session() as session:
        latest = session.execute(
            select(AutomationRunRow).order_by(AutomationRunRow.started_at.desc()).limit(1)
        ).scalar_one_or_none()
    return _envelope(
        {
            "inbox": _inbox_summary(settings),
            "operations": operations_snapshot(database, settings),
            "latest_run": _run_summary(latest) if latest else None,
        },
        request.state.request_id,
    )


@router.get("/inbox")
def get_inbox_summary(request: Request):
    return _envelope(
        _inbox_summary(request.app.state.services.settings), request.state.request_id
    )


@router.get("/runs")
def list_runs(request: Request, limit: int = Query(default=20, ge=1, le=100)):
    with request.app.state.database.session() as session:
        rows = session.execute(
            select(AutomationRunRow)
            .order_by(AutomationRunRow.started_at.desc(), AutomationRunRow.id.desc())
            .limit(limit)
        ).scalars().all()
    return _envelope({"items": [_run_summary(row) for row in rows]}, request.state.request_id)


def _record_manual_run_event(request: Request, outcome: str) -> None:
    actor = request.state.authenticated_user
    with request.app.state.database.api_write_unit_of_work() as session:
        record_actor_audit(
            session,
            actor_id=actor.user_id,
            event_type="automation.manual_run",
            target_type="automation",
            outcome=outcome,
            request_id=request.state.request_id,
        )


def _run_wire(result) -> dict[str, Any]:
    return {
        "id": result.run_id,
        "status": result.status,
        "dry_run": result.dry_run,
        "audit_passed": result.audit_passed,
        "backup_created": bool(result.backup_path),
        "counts": result.counts,
        "issue_codes": result.issue_codes,
        "started_at": result.started_at.isoformat() if result.started_at else None,
        "finished_at": result.finished_at.isoformat() if result.finished_at else None,
        "items": [
            {"status": item.status, "reason_code": item.reason_code}
            for item in result.files
        ],
    }


@router.post("/runs")
def run_automation(body: AutomationRunBody, request: Request):
    if not body.dry_run:
        snapshot = operations_snapshot(
            request.app.state.database, request.app.state.services.settings
        )
        if not snapshot["run_now_allowed"]:
            _record_manual_run_event(request, "blocked")
            raise ApiError(
                409,
                "AUTOMATION_NOT_READY",
                "Manual automation is blocked until the audit passes and the backup destination is ready.",
                fields={"reason": [snapshot["run_now_block_reason"] or "NOT_READY"]},
            )

    _record_manual_run_event(request, "requested")
    automation = AutomationService(
        settings=request.app.state.services.settings,
        database=request.app.state.database,
        import_service=request.app.state.services,
    )
    result = automation.run(dry_run=body.dry_run)
    if not body.dry_run:
        _record_manual_run_event(
            request,
            "success" if result.status in {"completed", "completed_with_warnings"} else "blocked",
        )
    return _envelope(_run_wire(result), request.state.request_id)
