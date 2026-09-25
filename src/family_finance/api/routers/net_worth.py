"""Authenticated HTTP adapter for observed household net worth."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any

from fastapi import File, Form, Query, Request, Response, UploadFile
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import ArgumentError

from family_finance.api.app import ApiError, authenticated_router
from family_finance.api.audit import record_actor_audit
from family_finance.api.schemas.net_worth import (
    AccountBody,
    AccountCloseBody,
    AccountReactivateBody,
    AccountUpdateBody,
    CsvCommitFields,
    ForecastComparisonBody,
    IsoDate,
    SnapshotArchiveBody,
    SnapshotCreateBody,
    SnapshotRestoreBody,
    SnapshotRevisionBody,
)
from family_finance.net_worth import (
    DuplicateNetWorthAccountError,
    DuplicateNetWorthImportError,
    ExistingSnapshotRevisionError,
    NetWorthPreviewStaleError,
    NetWorthValidationError,
    StaleNetWorthRevisionError,
)

router = authenticated_router(prefix="/net-worth")


def _wire(value: Any) -> Any:
    """Serialize domain values to the API's exact string-based decimal contract."""

    if isinstance(value, BaseModel):
        result = {key: _wire(item) for key, item in value.model_dump(mode="python").items()}
        # These service properties are part of the supported read contract.
        if hasattr(value, "stale_account_keys"):
            result["stale_account_keys"] = _wire(value.stale_account_keys)
        if hasattr(value, "complete"):
            result["complete"] = bool(value.complete)
        return result
    if callable(getattr(value, "model_dump", None)):
        try:
            return _wire(value.model_dump(mode="python"))
        except TypeError:
            return _wire(value.model_dump())
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return aware.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_wire(item) for item in value]
    return value


def _envelope(request: Request, value: Any) -> dict[str, Any]:
    return {"data": _wire(value), "meta": {"request_id": request.state.request_id}}


def _service(
    request: Request,
    operation,
    *args,
    _audit: tuple[str, str] | None = None,
    _precondition: Callable[[], None] | None = None,
    _flush_audit_first: bool = False,
    **kwargs,
):
    try:
        if _audit is None:
            result = operation(*args, **kwargs)
        else:
            actor = request.state.authenticated_user
            with request.app.state.database.api_write_unit_of_work() as session:
                record_actor_audit(
                    session,
                    actor_id=actor.user_id,
                    event_type=_audit[0],
                    target_type=_audit[1],
                    request_id=request.state.request_id,
                )
                # CSV commit has a filesystem step before its database writes.
                # Flush the database audit row before installing that archive.
                if _flush_audit_first:
                    session.flush()
                if _precondition is not None:
                    _precondition()
                result = operation(*args, **kwargs)
    except DuplicateNetWorthAccountError:
        raise ApiError(409, "ACCOUNT_ALREADY_EXISTS", "An account with this key already exists") from None
    except StaleNetWorthRevisionError:
        raise ApiError(409, "STALE_REVISION", "The snapshot changed. Reload it before saving again") from None
    except NetWorthPreviewStaleError:
        raise ApiError(409, "PREVIEW_STALE", "The CSV or account registry changed. Preview the file again") from None
    except ExistingSnapshotRevisionError:
        raise ApiError(409, "EXISTING_SNAPSHOT", "Choose the explicit new revision option to replace this date") from None
    except DuplicateNetWorthImportError:
        raise ApiError(409, "DUPLICATE_IMPORT", "This CSV has already been imported") from None
    except (NetWorthValidationError, ValidationError, ValueError) as exc:
        message = str(exc).casefold()
        if "not found" in message or "does not exist" in message:
            raise ApiError(404, "NOT_FOUND", "The requested net-worth record was not found") from None
        if "already exists" in message or "already exists for this date" in message:
            raise ApiError(409, "EXISTING_SNAPSHOT", "A snapshot already exists for this date") from None
        if "archived" in message:
            raise ApiError(409, "INVALID_STATE", "Archived snapshots cannot be restored") from None
        if "quality acknowledgement is required" in message:
            raise ApiError(422, "QUALITY_ACKNOWLEDGEMENT_REQUIRED", "Review the snapshot quality warnings and acknowledge them before saving") from None
        if "acknowledge stale source valuations" in message:
            raise ApiError(422, "QUALITY_ACKNOWLEDGEMENT_REQUIRED", "Review the stale valuation warnings and acknowledge them before importing") from None
        raise ApiError(422, "VALIDATION_ERROR", "Net-worth data failed validation") from None
    return _envelope(request, result)


