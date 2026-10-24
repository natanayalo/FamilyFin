"""Authenticated API for apartment studies and immutable revisions."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from fastapi import Request
from pydantic import BaseModel, ValidationError

from family_finance.api.app import ApiError, authenticated_router
from family_finance.api.audit import record_actor_audit
from family_finance.api.schemas.apartment import (
    ApartmentArchiveBody,
    ApartmentCloneBody,
    ApartmentCreateBody,
    ApartmentPreviewBody,
    ApartmentRestoreBody,
    ApartmentRevisionBody,
)
from family_finance.apartment import ApartmentValidationError, StaleApartmentRevisionError
from family_finance.models import PlanningItemKind

router = authenticated_router(prefix="/apartment")


def _wire(value: Any) -> Any:
    """Serialize apartment responses without converting Decimal through float."""

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
    return request.app.state.services.apartment_planning_service


def _domain_inputs(body):
    try:
        return body.domain_inputs()
    except (ValidationError, ValueError) as exc:
        raise ApiError(422, "VALIDATION_ERROR", "Apartment assumptions failed validation") from exc


def _run(
    request: Request,
    operation,
    *args,
    audit: tuple[str, str] | None = None,
    stale_study_id: str | None = None,
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
    except StaleApartmentRevisionError as exc:
        current_number = None
        if stale_study_id:
            try:
                current_number = _service(request).get_study(stale_study_id).current_revision_number
            except ApartmentValidationError:
                pass
        fields = {"current_revision_number": [str(current_number)]} if current_number is not None else None
        raise ApiError(
            409,
            "STALE_REVISION",
            "The apartment study changed. Reload its current revision before saving again.",
            fields=fields,
        ) from exc
    except (ApartmentValidationError, ValidationError, ValueError) as exc:
        message = str(exc)
        normalized = message.casefold()
        if "not found" in normalized:
            raise ApiError(404, "NOT_FOUND", "The requested apartment study or pinned source was not found") from exc
        if "acknowledg" in normalized or "confirm" in normalized:
            raise ApiError(
                422,
                "QUALITY_ACKNOWLEDGEMENT_REQUIRED",
                "Review and confirm every alternative and acknowledge inherited provisional source issues before saving.",
            ) from exc
        raise ApiError(422, "VALIDATION_ERROR", "Apartment data failed validation") from exc
    return _envelope(request, result)


def _source_verification(service, forecast_id: str, forecast_revision_number: int) -> dict[str, Any]:
    forecast = service.forecasting.get_forecast(forecast_id)
    pinned_forecast = service.forecasting.get_revision(forecast_id, forecast_revision_number)
    pinned_plan = service.planning.get_revision(forecast.scenario_id, pinned_forecast.source_revision_number)
    scenario = service.planning.get_scenario(forecast.scenario_id)
    current_plan = service.planning.get_revision(forecast.scenario_id, scenario.current_revision_number)

    def state(revision):
        return {
            "scenario_id": forecast.scenario_id,
            "revision_id": revision.revision_id,
            "revision_number": revision.revision_number,
            "provisional": revision.provisional,
            "issue_codes": revision.issue_codes,
        }

    return {"at_creation": state(pinned_plan), "current": state(current_plan)}


def _project_saved_revision(service, study_id: str, revision_number: int):
    snapshot = service.get_revision(study_id, revision_number)
    draft = service.project_draft(
        snapshot.forecast_id,
        snapshot.alternatives,
        forecast_revision_number=snapshot.forecast_revision_number,
        guardrails=snapshot.guardrails,
        source_quality_acknowledged=snapshot.source_quality_acknowledged,
        notes=snapshot.notes,
    )
    return {
        "snapshot": snapshot,
        "draft": draft,
        "source_verification": _source_verification(
            service, snapshot.forecast_id, snapshot.forecast_revision_number
        ),
    }


@router.get("/options")
def get_options(request: Request, forecast_id: str, forecast_revision_number: int):
    """Return exact pinned source metadata and choices for one forecast revision."""

    service = _service(request)

    def load():
        forecast = service.forecasting.get_forecast(forecast_id)
        snapshot = service.forecasting.get_revision(forecast_id, forecast_revision_number)
        plan = service.planning.get_revision(forecast.scenario_id, snapshot.source_revision_number)
        verification = _source_verification(service, forecast_id, forecast_revision_number)
        return {
            "forecast": forecast,
            "forecast_revision": snapshot,
            "planning_source": verification,
            "expense_lines": [
                item for item in plan.items if item.kind == PlanningItemKind.EXPENSE
            ],
        }

    return _run(request, load)


@router.get("/pool-balances")
def get_pool_balances(
    request: Request,
    forecast_id: str,
    forecast_revision_number: int,
    forecast_role: str,
    purchase_month: int,
):
    service = _service(request)
    balances = _run(
        request,
        service.available_pool_balances,
        forecast_id,
        forecast_role,
        purchase_month,
        forecast_revision_number=forecast_revision_number,
    )
    return balances


@router.get("/studies")
def list_studies(request: Request, include_archived: bool = False):
    return _run(request, _service(request).list_studies, include_archived=include_archived)


@router.post("/previews")
def preview_study(body: ApartmentPreviewBody, request: Request):
    guardrails, alternatives = _domain_inputs(body)
    return _run(
        request,
        _service(request).project_draft,
        body.forecast_id,
        alternatives,
        forecast_revision_number=body.forecast_revision_number,
        guardrails=guardrails,
        source_quality_acknowledged=body.source_quality_acknowledged,
        notes=body.notes,
    )


@router.post("/studies", status_code=201)
def create_study(body: ApartmentCreateBody, request: Request):
    guardrails, alternatives = _domain_inputs(body)
    return _run(
        request,
        _service(request).create_study,
        body.name,
        body.forecast_id,
        alternatives,
        forecast_revision_number=body.forecast_revision_number,
        guardrails=guardrails,
        notes=body.notes,
        source_quality_acknowledged=body.source_quality_acknowledged,
        audit=("apartment_study.create", "apartment_study"),
    )


@router.get("/studies/{study_id}")
def get_study(study_id: str, request: Request):
    return _run(request, _service(request).get_study, study_id)


@router.get("/studies/{study_id}/revisions")
def list_revisions(study_id: str, request: Request):
    return _run(request, _service(request).list_revisions, study_id)


@router.get("/studies/{study_id}/revisions/{revision_number}")
def get_revision(study_id: str, revision_number: int, request: Request):
    return _run(request, _service(request).get_revision, study_id, revision_number)


@router.get("/studies/{study_id}/revisions/{revision_number}/projection")
def project_revision(study_id: str, revision_number: int, request: Request):
    return _run(request, _project_saved_revision, _service(request), study_id, revision_number)


@router.post("/studies/{study_id}/revisions", status_code=201)
def save_revision(study_id: str, body: ApartmentRevisionBody, request: Request):
    guardrails, alternatives = _domain_inputs(body)
    return _run(
        request,
        _service(request).save_revision,
        study_id,
        expected_revision_number=body.expected_revision_number,
        alternatives=alternatives,
        guardrails=guardrails,
        notes=body.notes,
        source_quality_acknowledged=body.source_quality_acknowledged,
        audit=("apartment_study.revision.create", "apartment_study"),
        stale_study_id=study_id,
    )


@router.post("/studies/{study_id}/revisions/{revision_number}/restore", status_code=201)
def restore_revision(
    study_id: str,
    revision_number: int,
    body: ApartmentRestoreBody,
    request: Request,
):
    return _run(
        request,
        _service(request).restore_revision,
        study_id,
        revision_number,
        expected_revision_number=body.expected_revision_number,
        notes=body.notes,
        source_quality_acknowledged=body.source_quality_acknowledged,
        audit=("apartment_study.revision.restore", "apartment_study"),
        stale_study_id=study_id,
    )


@router.post("/studies/{study_id}/clone", status_code=201)
def clone_study(study_id: str, body: ApartmentCloneBody, request: Request):
    return _run(
        request,
        _service(request).clone_study,
        study_id,
        name=body.name,
        audit=("apartment_study.clone", "apartment_study"),
    )


@router.post("/studies/{study_id}/archive")
def set_study_archived(study_id: str, body: ApartmentArchiveBody, request: Request):
    return _run(
        request,
        _service(request).archive_study,
        study_id,
        body.archived,
        audit=("apartment_study.archive", "apartment_study"),
    )
