"""Per-user application preferences and scoped household session controls."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Request, Response
from sqlalchemy import func, select

from family_finance.api.app import ApiError, _envelope, authenticated_router
from family_finance.api.audit import record_actor_audit
from family_finance.api.auth import SESSION_COOKIE_NAME
from family_finance.api.routers.operations import operations_snapshot
from family_finance.api.schemas.operations import AppPreferencesBody
from family_finance.persistence.models import (
    ApiUserRow,
    ImportBatchRow,
    NetWorthImportRow,
    PlanningSeedImportRow,
    TransactionRow,
    UserAppPreferencesRow,
)

router = authenticated_router(prefix="/settings")


def _timestamp_age(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max(0, (datetime.now(UTC).date() - parsed.astimezone(UTC).date()).days)
    except ValueError:
        return None


def _freshness(database) -> dict:
    with database.session() as session:
        familybiz_at = session.execute(
            select(func.max(ImportBatchRow.created_at)).where(
                ImportBatchRow.status.in_(("committed", "needs_review", "duplicate"))
            )
        ).scalar_one_or_none()
        latest_transaction = session.execute(
            select(func.max(TransactionRow.booking_date))
        ).scalar_one_or_none()
        planning_at = session.execute(
            select(func.max(PlanningSeedImportRow.imported_at))
        ).scalar_one_or_none()
        net_worth_at = session.execute(
            select(func.max(NetWorthImportRow.imported_at))
        ).scalar_one_or_none()
    return {
        "familybiz": {
            "last_import_at": familybiz_at,
            "latest_transaction_date": latest_transaction,
            "age_days": _timestamp_age(familybiz_at),
        },
        "planning": {"last_import_at": planning_at, "age_days": _timestamp_age(planning_at)},
        "net_worth": {"last_import_at": net_worth_at, "age_days": _timestamp_age(net_worth_at)},
    }


@router.get("")
def get_settings(request: Request):
    database = request.app.state.database
    user = request.state.authenticated_user
    with database.session() as session:
        preferences = session.get(UserAppPreferencesRow, user.user_id)
        members = session.execute(
            select(ApiUserRow.display_name).where(ApiUserRow.enabled.is_(True)).order_by(ApiUserRow.created_at)
        ).scalars().all()
    freshness = _freshness(database)
    operations = operations_snapshot(database, request.app.state.services.settings)
    warnings = list(operations["warnings"])
    familybiz_age = freshness["familybiz"]["age_days"]
    if familybiz_age is not None and familybiz_age > 31:
        warnings.append("FAMILYBIZ_DATA_STALE")
    response = {
        "preferences": {
            "default_currency": preferences.default_currency if preferences else "ILS",
            "default_months": preferences.default_months if preferences else 12,
            "updated_at": preferences.updated_at if preferences else None,
        },
        "freshness": freshness,
        "operations": operations,
        "operational_warnings": sorted(set(warnings)),
        "household": {"member_count": len(members), "members": members, "permissions": "equal"},
    }
    return _envelope(response, request.state.request_id)


@router.put("/preferences")
def save_app_preferences(body: AppPreferencesBody, request: Request):
    user_id = request.state.authenticated_user.user_id
    now = datetime.now(UTC).isoformat()
    database = request.app.state.database
    with database.api_write_unit_of_work() as session:
        record_actor_audit(
            session,
            actor_id=user_id,
            event_type="settings.preferences.update",
            target_type="app_preferences",
            request_id=request.state.request_id,
        )
        row = session.get(UserAppPreferencesRow, user_id)
        if row is None:
            row = UserAppPreferencesRow(user_id=user_id, updated_at=now)
            session.add(row)
        row.default_currency = body.default_currency
        row.default_months = body.default_months
        row.updated_at = now
    return _envelope(
        {
            "default_currency": body.default_currency,
            "default_months": body.default_months,
            "updated_at": now,
        },
        request.state.request_id,
    )


@router.get("/sessions")
def list_sessions(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if not token:
        raise ApiError(401, "AUTHENTICATION_REQUIRED", "Sign in to continue")
    sessions = request.app.state.auth_service.list_sessions(
        user_id=request.state.authenticated_user.user_id,
        current_token=token,
    )
    return _envelope(
        {
            "items": [
                {
                    "id": item.session_id,
                    "created_at": item.created_at,
                    "expires_at": item.expires_at,
                    "current": item.current,
                }
                for item in sessions
            ]
        },
        request.state.request_id,
    )


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(session_id: str, request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if not token:
        raise ApiError(401, "AUTHENTICATION_REQUIRED", "Sign in to continue")
    try:
        request.app.state.auth_service.revoke_session(
            session_id=session_id,
            user_id=request.state.authenticated_user.user_id,
            current_token=token,
            request_id=request.state.request_id,
        )
    except ValueError as exc:
        if "current session" in str(exc).casefold():
            raise ApiError(409, "CURRENT_SESSION", "Sign out to end this session") from exc
        raise ApiError(404, "NOT_FOUND", "The session was not found") from exc
    return Response(status_code=204)
