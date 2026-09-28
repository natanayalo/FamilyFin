"""Authenticated insight preferences, saved results, and review controls."""

from __future__ import annotations

import json
from datetime import date
from typing import Literal

from fastapi import Query, Request

from family_finance.api.app import ApiError, _envelope, authenticated_router
from family_finance.api.audit import record_actor_audit
from family_finance.api.schemas.operations import InsightPreferencesBody
from family_finance.persistence.models import MonthlySummaryRevisionRow

router = authenticated_router(prefix="/insights")


def _service(request: Request):
    return request.app.state.services.insights_service


def _record_review_event(request: Request, event_type: str, target_type: str) -> None:
    actor = request.state.authenticated_user
    with request.app.state.database.api_write_unit_of_work() as session:
        record_actor_audit(
            session,
            actor_id=actor.user_id,
            event_type=event_type,
            target_type=target_type,
            request_id=request.state.request_id,
        )


@router.get("/preferences")
def get_preferences(request: Request):
    value = _service(request).get_preferences()
    return _envelope(value.model_dump(mode="json"), request.state.request_id)


@router.get("/preferences/options")
def get_preference_options(request: Request):
    services = request.app.state.services
    scenarios = services.planning_service.list_scenarios()[:100]
    forecasts = services.savings_forecast_service.list_forecasts()[:100]
    studies = services.apartment_planning_service.list_studies()[:100]
    return _envelope(
        {
            "planning_scenarios": [
                {"id": item.scenario_id, "name": item.name, "currency": item.currency,
                 "revision_number": item.current_revision_number}
                for item in scenarios
            ],
            "forecasts": [
                {"id": item.forecast_id, "name": item.name, "currency": item.currency,
                 "revision_number": item.current_revision_number}
                for item in forecasts
            ],
            "apartment_studies": [
                {"id": item.study_id, "name": item.name, "currency": item.currency,
                 "revision_number": item.current_revision_number}
                for item in studies
            ],
        },
        request.state.request_id,
    )


@router.put("/preferences")
def save_preferences(body: InsightPreferencesBody, request: Request):
    try:
        with request.app.state.database.api_write_unit_of_work() as session:
            record_actor_audit(
                session,
                actor_id=request.state.authenticated_user.user_id,
                event_type="insights.preferences.update",
                target_type="insight_preferences",
                request_id=request.state.request_id,
            )
            value = _service(request).save_preferences(body.model_dump(mode="python"))
    except (TypeError, ValueError) as exc:
        raise ApiError(422, "INVALID_PREFERENCES", "The selected insight preferences are not valid") from exc
    return _envelope(value.model_dump(mode="json"), request.state.request_id)


@router.get("/alerts")
def list_alerts(
    request: Request,
    state: Literal["open", "acknowledged", "resolved"] | None = None,
    limit: int = Query(default=100, ge=1, le=200),
):
    rows = _service(request).list_alerts(state=state)[:limit]
    return _envelope(
        {"items": [item.model_dump(mode="json") for item in rows]},
        request.state.request_id,
    )


def _transition(request: Request, alert_id: str, action: str):
    operation = (
        _service(request).acknowledge_alert if action == "acknowledge"
        else _service(request).resolve_alert
    )
    try:
        with request.app.state.database.api_write_unit_of_work() as session:
            record_actor_audit(
                session,
                actor_id=request.state.authenticated_user.user_id,
                event_type=f"insights.alert.{action}",
                target_type="insight_alert",
                request_id=request.state.request_id,
            )
            value = operation(alert_id)
    except ValueError as exc:
        if "not found" in str(exc).casefold():
            raise ApiError(404, "NOT_FOUND", "The insight was not found") from exc
        raise ApiError(409, "INVALID_STATE", "The insight cannot be moved to that state") from exc
    return _envelope(value.model_dump(mode="json"), request.state.request_id)


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, request: Request):
    return _transition(request, alert_id, "acknowledge")


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: str, request: Request):
    return _transition(request, alert_id, "resolve")


@router.get("/monthly-summaries")
def list_monthly_summaries(
    request: Request,
    month: date | None = None,
    currency: str = Query(default="ILS", min_length=3, max_length=3, pattern="^[A-Za-z]{3}$"),
    limit: int = Query(default=50, ge=1, le=100),
):
    rows = _service(request).list_summary_revisions(
        month=month, currency=currency.upper(), limit=limit
    )
    return _envelope(
        {"items": [item.model_dump(mode="json") for item in rows]},
        request.state.request_id,
    )


@router.get("/monthly-summaries/{revision_id}")
def get_monthly_summary(revision_id: str, request: Request):
    with request.app.state.database.session() as session:
        row = session.get(MonthlySummaryRevisionRow, revision_id)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "The saved monthly summary was not found")
    try:
        content = json.loads(row.content_json)
        provenance = json.loads(row.contributor_provenance_json or "{}")
    except (TypeError, ValueError):
        raise ApiError(500, "INVALID_SAVED_SUMMARY", "The saved summary could not be read") from None
    return _envelope(
        {
            "id": row.id,
            "identity_id": row.identity_id,
            "revision_number": row.revision_number,
            "month": row.month,
            "currency": row.currency,
            "content_hash": row.content_hash,
            "content": content,
            "markdown": row.markdown,
            "contributor_provenance": provenance,
            "created_at": row.created_at,
        },
        request.state.request_id,
    )
