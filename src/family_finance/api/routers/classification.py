"""Authenticated classification review, coverage, and reusable-rule routes."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Body, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from family_finance.api.app import ApiError, authenticated_router, current_user
from family_finance.api.audit import record_actor_audit
from family_finance.api.auth import AuthenticatedUser
from family_finance.api.idempotency import canonical_json
from family_finance.api.schemas.classification import (
    ClearOverrideBody,
    OverrideBody,
    ReviewQueueItem,
    RuleCreateBody,
    RuleDisableBody,
    RuleFields,
)
from family_finance.classification import ClassificationService
from family_finance.models import (
    ClassificationResult,
    ClassificationRule,
    ClassificationSource,
    EconomicClass,
)

router = authenticated_router(prefix="/classification")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_PAGE_SIZE_DEFAULT = 50
_PAGE_SIZE_MAX = 200


def _service(request: Request) -> ClassificationService:
    # ClassificationService memoizes rows for normal UI/CLI sessions. The API
    # serves concurrent requests, so use a request-scoped instance and never
    # expose a shared cache across a read and an immediate write transaction.
    return ClassificationService(request.app.state.database)


def _envelope(request: Request, data: Any, *, next_cursor: str | None = None, limit: int | None = None):
    meta: dict[str, Any] = {"request_id": request.state.request_id}
    if limit is not None:
        meta["limit"] = limit
        meta["next_cursor"] = next_cursor
    return {"data": jsonable_encoder(data), "meta": meta}


def _month_bounds(value: str | None) -> tuple[date | None, date | None]:
    if value is None:
        return None, None
    if not _MONTH_RE.fullmatch(value):
        raise ApiError(422, "VALIDATION_ERROR", "Month must use YYYY-MM format")
    try:
        start = date.fromisoformat(f"{value}-01")
    except ValueError:
        raise ApiError(422, "VALIDATION_ERROR", "Month must be a valid calendar month") from None
    end = date(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1)
    return start, end


def _override_version(service: ClassificationService, transaction_id: int) -> int:
    latest = service.repository.latest_overrides(transaction_id)
    return max((int(item["id"]) for item in latest), default=0)


def _classification_state(result: ClassificationResult, override_version: int) -> str:
    value = {
        "override_version": override_version,
        "classification": result.model_dump(mode="json"),
    }
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _page_fingerprint(scope: str, filters: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json({"scope": scope, "filters": filters}).encode("utf-8")).hexdigest()


def _decode_cursor(cursor: str | None, *, fingerprint: str) -> int:
    if not cursor:
        return 0
    try:
        decoded = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(decoded)
        offset = payload["offset"]
        if payload.get("fingerprint") != fingerprint or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError
        return offset
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        raise ApiError(422, "INVALID_CURSOR", "The collection cursor is invalid or no longer matches these filters") from None


def _encode_cursor(offset: int, *, fingerprint: str) -> str:
    raw = canonical_json({"offset": offset, "fingerprint": fingerprint}).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _slice_page(items: list[Any], *, cursor: str | None, limit: int, scope: str, filters: dict[str, Any]):
    fingerprint = _page_fingerprint(scope, filters)
    offset = _decode_cursor(cursor, fingerprint=fingerprint)
    page = items[offset : offset + limit]
    next_cursor = _encode_cursor(offset + limit, fingerprint=fingerprint) if offset + limit < len(items) else None
    return page, next_cursor


def _current_rule_id(service: ClassificationService, fields: dict[str, Any]) -> int | None:
    key = (
        str(fields["account_kind"]).casefold(),
        str(fields["direction"]),
        str(fields["source_category"]),
        str(fields.get("source_movement_type") or ""),
        str(fields["currency"]).upper(),
    )
    current = next(
        (
            row
            for row in service.list_rules()
            if row["is_current"]
            and (
                str(row["account_kind"]).casefold(),
                str(row["direction"]),
                str(row["source_category"]),
                str(row.get("source_movement_type") or ""),
                str(row["currency"]).upper(),
            )
            == key
        ),
        None,
    )
    return int(current["id"]) if current else None


def _not_found_or_invalid(exc: ValueError) -> ApiError:
    message = str(exc)
    if "not found" in message.casefold():
        return ApiError(404, "CLASSIFICATION_NOT_FOUND", "The transaction or rule was not found")
    return ApiError(422, "CLASSIFICATION_INVALID", "The classification decision was rejected")


@router.get("/review-queue")
def review_queue(
    request: Request,
    month: Annotated[str | None, Query(max_length=7)] = None,
    account_kind: Annotated[str | None, Query(max_length=64)] = None,
    currency: Annotated[str | None, Query(max_length=8)] = None,
    issue: Annotated[str | None, Query(max_length=100)] = None,
    economic_class: EconomicClass | None = None,
    classification_source: ClassificationSource | None = None,
    include_resolved: bool = False,
    limit: Annotated[int, Query(ge=1, le=_PAGE_SIZE_MAX)] = _PAGE_SIZE_DEFAULT,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
):
    month_start, _ = _month_bounds(month)
    service = _service(request)
    service.invalidate_cache()
    filters = {
        "month": month,
        "account_kind": account_kind,
        "currency": currency,
        "issue": issue,
        "economic_class": economic_class.value if economic_class else None,
        "classification_source": classification_source.value if classification_source else None,
        "include_resolved": include_resolved,
    }
    items = service.review_queue(
        month=month_start,
        account_kind=account_kind,
        currency=currency,
        issue=issue,
        economic_class=economic_class,
        classification_source=classification_source,
        include_resolved=include_resolved,
    )
    page, next_cursor = _slice_page(
        items, cursor=cursor, limit=limit, scope="review-queue", filters=filters
    )
    rows = []
    for item in page:
        # The queue query and version reads are separate service calls. Check
        # the override version on both sides of a fresh classification read so
        # the displayed result and its conditional token agree.
        for _attempt in range(3):
            version_before = _override_version(service, item.transaction_id)
            service.invalidate_cache()
            effective = service.classify_one(item.transaction_id)
            version_after = _override_version(service, item.transaction_id)
            if version_before == version_after:
                break
        else:
            raise ApiError(409, "STALE_CLASSIFICATION", "Classification changed while loading this page. Reload the queue.")
        if not _matches_review_filters(
            effective,
            month=month_start,
            account_kind=account_kind,
            currency=currency,
            issue=issue,
            economic_class=economic_class,
            classification_source=classification_source,
            include_resolved=include_resolved,
        ):
            continue
        rows.append(
            ReviewQueueItem(
                **item.model_dump(exclude={"effective_classification"}),
                effective_classification=effective,
                expected_override_version=version_after,
                expected_classification_state=_classification_state(effective, version_after),
            ).model_dump(mode="json")
        )
    return _envelope(request, rows, next_cursor=next_cursor, limit=limit)


def _matches_review_filters(
    result: ClassificationResult,
    *,
    month: date | None,
    account_kind: str | None,
    currency: str | None,
    issue: str | None,
    economic_class: EconomicClass | None,
    classification_source: ClassificationSource | None,
    include_resolved: bool,
) -> bool:
    if not include_resolved and result.economic_class != EconomicClass.UNCLASSIFIED and not issue:
        return False
    if month and result.booking_date.replace(day=1) != month.replace(day=1):
        return False
    if account_kind and " ".join(result.account_kind.casefold().split()) != " ".join(account_kind.casefold().split()):
        return False
    if currency and result.currency.upper() != currency.upper():
        return False
    if economic_class and result.economic_class != economic_class:
        return False
    if classification_source and result.source != classification_source:
        return False
    return not issue or any(issue.casefold() in item.code.casefold() for item in result.issues)


@router.get("/coverage")
def classification_coverage(
    request: Request,
    month: Annotated[str | None, Query(max_length=7)] = None,
    currency: Annotated[str | None, Query(max_length=8)] = None,
):
    start, end = _month_bounds(month)
    service = _service(request)
    service.invalidate_cache()
    results = service.classify_many(currency=currency, start=start, end=end)
    by_class = Counter(item.economic_class.value for item in results)
    by_source = Counter(item.source.value for item in results)
    issues = Counter(issue.code for item in results for issue in item.issues)
    total = len(results)
    unclassified = by_class.get(EconomicClass.UNCLASSIFIED.value, 0)
    classified = total - unclassified
    review_required = sum(item.is_review_required for item in results)
    return _envelope(
        request,
        {
            "month": month,
            "currency": currency.upper() if currency else None,
            "total_accepted": total,
            "classified_count": classified,
            "unclassified_count": unclassified,
            "review_required_count": review_required,
            "classification_coverage_percent": (
                format((Decimal(classified) * Decimal(100) / Decimal(total)).quantize(Decimal("0.1")), "f")
                if total
                else None
            ),
            "by_economic_class": {value.value: by_class.get(value.value, 0) for value in EconomicClass},
            "by_source": {value.value: by_source.get(value.value, 0) for value in ClassificationSource},
            "issue_counts": dict(sorted(issues.items())),
        },
    )


@router.post("/transactions/{transaction_id}/override")
def save_override(
    transaction_id: int,
    body: OverrideBody,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
):
    fields = body.decision_fields()
    if not fields:
        raise ApiError(422, "VALIDATION_ERROR", "At least one override value is required")
    service = _service(request)
    database = request.app.state.database
    try:
        with database.api_write_unit_of_work() as session:
            service.invalidate_cache()
            current = service.classify_one(transaction_id)
            current_version = _override_version(service, transaction_id)
            current_state = _classification_state(current, current_version)
            if current_version != body.expected_override_version or current_state != body.expected_classification_state:
                raise ApiError(409, "STALE_CLASSIFICATION", "This transaction changed after it was loaded. Reload before saving.")
            result = service.save_override(transaction_id, **fields, reason=body.reason)
            new_version = _override_version(service, transaction_id)
            record_actor_audit(
                session,
                actor_id=user.user_id,
                event_type="classification.override_saved",
                request_id=request.state.request_id,
                target_type="transaction",
            )
    except ValueError as exc:
        raise _not_found_or_invalid(exc) from None
    return _envelope(request, {
        "result": result.model_dump(mode="json"),
        "override_version": new_version,
        "expected_classification_state": _classification_state(result, new_version),
    })


@router.delete("/transactions/{transaction_id}/override")
def clear_override(
    transaction_id: int,
    request: Request,
    body: Annotated[ClearOverrideBody, Body()],
    user: Annotated[AuthenticatedUser, Depends(current_user)],
):
    service = _service(request)
    database = request.app.state.database
    try:
        with database.api_write_unit_of_work() as session:
            service.invalidate_cache()
            current = service.classify_one(transaction_id)
            current_version = _override_version(service, transaction_id)
            current_state = _classification_state(current, current_version)
            if current_version != body.expected_override_version or current_state != body.expected_classification_state:
                raise ApiError(409, "STALE_CLASSIFICATION", "This transaction changed after it was loaded. Reload before clearing.")
            result = service.clear_override(transaction_id, body.fields, reason=body.reason)
            new_version = _override_version(service, transaction_id)
            record_actor_audit(
                session,
                actor_id=user.user_id,
                event_type="classification.override_cleared",
                request_id=request.state.request_id,
                target_type="transaction",
            )
    except ValueError as exc:
        raise _not_found_or_invalid(exc) from None
    return _envelope(request, {
        "result": result.model_dump(mode="json"),
        "override_version": new_version,
        "expected_classification_state": _classification_state(result, new_version),
    })


@router.get("/rules")
def list_rules(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=_PAGE_SIZE_MAX)] = _PAGE_SIZE_DEFAULT,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
):
    rules = _service(request).list_rules()
    page, next_cursor = _slice_page(
        rules, cursor=cursor, limit=limit, scope="rules", filters={}
    )
    return _envelope(request, page, next_cursor=next_cursor, limit=limit)


@router.post("/rules/previews")
def preview_rule(body: RuleFields, request: Request):
    service = _service(request)
    try:
        preview = service.preview_rule(body.service_payload())
    except (ValueError, ValidationError):
        raise ApiError(422, "CLASSIFICATION_INVALID", "The reusable rule was rejected") from None
    rule = preview["rule"]
    fields = body.service_payload()
    return _envelope(
        request,
        {
            "count": int(preview["count"]),
            "rule": rule.model_dump(mode="json"),
            "expected_current_rule_id": _current_rule_id(service, fields),
        },
    )


@router.post("/rules", status_code=201)
def create_rule(
    body: RuleCreateBody,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
):
    service = _service(request)
    database = request.app.state.database
    values = body.service_payload()
    try:
        with database.api_write_unit_of_work() as session:
            current_id = _current_rule_id(service, values)
            if current_id != body.expected_current_rule_id:
                raise ApiError(409, "STALE_RULE", "The exact-match rule changed after preview. Preview again before creating.")
            rule = service.create_rule(values)
            service.invalidate_cache()
            record_actor_audit(
                session,
                actor_id=user.user_id,
                event_type="classification.rule_created",
                request_id=request.state.request_id,
                target_type="classification_rule",
            )
    except (ValueError, ValidationError) as exc:
        raise _not_found_or_invalid(exc) from None
    return _envelope(request, ClassificationRule.model_validate(rule.__dict__).model_dump(mode="json"))


@router.post("/rules/{rule_id}/disable")
def disable_rule(
    rule_id: int,
    body: RuleDisableBody,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
):
    service = _service(request)
    database = request.app.state.database
    try:
        with database.api_write_unit_of_work() as session:
            current = next((row for row in service.list_rules() if int(row["id"]) == rule_id), None)
            if (
                current is None
                or not current["is_current"]
                or int(current["id"]) != body.expected_current_rule_id
                or not current["effective_active"]
            ):
                raise ApiError(409, "STALE_RULE", "Only the current active rule revision can be disabled. Reload rule history.")
            rule = service.disable_rule(rule_id, reason=body.reason)
            service.invalidate_cache()
            record_actor_audit(
                session,
                actor_id=user.user_id,
                event_type="classification.rule_disabled",
                request_id=request.state.request_id,
                target_type="classification_rule",
            )
    except (ValueError, ValidationError) as exc:
        raise _not_found_or_invalid(exc) from None
    return _envelope(request, ClassificationRule.model_validate(rule.__dict__).model_dump(mode="json"))


__all__ = ["router"]
