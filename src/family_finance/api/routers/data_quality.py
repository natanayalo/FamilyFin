"""Authenticated Data Quality, FamilyBiz import, and reconciliation routes."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from family_finance.api.app import (
    ApiError,
    _envelope,
    authenticated_router,
    current_user,
)
from family_finance.api.auth import AuthenticatedUser
from family_finance.api.idempotency import IdempotencyKeyReusedError, IdempotencyStore
from family_finance.api.schemas.data_quality import (
    DataQualitySummary,
    FamilyBizPreview,
    ReconciliationCase,
    ReconciliationResolutionBody,
    import_history_item,
)
from family_finance.importers.familybiz import FamilyBizSchemaError
from family_finance.persistence.models import ReconciliationCaseRow, SourceRecordRow
from family_finance.services import (
    ImportValidationError,
    PreviewStaleError,
)

router = authenticated_router()

_HISTORY_CURSOR_ROUTE = "imports-history-v1"
_CASES_CURSOR_ROUTE = "reconciliation-cases-v1"
_MAX_CURSOR_CHARS = 512
_MAX_PREVIEW_TOKEN_CHARS = 16_384


def _error(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    fields: dict[str, list[str]] | None = None,
) -> ApiError:
    return ApiError(status_code, code, message, fields=fields)


def _cursor_encode(route: str, offset: int, limit: int) -> str:
    raw = json.dumps(
        {"route": route, "offset": offset, "limit": limit},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _cursor_offset(cursor: str | None, route: str, limit: int, request: Request) -> int:
    if cursor is None:
        return 0
    if len(cursor) > _MAX_CURSOR_CHARS:
        raise _error(request, 400, "INVALID_CURSOR", "The page cursor is invalid")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeEncodeError, binascii.Error, json.JSONDecodeError):
        raise _error(request, 400, "INVALID_CURSOR", "The page cursor is invalid") from None
    if (
        not isinstance(payload, dict)
        or payload.get("route") != route
        or payload.get("limit") != limit
        or not isinstance(payload.get("offset"), int)
        or isinstance(payload.get("offset"), bool)
        or payload["offset"] < 0
    ):
        raise _error(request, 400, "INVALID_CURSOR", "The page cursor is invalid")
    return payload["offset"]


def _collection_response(
    request: Request,
    *,
    route: str,
    rows: list[Any],
    cursor: str | None,
    limit: int,
    mapper,
) -> dict[str, Any]:
    offset = _cursor_offset(cursor, route, limit, request)
    selected = rows[offset : offset + limit]
    next_offset = offset + len(selected)
    next_cursor = _cursor_encode(route, next_offset, limit) if next_offset < len(rows) else None
    return {
        "data": {"items": [mapper(row).model_dump(mode="json") for row in selected]},
        "meta": {
            "request_id": request.state.request_id,
            "next_cursor": next_cursor,
            "limit": limit,
        },
    }


async def _uploaded_xlsx(
    request: Request,
    *,
    expected_fields: set[str],
) -> tuple[bytes, str | None, str | None]:
    """Read one bounded upload from the multipart request without retaining it."""

    try:
        form = await request.form()
    except (HTTPException, ValueError, OSError):
        raise _error(
            request,
            422,
            "INVALID_UPLOAD",
            "The upload form is invalid",
            fields={"file": ["Select one FamilyBiz XLSX file."]},
        ) from None
    try:
        fields = form.multi_items()
        if len(fields) != len(expected_fields) or {key for key, _ in fields} != expected_fields:
            raise _error(
                request,
                422,
                "INVALID_UPLOAD",
                "The upload form is invalid",
                fields={"file": ["The request must contain only the required upload fields."]},
            )
        values = dict(fields)
        upload = values.get("file")
        if not isinstance(upload, UploadFile):
            raise _error(
                request,
                422,
                "INVALID_UPLOAD",
                "The upload form is invalid",
                fields={"file": ["Select one FamilyBiz XLSX file."]},
            )
        filename = upload.filename
        if filename is not None and len(filename) > 255:
            raise _error(
                request,
                422,
                "INVALID_UPLOAD",
                "The upload form is invalid",
                fields={"file": ["The filename is too long."]},
            )
        max_compressed_bytes = request.app.state.services.settings.max_compressed_bytes
        raw = await upload.read(max_compressed_bytes + 1)
        if len(raw) > max_compressed_bytes:
            raise _error(
                request,
                413,
                "REQUEST_TOO_LARGE",
                "The XLSX upload exceeds the configured file limit",
                fields={"file": ["Choose a file no larger than the configured 25 MiB limit."]},
            )
        token = values.get("preview_token")
        if token is not None and (not isinstance(token, str) or len(token) > _MAX_PREVIEW_TOKEN_CHARS):
            raise _error(
                request,
                422,
                "INVALID_UPLOAD",
                "The upload form is invalid",
                fields={"preview_token": ["The preview token is invalid."]},
            )
        return raw, filename, token
    finally:
        await form.close()


def _map_familybiz_error(request: Request, exc: Exception) -> ApiError:
    # Parser messages may contain uploaded values. Expose a stable safe error.
    message = str(exc).casefold()
    if "exceeds" in message and "limit" in message:
        return _error(
            request,
            413,
            "REQUEST_TOO_LARGE",
            "The XLSX upload exceeds a configured parser limit",
            fields={"file": ["The workbook exceeds the configured size or row limit."]},
        )
    return _error(
        request,
        422,
        "INVALID_FAMILYBIZ_WORKBOOK",
        "The workbook could not be validated as a FamilyBiz XLSX export",
        fields={"file": ["Check that this is a valid FamilyBiz XLSX export and preview it again."]},
    )


def _reconciliation_case(row: dict[str, Any]) -> ReconciliationCase:
    source = row.get("source")
    source_fields = (
        "booking_date",
        "allocation_date",
        "amount",
        "currency",
        "original_currency",
        "original_amount",
        "description",
        "movement_type",
        "category",
    )
    candidate_fields = (
        "id",
        "account",
        "booking_date",
        "allocation_date",
        "amount",
        "currency",
        "original_currency",
        "original_amount",
        "description",
        "movement_type",
        "category",
    )
    return ReconciliationCase.model_validate(
        {
            "id": row["id"],
            "import_batch_id": row["import_batch_id"],
            "source_record_id": row["source_record_id"],
            "reason": row["reason"],
            "created_at": row["created_at"],
            "source": ({key: source.get(key) for key in source_fields} if source else None),
            "candidates": [
                {key: candidate.get(key) for key in candidate_fields}
                for candidate in row.get("candidates", [])
            ],
        }
    )


def _import_history(request: Request) -> list[dict[str, Any]]:
    rows = request.app.state.services.history()
    batch_ids = [str(row["id"]) for row in rows]
    issue_codes: dict[str, set[str]] = {batch_id: set() for batch_id in batch_ids}
    if batch_ids:
        with request.app.state.database.session() as session:
            source_rows = session.execute(
                select(SourceRecordRow.import_batch_id, SourceRecordRow.issues_json).where(
                    SourceRecordRow.import_batch_id.in_(batch_ids)
                )
            )
            for batch_id, issues_json in source_rows:
                for issue in json.loads(issues_json):
                    code = issue.get("code")
                    if code:
                        issue_codes[str(batch_id)].add(str(code))
            cases = session.execute(
                select(ReconciliationCaseRow.import_batch_id).where(
                    ReconciliationCaseRow.import_batch_id.in_(batch_ids)
                )
            )
            for (batch_id,) in cases:
                issue_codes[str(batch_id)].add("RECONCILIATION_REQUIRED")
    enriched = []
    for row in rows:
        item = dict(row)
        codes = issue_codes.get(str(item["id"]), set())
        if item.get("error_code"):
            codes.add(str(item["error_code"]))
        item["issue_codes"] = sorted(codes)
        enriched.append(item)
    return enriched


@router.get("/dashboard/quality")
def get_data_quality(request: Request):
    dashboard = request.app.state.dashboard_service
    quality = dashboard.data_quality()
    history = _import_history(request)
    latest_id = quality.latest_import.get("id") if quality.latest_import else None
    latest_row = next((row for row in history if row.get("id") == latest_id), None)
    latest = import_history_item(latest_row).model_dump(mode="json") if latest_row else None
    response = DataQualitySummary(
        accepted_rows=sum(quality.currencies.values()),
        freshness_date=quality.freshness_date,
        covered_start=quality.covered_start,
        covered_end=quality.covered_end,
        currencies=quality.currencies,
        issue_counts=quality.issue_counts,
        incomplete_months=quality.incomplete_months,
        open_reconciliation_cases=quality.open_reconciliation_cases,
        unclassified_transaction_count=quality.unclassified_transaction_count,
        unclassified_absolute_amount=quality.unclassified_absolute_amount,
        source_coverage=quality.source_coverage,
        latest_import=latest,
    )
    return _envelope(response.model_dump(mode="json"), request.state.request_id)


@router.post("/imports/familybiz/previews")
async def preview_familybiz(request: Request):
    file_bytes, filename, _ = await _uploaded_xlsx(request, expected_fields={"file"})
    try:
        result = await run_in_threadpool(
            request.app.state.services.preview_import,
            file_bytes,
            filename,
        )
    except FamilyBizSchemaError as exc:
        raise _map_familybiz_error(request, exc) from None
    response = FamilyBizPreview.model_validate(result.model_dump(mode="python"))
    return _envelope(response.model_dump(mode="json"), request.state.request_id)


@router.post("/imports/familybiz/commits")
async def commit_familybiz(request: Request):
    file_bytes, filename, preview_token = await _uploaded_xlsx(
        request,
        expected_fields={"file", "preview_token"},
    )
    if not preview_token:
        raise _error(
            request,
            422,
            "VALIDATION_ERROR",
            "A preview token is required",
            fields={"preview_token": ["Create a fresh preview before committing."]},
        )
    try:
        result = await run_in_threadpool(
            request.app.state.services.commit_import,
            file_bytes,
            preview_token,
            filename,
        )
    except PreviewStaleError:
        raise _error(
            request,
            409,
            "PREVIEW_STALE",
            "The preview no longer matches the file or current import state; preview again",
        ) from None
    except (FamilyBizSchemaError, ImportValidationError) as exc:
        raise _map_familybiz_error(request, exc) from None
    except ValueError:
        raise _error(
            request,
            409,
            "PREVIEW_STALE",
            "The preview token is invalid or no longer usable; preview again",
        ) from None
    return _envelope(result.model_dump(mode="json"), request.state.request_id)


@router.get("/imports/history")
def get_import_history(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=_MAX_CURSOR_CHARS)] = None,
):
    rows = _import_history(request)
    rows.sort(key=lambda row: (str(row.get("created_at") or ""), str(row.get("id") or "")), reverse=True)
    return _collection_response(
        request,
        route=_HISTORY_CURSOR_ROUTE,
        rows=rows,
        cursor=cursor,
        limit=limit,
        mapper=import_history_item,
    )


@router.get("/reconciliation/cases")
def get_reconciliation_cases(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=_MAX_CURSOR_CHARS)] = None,
):
    rows = request.app.state.services.reconciliation_cases()
    rows.sort(key=lambda row: (str(row.get("created_at") or ""), str(row.get("id") or "")))
    return _collection_response(
        request,
        route=_CASES_CURSOR_ROUTE,
        rows=rows,
        cursor=cursor,
        limit=limit,
        mapper=_reconciliation_case,
    )


@router.post("/reconciliation/cases/{case_id}/resolution")
async def resolve_reconciliation_case(
    case_id: str,
    body: ReconciliationResolutionBody,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
):
    service = request.app.state.services
    database = request.app.state.database
    idempotency = IdempotencyStore(database)
    body_json = body.model_dump(mode="json")

    def operation() -> tuple[int, dict[str, Any]]:
        result = service.resolve_reconciliation(case_id, body_json)
        return 200, result.model_dump(mode="json")

    try:
        result = await run_in_threadpool(
            idempotency.execute,
            actor_id=user.user_id,
            http_method="POST",
            canonical_route=f"/api/v1/reconciliation/cases/{case_id}/resolution",
            idempotency_key=idempotency_key,
            request={"case_id": case_id, **body_json},
            operation=operation,
        )
    except IdempotencyKeyReusedError:
        raise _error(
            request,
            409,
            "IDEMPOTENCY_KEY_REUSED",
            "The idempotency key was already used for a different resolution",
        ) from None
    except ValueError:
        raise _error(
            request,
            409,
            "RECONCILIATION_CONFLICT",
            "The reconciliation case is closed or the selected transaction is no longer a candidate",
        ) from None
    response = JSONResponse(
        _envelope(result.body, request.state.request_id),
        status_code=result.status_code,
    )
    return response