def _balances(body):
    return [item.model_dump(mode="python") for item in body]


@router.get("/accounts")
def list_accounts(
    request: Request,
    include_closed: bool = False,
    as_of: Annotated[IsoDate | None, Query()] = None,
):
    service = request.app.state.services.net_worth_service
    if as_of is not None:
        result = _service(request, service.accounts_for_snapshot_date, as_of)
    else:
        result = _service(request, service.list_accounts, include_closed=include_closed)
    return result


@router.post("/accounts", status_code=201)
def create_account(body: AccountBody, request: Request):
    return _service(
        request,
        request.app.state.services.net_worth_service.create_account,
        body,
        _audit=("net_worth.account.create", "net_worth_account"),
    )


@router.put("/accounts/{account_key}")
def update_account(account_key: str, body: AccountUpdateBody, request: Request):
    if body.account_key and body.account_key != account_key:
        raise ApiError(422, "VALIDATION_ERROR", "Account key in the path and body must match")
    service = request.app.state.services.net_worth_service
    changes = body.model_dump(mode="python", exclude={"account_key", "expected_updated_at"})
    return _service(
        request,
        service.update_account,
        account_key,
        _audit=("net_worth.account.update", "net_worth_account"),
        _precondition=lambda: _require_current_account_version(
            request, service, account_key, body.expected_updated_at
        ),
        **changes,
    )


@router.post("/accounts/{account_key}/close")
def close_account(account_key: str, body: AccountCloseBody, request: Request):
    service = request.app.state.services.net_worth_service
    return _service(
        request,
        service.close_account,
        account_key,
        body.closed_on,
        _audit=("net_worth.account.close", "net_worth_account"),
        _precondition=lambda: _require_current_account_version(
            request, service, account_key, body.expected_updated_at
        ),
    )


@router.post("/accounts/{account_key}/reactivate")
def reactivate_account(account_key: str, body: AccountReactivateBody, request: Request):
    service = request.app.state.services.net_worth_service
    return _service(
        request,
        service.reactivate_account,
        account_key,
        body.active_from,
        _audit=("net_worth.account.reactivate", "net_worth_account"),
        _precondition=lambda: _require_current_account_version(
            request, service, account_key, body.expected_updated_at
        ),
    )


def _timestamp_token(value: datetime) -> str:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat().replace("+00:00", "Z")


def _require_current_account_version(request: Request, service, account_key: str, expected_updated_at: datetime):
    current = service.get_account(account_key)
    if current.updated_at is None or _timestamp_token(current.updated_at) != _timestamp_token(expected_updated_at):
        raise ApiError(409, "STALE_ACCOUNT", "The account changed. Reload it before saving again")


@router.get("/snapshots")
def list_snapshots(request: Request, include_archived: bool = False):
    return _service(request, request.app.state.services.net_worth_service.list_snapshots, include_archived=include_archived)


@router.get("/snapshots/{snapshot_id}/revisions")
def list_revisions(snapshot_id: str, request: Request):
    return _service(request, request.app.state.services.net_worth_service.list_revisions, snapshot_id)


@router.get("/snapshots/{snapshot_id}/revisions/{revision_number}")
def get_revision(snapshot_id: str, revision_number: int, request: Request):
    return _service(request, request.app.state.services.net_worth_service.get_revision, snapshot_id, revision_number)


@router.post("/snapshots", status_code=201)
def create_snapshot(body: SnapshotCreateBody, request: Request):
    return _service(
        request,
        request.app.state.services.net_worth_service.create_snapshot,
        body.snapshot_date,
        _balances(body.balances),
        notes=body.notes,
        quality_acknowledged=body.quality_acknowledged,
        _audit=("net_worth.snapshot.create", "net_worth_snapshot"),
    )


@router.post("/snapshots/{snapshot_id}/revisions", status_code=201)
def save_revision(snapshot_id: str, body: SnapshotRevisionBody, request: Request):
    return _service(
        request,
        request.app.state.services.net_worth_service.save_revision,
        snapshot_id,
        _balances(body.balances),
        expected_revision_number=body.expected_revision_number,
        notes=body.notes,
        quality_acknowledged=body.quality_acknowledged,
        _audit=("net_worth.snapshot.revision.create", "net_worth_snapshot"),
    )


