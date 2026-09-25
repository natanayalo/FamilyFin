"""Dashboard transport schemas for the read-only PWA endpoints."""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from family_finance.models import (
    ExpenseDashboard,
    OverviewDashboard,
    TransactionContribution,
)

_MONTH_OR_DATE = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")


class ApiResponseMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    next_cursor: str | None = None
    limit: int | None = None


class ApiResponse[T](BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: T
    meta: ApiResponseMeta


class DashboardFilterQuery(BaseModel):
    """Optional month scope; absent months resolve through DashboardService defaults."""

    model_config = ConfigDict(extra="forbid")

    start_month: str | None = None
    end_month: str | None = None
    currency: str = "ILS"

    @field_validator("start_month", "end_month", mode="before")
    @classmethod
    def parse_and_align_month(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _MONTH_OR_DATE.fullmatch(value):
            raise ValueError("Month must use YYYY-MM or YYYY-MM-DD")
        parsed = date.fromisoformat(f"{value}-01" if len(value) == 7 else value)
        return parsed.replace(day=1).isoformat()

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if not value or len(value) > 12:
            raise ValueError("Currency must be a non-empty short code")
        return value

class ContributorQuery(BaseModel):
    """Bounded transaction-ID request; IDs never travel in a URL."""

    model_config = ConfigDict(extra="forbid")

    transaction_ids: list[StrictInt] = Field(min_length=1, max_length=100)

    @field_validator("transaction_ids")
    @classmethod
    def require_distinct_ids(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("Transaction IDs must be distinct")
        return value


class DashboardOverview(OverviewDashboard):
    """Feature-local response DTO matching DashboardService.overview."""


class DashboardExpenses(ExpenseDashboard):
    """Feature-local response DTO matching DashboardService.expenses."""


class DashboardContributor(TransactionContribution):
    """Feature-local response DTO for a contributing transaction."""
