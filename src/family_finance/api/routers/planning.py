"""Authenticated planning scenario, seed, revision, and comparison routes."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from fastapi import File, Form, Request, UploadFile
from pydantic import ValidationError

from family_finance.api.app import ApiError, authenticated_router
from family_finance.api.audit import record_actor_audit
from family_finance.api.schemas.planning import (
    ArchiveScenarioBody,
    CloneScenarioBody,
    CompareScenariosBody,
    CsvCommitMappings,
    HistorySeedPreviewBody,
    PlanningItemBody,
    PreviewCommitBody,
    ProjectionBody,
    RestoreRevisionBody,
    RevisionBody,
    ScenarioCreateBody,
)
from family_finance.planning import (
    DuplicateSeedError,
    PlanningPreviewStaleError,
    PlanningService,
    PlanningValidationError,
    StaleRevisionError,
)

router = authenticated_router(prefix="/planning")


def _wire(value: Any) -> Any:
    if hasattr(value, "model_dump"):
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


def _service(request: Request) -> PlanningService:
    return request.app.state.services.planning_service


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
                # A CSV source archive is installed before the service writes
                # its linked rows. Flush actor attribution before that effect.
                session.flush()
                result = operation(*args, **kwargs)
    except StaleRevisionError as exc:
        try:
            current = _service(request).get_scenario(str(args[0]))
            current_number = current.current_revision_number
        except PlanningValidationError:
            current_number = None
        fields = {"current_revision_number": [str(current_number)]} if current_number is not None else None
        raise ApiError(
            409,
            "STALE_REVISION",
            f"The scenario changed. Its current revision is {current_number}; reload before saving again."
            if current_number is not None
            else "The scenario changed. Reload before saving again.",
            fields=fields,
        ) from exc
    except DuplicateSeedError as exc:
        fields = {"scenario_id": [exc.scenario_id]} if exc.scenario_id else None
        raise ApiError(409, "DUPLICATE_SEED", str(exc), fields=fields) from exc
    except PlanningPreviewStaleError as exc:
        raise ApiError(409, "PREVIEW_STALE", str(exc)) from exc
    except (PlanningValidationError, ValidationError, ValueError) as exc:
        message = str(exc)
        if "not found" in message.casefold() or "does not exist" in message.casefold():
            raise ApiError(404, "NOT_FOUND", message) from exc
        raise ApiError(422, "VALIDATION_ERROR", message) from exc
    return _envelope(request, result)


def _items(items: list[PlanningItemBody]) -> list[dict[str, Any]]:
    return [item.service_payload() for item in items]


def _require_current_provisional_ack(service: PlanningService, scenario_id: str, acknowledged: bool) -> None:
    revision = service.get_revision(scenario_id)
    if revision.provisional and not acknowledged:
        raise ApiError(
            422,
            "QUALITY_ACKNOWLEDGEMENT_REQUIRED",
            "Review and acknowledge the provisional source before continuing.",
            fields={"acknowledge_provisional": ["Required for this provisional revision"]},
        )


@router.get("/scenarios")
def list_scenarios(request: Request, include_archived: bool = False):
    return _run(request, _service(request).list_scenarios, include_archived=include_archived)


@router.post("/scenarios", status_code=201)
def create_scenario(body: ScenarioCreateBody, request: Request):
    service = _service(request)
    return _run(
        request,
        service.create_manual_scenario,
        body.name,
        body.start_month,
        _items(body.items),
        currency=body.currency,
        notes=body.notes,
        audit=("planning.scenario.create", "planning_scenario"),
    )


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str, request: Request):
    return _run(request, _service(request).get_scenario, scenario_id)


@router.get("/scenarios/{scenario_id}/revisions")
def list_revisions(scenario_id: str, request: Request):
    return _run(request, _service(request).list_revisions, scenario_id)


@router.get("/scenarios/{scenario_id}/revisions/{revision_number}")
def get_revision(scenario_id: str, revision_number: int, request: Request):
    return _run(request, _service(request).get_revision, scenario_id, revision_number)


@router.get("/scenarios/{scenario_id}/projection")
def get_projection(scenario_id: str, request: Request, revision_number: int | None = None):
    return _run(request, _service(request).project_draft, scenario_id, revision_number=revision_number)


@router.post("/scenarios/{scenario_id}/projections")
def project_draft(scenario_id: str, body: ProjectionBody, request: Request):
    service = _service(request)
    return _run(
        request,
        service.project_draft,
        scenario_id,
        _items(body.items),
        revision_number=body.expected_revision_number,
    )


@router.post("/scenarios/{scenario_id}/revisions", status_code=201)
def save_revision(scenario_id: str, body: RevisionBody, request: Request):
    service = _service(request)
    return _run(
        request,
        service.save_revision,
        scenario_id,
        body.expected_revision_number,
        _items(body.items),
        notes=body.notes,
        acknowledge_provisional=body.acknowledge_provisional,
        audit=("planning.revision.create", "planning_scenario"),
    )


@router.post("/scenarios/{scenario_id}/revisions/{revision_number}/restore", status_code=201)
def restore_revision(
    scenario_id: str,
    revision_number: int,
    body: RestoreRevisionBody,
    request: Request,
):
    service = _service(request)
    target = _run(request, service.get_revision, scenario_id, revision_number)["data"]
    if target["provisional"] and not body.acknowledge_provisional:
        raise ApiError(
            422,
            "QUALITY_ACKNOWLEDGEMENT_REQUIRED",
            "Review and acknowledge the provisional source before restoring this revision.",
            fields={"acknowledge_provisional": ["Required for this provisional revision"]},
        )
    return _run(
        request,
        service.restore_revision,
        scenario_id,
        revision_number,
        expected_revision_number=body.expected_revision_number,
        notes=body.notes,
        acknowledge_provisional=body.acknowledge_provisional,
        audit=("planning.revision.restore", "planning_scenario"),
    )


@router.post("/scenarios/{scenario_id}/clone", status_code=201)
def clone_scenario(scenario_id: str, body: CloneScenarioBody, request: Request):
    service = _service(request)
    _require_current_provisional_ack(service, scenario_id, body.acknowledge_provisional)
    return _run(
        request,
        service.clone_scenario,
        scenario_id,
        name=body.name,
        acknowledge_provisional=body.acknowledge_provisional,
        audit=("planning.scenario.clone", "planning_scenario"),
    )


@router.post("/scenarios/{scenario_id}/archive")
def archive_scenario(scenario_id: str, body: ArchiveScenarioBody, request: Request):
    event = "planning.scenario.archive" if body.archived else "planning.scenario.restore"
    return _run(
        request,
        _service(request).archive_scenario,
        scenario_id,
        body.archived,
        audit=(event, "planning_scenario"),
    )


@router.post("/seeds/history/previews")
def preview_history_seed(body: HistorySeedPreviewBody, request: Request):
    return _run(
        request,
        _service(request).preview_history_seed,
        name=body.name,
        currency=body.currency,
        start_month=body.start_month,
        history_months=body.history_months,
    )


@router.post("/seeds/history/commits", status_code=201)
def commit_history_seed(body: PreviewCommitBody, request: Request):
    service = _service(request)
    try:
        payload = service._decode_token(body.preview_token)
    except PlanningValidationError as exc:
        raise ApiError(409, "PREVIEW_STALE", "The historical preview expired. Preview the source again.") from exc
    if payload.get("baseline_batch_id") != service.database.latest_committed_batch_id():
        raise ApiError(409, "PREVIEW_STALE", "Imported history changed after preview; create a new preview.")
    if payload.get("provisional") and not body.acknowledge_provisional:
        raise ApiError(
            422,
            "QUALITY_ACKNOWLEDGEMENT_REQUIRED",
            "Review and acknowledge the incomplete historical months before committing.",
            fields={"acknowledge_provisional": ["Required for this provisional seed"]},
        )
    return _run(
        request,
        service.commit_history_seed,
        body.preview_token,
        acknowledge_provisional=body.acknowledge_provisional,
        audit=("planning.seed.history.commit", "planning_scenario"),
    )


@router.post("/seeds/csv/previews")
def preview_csv_seed(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    name: str | None = Form(default=None, max_length=200),
    currency: str = Form(default="ILS", max_length=12),
    start_month: str | None = Form(default=None, max_length=10),
):
    service = _service(request)
    contents = file.file.read()
    return _run(
        request,
        service.preview_csv_seed,
        contents,
        file.filename,
        name=name,
        currency=currency,
        start_month=start_month,
    )


@router.post("/seeds/csv/commits", status_code=201)
def commit_csv_seed(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    preview_token: str = Form(..., min_length=1, max_length=1_000_000),
    mappings_json: str = Form(default="{}", max_length=256_000),
    acknowledge_provisional: bool = Form(default=False),
):
    service = _service(request)
    contents = file.file.read()
    try:
        parsed_mappings = CsvCommitMappings.model_validate(json.loads(mappings_json))
        parsed = service.csv_parser.parse(contents, filename=file.filename)
    except (json.JSONDecodeError, ValidationError, PlanningValidationError) as exc:
        raise ApiError(422, "VALIDATION_ERROR", "Review the CSV mappings and upload a valid planning file.") from exc
    categories = {str(entry["category"]) for entry in parsed["expenses"]}
    mappings = parsed_mappings.mappings
    mapped_categories = [mapping.csv_category for mapping in mappings]
    if len(set(mapped_categories)) != len(mapped_categories) or set(mapped_categories) != categories:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "Confirm a category mapping or explicitly leave it unmapped for every CSV expense category.",
            fields={"mappings": ["Every source category must appear exactly once"]},
        )
    mapping_values = {
        mapping.csv_category: mapping.analysis_category
        for mapping in mappings
        if mapping.analysis_category is not None
    }
    has_unmapped = any(mapping.analysis_category is None for mapping in mappings)
    try:
        payload = service._decode_token(preview_token)
    except PlanningValidationError as exc:
        raise ApiError(409, "PREVIEW_STALE", "The CSV preview expired. Preview the file again.") from exc
    if (
        payload.get("origin") != "csv"
        or payload.get("sha256") != parsed["sha256"]
        or payload.get("parser_version") != service.settings.planning_parser_version
    ):
        raise ApiError(409, "PREVIEW_STALE", "The CSV or parser changed after preview; preview the file again.")
    if (payload.get("provisional") or has_unmapped) and not acknowledge_provisional:
        raise ApiError(
            422,
            "QUALITY_ACKNOWLEDGEMENT_REQUIRED",
            "Review and acknowledge CSV control gaps or unmapped categories before committing.",
            fields={"acknowledge_provisional": ["Required for this provisional seed"]},
        )
    return _run(
        request,
        service.commit_csv_seed,
        contents,
        preview_token,
        mappings=mapping_values,
        acknowledge_provisional=acknowledge_provisional,
        audit=("planning.seed.csv.commit", "planning_scenario"),
    )


@router.get("/categories")
def get_categories(request: Request, currency: str = "ILS"):
    return _run(request, _service(request).analysis_categories, currency)


@router.get("/suggested-start-month")
def suggested_start_month(request: Request, currency: str = "ILS"):
    return _run(request, _service(request).suggested_start_month, currency)


@router.post("/comparisons")
def compare_scenarios(body: CompareScenariosBody, request: Request):
    return _run(request, _service(request).compare_scenarios, body.scenario_ids)


@router.get("/scenarios/{scenario_id}/actual-comparison")
def compare_actual(scenario_id: str, request: Request, revision_number: int | None = None):
    return _run(request, _service(request).compare_actual, scenario_id, revision_number=revision_number)
