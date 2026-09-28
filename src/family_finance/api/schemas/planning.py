"""Strict transport contracts for household planning scenarios."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from family_finance.models import PlanningFrequency, PlanningItemKind


def _month_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, str):
        result = value
    elif isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}(?:-01)?", value):
        try:
            result = date.fromisoformat(value if len(value) == 10 else f"{value}-01")
        except ValueError as exc:
            raise ValueError("Month must be a valid calendar month") from exc
    else:
        raise ValueError("Month must use YYYY-MM or YYYY-MM-01")
    if result.day != 1:
        raise ValueError("Month must be the first day of a calendar month")
    return result


def _decimal_string(value: object) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("Amounts must be decimal strings")  # noqa: TRY004
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Amount is not a valid decimal") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("Amount must be a finite non-negative decimal")
    return result


MonthDate = Annotated[date, BeforeValidator(_month_date)]
DecimalString = Annotated[Decimal, BeforeValidator(_decimal_string)]


class PlanningItemBody(BaseModel):
    """Planning item input plus the source fields needed to preserve provenance."""

    model_config = ConfigDict(extra="forbid")

    kind: PlanningItemKind
    label: str = Field(min_length=1, max_length=500)
    category: str | None = Field(default=None, max_length=200)
    amount: DecimalString
    frequency: PlanningFrequency
    start_month: MonthDate | None = None
    end_month: MonthDate | None = None
    occurrence_month: MonthDate | None = None
    id: str = Field(default="", max_length=200)
    origin: str = Field(default="manual", max_length=64)
    source_range: str | None = Field(default=None, max_length=500)
    source_row: int | None = Field(default=None, ge=1)
    policy_version: str = Field(default="planning-v1", max_length=64)
    completeness_codes: list[str] = Field(default_factory=list, max_length=100)
    contributor_transaction_ids: list[int] = Field(default_factory=list, max_length=10000)
    provenance: dict[str, Any] = Field(default_factory=dict)
    notes: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Planning item label must not be blank")
        return value

    @field_validator("category")
    @classmethod
    def normalize_category(cls, value: str | None) -> str | None:
        value = value.strip() if value is not None else None
        return value or None

    @model_validator(mode="after")
    def schedule_matches_frequency(self) -> PlanningItemBody:
        if self.frequency == PlanningFrequency.MONTHLY:
            if self.start_month is None or self.end_month is None:
                raise ValueError("Monthly planning items require a start and end month")
            if self.start_month > self.end_month:
                raise ValueError("Planning item start month cannot be after its end month")
            if self.occurrence_month is not None:
                raise ValueError("Monthly planning items cannot have an occurrence month")
        elif self.occurrence_month is None:
            raise ValueError("One-time planning items require an occurrence month")
        elif self.start_month is not None or self.end_month is not None:
            raise ValueError("One-time planning items cannot have a start or end month")
        return self

    def service_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python")


class ScenarioCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    currency: str = Field(default="ILS", min_length=1, max_length=12)
    start_month: MonthDate
    items: list[PlanningItemBody] = Field(default_factory=list, max_length=1000)
    notes: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Scenario name must not be blank")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("Currency must not be blank")
        return value


class HistorySeedPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Historical baseline", min_length=1, max_length=200)
    currency: str = Field(default="ILS", min_length=1, max_length=12)
    start_month: MonthDate
    history_months: int = Field(default=6, ge=1, le=120)


class PreviewCommitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_token: str = Field(min_length=1, max_length=1_000_000)
    acknowledge_provisional: bool = False


class CategoryMappingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csv_category: str = Field(min_length=1, max_length=200)
    analysis_category: str | None = Field(default=None, max_length=200)

    @field_validator("analysis_category")
    @classmethod
    def normalize_mapping(cls, value: str | None) -> str | None:
        value = value.strip() if value is not None else None
        return value or None


class CsvCommitMappings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mappings: list[CategoryMappingBody] = Field(default_factory=list, max_length=1000)


class RevisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_number: int = Field(ge=1)
    items: list[PlanningItemBody] = Field(max_length=1000)
    notes: str = Field(default="", max_length=2000)
    acknowledge_provisional: bool = False


class ProjectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_number: int = Field(ge=1)
    items: list[PlanningItemBody] = Field(max_length=1000)


class RestoreRevisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_number: int = Field(ge=1)
    acknowledge_provisional: bool = False
    notes: str = Field(default="Restored older planning revision", max_length=2000)


class CloneScenarioBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    acknowledge_provisional: bool = False


class ArchiveScenarioBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archived: bool = True


class CompareScenariosBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_ids: list[str] = Field(min_length=2, max_length=4)

    @field_validator("scenario_ids")
    @classmethod
    def unique_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Choose each scenario once")
        return value
