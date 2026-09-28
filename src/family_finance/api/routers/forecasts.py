"""Authenticated API for immutable savings forecast revisions."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from fastapi import Request
from pydantic import BaseModel, ValidationError

from family_finance.api.app import ApiError, authenticated_router
from family_finance.api.audit import record_actor_audit
from family_finance.api.schemas.forecasts import (
    ForecastArchiveBody,
    ForecastCloneBody,
    ForecastCreateBody,
    ForecastDraftBody,
    ForecastNetWorthSeedsBody,
    ForecastRestoreBody,
    ForecastRevisionBody,
)
from family_finance.forecasting import ForecastValidationError, StaleForecastRevisionError
from family_finance.net_worth import NetWorthValidationError

router = authenticated_router(prefix="/forecasts")


def _wire(value: Any) -> Any:
    """Serialize forecasts without converting Decimal values through float."""

    if isinstance(value, BaseModel):
        return _wire(value.model_dump(mode="python"))
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


def _service(request: Request):
    return request.app.state.services.savings_forecast_service


def _run(
    request: Request,
    operation,
    *args,
    audit: tuple[str, str] | None = None,
    **kwargs,
):
    try:
        if audit is None:
            result = operation(*args, **kwargs)
        else:
            actor = request.state.authenticated_user
            with request.app.state.database.api_write_unit_of_work() as session:
                record_actor_audit(
                    session,
                    actor_id=actor.user_id,
                    event_type=audit[0],
                    target_type=audit[1],
                    request_id=request.state.request_id,
                )
                session.flush()
                result = operation(*args, **kwargs)
    except StaleForecastRevisionError as exc:
        current_number = None
        try:
            if args:
                current_number = _service(request).get_forecast(str(args[0])).current_revision_number
        except ForecastValidationError:
            pass
        fields = {"current_revision_number": [str(current_number)]} if current_number is not None else None
        raise ApiError(
            409,
            "STALE_REVISION",
            "The forecast changed. Reload the current revision before saving again.",
            fields=fields,
        ) from exc
    except (ForecastValidationError, NetWorthValidationError, ValidationError, ValueError) as exc:
        message = str(exc)
        normalized = message.casefold()
        if "not found" in normalized:
            raise ApiError(404, "NOT_FOUND", "The requested forecast source or revision was not found") from exc
        if "acknowledg" in normalized or "confirm" in normalized:
            raise ApiError(
                422,
                "QUALITY_ACKNOWLEDGEMENT_REQUIRED",
                "Review and acknowledge the provisional plan or stale source balances before saving.",
            ) from exc
        raise ApiError(422, "VALIDATION_ERROR", "Forecast data failed validation") from exc
    return _envelope(request, result)


def _source_verification(service, scenario_id: str, pinned_revision_number: int) -> dict[str, Any]:
    pinned = service.planning.get_revision(scenario_id, pinned_revision_number)
    scenario = service.planning.get_scenario(scenario_id)
    current = service.planning.get_revision(scenario_id, scenario.current_revision_number)

    def state(revision):
        return {
            "scenario_id": scenario_id,
            "revision_id": revision.revision_id,
            "revision_number": revision.revision_number,
            "provisional": revision.provisional,
            "issue_codes": revision.issue_codes,
        }

    return {"at_creation": state(pinned), "current": state(current)}


def _domain_inputs(body):
    try:
        return body.domain_inputs()
    except (ValidationError, ValueError) as exc:
        raise ApiError(422, "VALIDATION_ERROR", "Forecast assumptions failed validation") from exc


def _project_saved_revision(service, forecast_id: str, revision_number: int):
    forecast = service.get_forecast(forecast_id)
    snapshot = service.get_revision(forecast_id, revision_number)
    draft = service.project_draft(
        snapshot.scenario_id,
        snapshot.starting_pools,
        snapshot.cases,
        source_revision_number=snapshot.source_revision_number,
        forecast_id=forecast_id,
        notes=snapshot.notes,
        provisional_acknowledged=snapshot.provisional_acknowledged,
    )
    return {
        "snapshot": snapshot,
        "draft": draft,
        "source_verification": _source_verification(
            service, forecast.scenario_id, snapshot.source_revision_number
        ),
    }


@router.get("")
def list_forecasts(request: Request, include_archived: bool = False):
    return _run(request, _service(request).list_forecasts, include_archived=include_archived)


@router.post("/previews")
def project_forecast(body: ForecastDraftBody, request: Request):
    service = _service(request)
    pools, cases = _domain_inputs(body)
    draft = _run(
        request,
        service.project_draft,
        body.scenario_id,
        pools,
        cases,
        source_revision_number=body.source_revision_number,
        forecast_id=body.forecast_id,
        notes=body.notes,
        provisional_acknowledged=body.provisional_acknowledged,
    )
    verification = _source_verification(service, body.scenario_id, body.source_revision_number)
    data = draft["data"]
    data["source_verification"] = _wire(verification)
    return draft


@router.post("/net-worth-seeds")
def seed_pools_from_net_worth(body: ForecastNetWorthSeedsBody, request: Request):
    return _run(
        request,
        request.app.state.services.net_worth_service.create_forecast_pool_seeds,
        body.snapshot_revision_id,
        body.account_keys,
        body.pool_types,
    )


@router.post("", status_code=201)
def create_forecast(body: ForecastCreateBody, request: Request):
    pools, cases = _domain_inputs(body)
    return _run(
        request,
        _service(request).create_forecast,
        body.name,
        body.scenario_id,
        pools,
        cases,
        source_revision_number=body.source_revision_number,
        notes=body.notes,
        provisional_acknowledged=body.provisional_acknowledged,
        audit=("savings_forecast.create", "savings_forecast"),
    )


@router.get("/{forecast_id}")
def get_forecast(forecast_id: str, request: Request):
    return _run(request, _service(request).get_forecast, forecast_id)


@router.get("/{forecast_id}/revisions")
def list_revisions(forecast_id: str, request: Request):
    return _run(request, _service(request).list_revisions, forecast_id)


@router.get("/{forecast_id}/revisions/{revision_number}")
def get_revision(forecast_id: str, revision_number: int, request: Request):
    return _run(request, _service(request).get_revision, forecast_id, revision_number)


@router.get("/{forecast_id}/revisions/{revision_number}/projection")
def project_revision(forecast_id: str, revision_number: int, request: Request):
    return _run(request, _project_saved_revision, _service(request), forecast_id, revision_number)


@router.post("/{forecast_id}/revisions", status_code=201)
def save_revision(forecast_id: str, body: ForecastRevisionBody, request: Request):
    pools, cases = _domain_inputs(body)
    return _run(
        request,
        _service(request).save_revision,
        forecast_id,
        expected_revision_number=body.expected_revision_number,
        starting_pools=pools,
        cases=cases,
        notes=body.notes,
        provisional_acknowledged=body.provisional_acknowledged,
        audit=("savings_forecast.revision.create", "savings_forecast"),
    )


@router.post("/{forecast_id}/revisions/{revision_number}/restore", status_code=201)
def restore_revision(
    forecast_id: str,
    revision_number: int,
    body: ForecastRestoreBody,
    request: Request,
):
    return _run(
        request,
        _service(request).restore_revision,
        forecast_id,
        revision_number,
        expected_revision_number=body.expected_revision_number,
        notes=body.notes,
        provisional_acknowledged=body.provisional_acknowledged,
        audit=("savings_forecast.revision.restore", "savings_forecast"),
    )


@router.post("/{forecast_id}/clone", status_code=201)
def clone_forecast(forecast_id: str, body: ForecastCloneBody, request: Request):
    return _run(
        request,
        _service(request).clone_forecast,
        forecast_id,
        name=body.name,
        audit=("savings_forecast.clone", "savings_forecast"),
    )


@router.post("/{forecast_id}/archive")
def set_forecast_archived(forecast_id: str, body: ForecastArchiveBody, request: Request):
    return _run(
        request,
        _service(request).archive_forecast,
        forecast_id,
        body.archived,
        audit=("savings_forecast.archive", "savings_forecast"),
    )
