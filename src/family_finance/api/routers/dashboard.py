"""Authenticated, read-only dashboard API routes."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select

from family_finance.api.app import ApiError, authenticated_router
from family_finance.api.schemas.dashboard import (
    ApiResponse,
    ContributorQuery,
    DashboardContributor,
    DashboardExpenses,
    DashboardFilterQuery,
    DashboardOverview,
)
from family_finance.dashboard import DashboardService
from family_finance.models import DashboardFilters
from family_finance.persistence.models import TransactionRow

router = authenticated_router(prefix="/dashboard")


def _filter_model(query: DashboardFilterQuery, dashboard: DashboardService) -> DashboardFilters:
    if query.start_month is None and query.end_month is None:
        return dashboard.default_filters(currency=query.currency)
    if query.start_month is None or query.end_month is None:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "Request validation failed",
            fields={"start_month": ["Provide both start_month and end_month"]},
        )
    start_month = date.fromisoformat(query.start_month)
    end_month = date.fromisoformat(query.end_month)
    if start_month > end_month:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "Request validation failed",
            fields={"start_month": ["start_month cannot be after end_month"]},
        )
    return DashboardFilters(
        start_month=start_month,
        end_month=end_month,
        currency=query.currency,
    )


def _envelope(data, request: Request) -> dict:
    return {"data": data, "meta": {"request_id": request.state.request_id}}


def _dashboard(request: Request) -> DashboardService:
    # MetricsService keeps per-series context for comparison lookups, so each
    # request receives its own service graph and cannot race another request.
    return DashboardService(request.app.state.database)


@router.get("/overview", response_model=ApiResponse[DashboardOverview])
def overview(
    request: Request,
    query: Annotated[DashboardFilterQuery, Depends()],
) -> dict:
    dashboard = _dashboard(request)
    result = dashboard.overview(_filter_model(query, dashboard))
    return _envelope(result.model_dump(mode="json"), request)


@router.get("/expenses", response_model=ApiResponse[DashboardExpenses])
def expenses(
    request: Request,
    query: Annotated[DashboardFilterQuery, Depends()],
) -> dict:
    dashboard = _dashboard(request)
    result = dashboard.expenses(_filter_model(query, dashboard))
    return _envelope(result.model_dump(mode="json"), request)


@router.post(
    "/contributors/query",
    response_model=ApiResponse[list[DashboardContributor]],
)
def contributors(request: Request, body: ContributorQuery) -> dict:
    ids = body.transaction_ids
    with request.app.state.database.session() as session:
        existing_ids = set(
            session.execute(
                select(TransactionRow.id).where(TransactionRow.id.in_(ids))
            ).scalars()
        )
    if existing_ids != set(ids):
        raise ApiError(404, "TRANSACTION_NOT_FOUND", "One or more transactions could not be found")
    result = _dashboard(request).contributors(ids)
    return _envelope([item.model_dump(mode="json") for item in result], request)