@router.post("/snapshots/{snapshot_id}/revisions/{revision_number}/restore", status_code=201)
def restore_revision(snapshot_id: str, revision_number: int, body: SnapshotRestoreBody, request: Request):
    service = request.app.state.services.net_worth_service
    def require_active_snapshot():
        identity = service.get_snapshot(snapshot_id)
        if identity.archived:
            raise ApiError(409, "INVALID_STATE", "Archived snapshots cannot be restored")

    return _service(
        request,
        service.restore_revision,
        snapshot_id,
        revision_number,
        expected_revision_number=body.expected_revision_number,
        quality_acknowledged=body.quality_acknowledged,
        notes=body.notes,
        _audit=("net_worth.snapshot.revision.restore", "net_worth_snapshot"),
        _precondition=require_active_snapshot,
    )


@router.post("/snapshots/{snapshot_id}/archive")
def set_snapshot_archived(snapshot_id: str, body: SnapshotArchiveBody, request: Request):
    service = request.app.state.services.net_worth_service
    event = "net_worth.snapshot.archive" if body.archived else "net_worth.snapshot.unarchive"
    return _service(
        request,
        service.archive_snapshot,
        snapshot_id,
        body.archived,
        _audit=(event, "net_worth_snapshot"),
    )


@router.get("/accounts/{account_key}/history")
def account_history(account_key: str, request: Request):
    service = request.app.state.services.net_worth_service
    _service(request, service.get_account, account_key)
    return _service(request, service.account_history, account_key)


@router.get("/summary")
def current_summary(
    request: Request,
    revision_id: str | None = None,
    snapshot_id: str | None = None,
    as_of_date: Annotated[IsoDate | None, Query()] = None,
):
    service = request.app.state.services.net_worth_service
    return _service(
        request,
        service.summary,
        revision_id,
        snapshot_id=snapshot_id,
        as_of_date=as_of_date,
    )


@router.get("/trend")
def net_worth_trend(
    request: Request,
    start_date: Annotated[IsoDate | None, Query()] = None,
    end_date: Annotated[IsoDate | None, Query()] = None,
):
    if start_date and end_date and start_date > end_date:
        raise ApiError(422, "VALIDATION_ERROR", "Start date must not be after end date")
    return _service(request, request.app.state.services.net_worth_service.trend, start_date, end_date)


@router.get("/csv-template")
def csv_template(request: Request, snapshot_date: Annotated[IsoDate | None, Query()] = None):
    csv_bytes = request.app.state.services.net_worth_service.csv_template(snapshot_date)
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="net-worth-template.csv"'},
    )


@router.post("/csv/previews")
def preview_csv(request: Request, file: UploadFile = File(...)):  # noqa: B008
    content = file.file.read()
    service = request.app.state.services.net_worth_service
    try:
        return _service(request, service.preview_csv, content, file.filename)
    except ArgumentError:
        # The current service can raise while preparing its optional existing-
        # snapshot lookup when an invalid file has no parseable snapshot date.
        # Keep malformed uploads on the validation path without exposing SQL.
        raise ApiError(422, "VALIDATION_ERROR", "CSV file is invalid or has no valid snapshot date") from None


@router.post("/csv/commits", status_code=201)
def commit_csv(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    preview_token: str = Form(..., min_length=1, max_length=4096),
    filename: str | None = Form(default=None, max_length=255),
    create_new_revision: bool = Form(default=False),
    quality_acknowledged: bool = Form(default=False),
):
    fields = CsvCommitFields(
        preview_token=preview_token,
        filename=filename,
        create_new_revision=create_new_revision,
        quality_acknowledged=quality_acknowledged,
    )
    content = file.file.read()
    original_filename = fields.filename or file.filename
    return _service(
        request,
        request.app.state.services.net_worth_service.commit_csv,
        content,
        fields.preview_token,
        original_filename,
        create_new_revision=fields.create_new_revision,
        quality_acknowledged=fields.quality_acknowledged,
        _audit=("net_worth.csv.commit", "net_worth_import"),
        _flush_audit_first=True,
    )


@router.post("/forecast-comparisons")
def compare_forecast(body: ForecastComparisonBody, request: Request):
    return _service(
        request,
        request.app.state.services.net_worth_service.compare_forecast_actual,
        body.forecast_id,
        body.observed_snapshot_revision_id,
        body.forecast_revision_number,
        role=body.role,
    )
