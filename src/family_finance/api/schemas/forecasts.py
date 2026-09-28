"""Strict transport contracts for savings forecast requests."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from family_finance.models import (
    ForecastAdjustmentInput,
    ForecastAdjustmentOperation,
    ForecastCaseInput,
    ForecastEventInput,
    ForecastEventType,
    ForecastPoolInput,
    ForecastPoolType,
    ForecastRole,
    ForecastRoutingInput,
    ForecastTargetType,
)


def _iso_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, str):
        return value
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError("Date must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Date must use YYYY-MM-DD") from exc


def _decimal_string(value: object) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("Amounts and rates must be decimal strings")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Value is not a valid decimal") from exc
    if not number.is_finite():
        raise ValueError("Values must be finite decimals")
    return number


IsoDate = Annotated[date, BeforeValidator(_iso_date)]
DecimalString = Annotated[Decimal, BeforeValidator(_decimal_string)]


class ForecastPoolBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    pool_type: ForecastPoolType
    opening_balance: DecimalString
    as_of_date: IsoDate
    net_worth_account_key: str | None = Field(default=None, max_length=200)
    net_worth_snapshot_revision_id: str | None = Field(default=None, max_length=200)
    source_valuation_date: IsoDate | None = None
    source_stale: bool = False
    source_quality_acknowledged: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Pool name must not be blank")
        return value

    def to_domain(self) -> ForecastPoolInput:
        return ForecastPoolInput.model_validate(self.model_dump(mode="python"))


class ForecastRouteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_item_id: str = Field(min_length=1, max_length=200)
    pool_name: str | None = Field(default=None, max_length=200)
    pool_id: str | None = Field(default=None, max_length=200)

    def to_domain(self) -> ForecastRoutingInput:
        return ForecastRoutingInput.model_validate(self.model_dump(mode="python"))


class ForecastAdjustmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: ForecastTargetType
    target: str = Field(min_length=1, max_length=200)
    operation: ForecastAdjustmentOperation
    value: DecimalString
    start_month: int = Field(ge=1, le=36)
    end_month: int | None = Field(default=None, ge=1, le=36)

    def to_domain(self) -> ForecastAdjustmentInput:
        return ForecastAdjustmentInput.model_validate(self.model_dump(mode="python"))


class ForecastEventBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: ForecastEventType
    month: int = Field(ge=1, le=36)
    amount: DecimalString
    label: str = Field(default="One-time event", max_length=200)
    pool_name: str | None = Field(default=None, max_length=200)
    pool_id: str | None = Field(default=None, max_length=200)

    def to_domain(self) -> ForecastEventInput:
        return ForecastEventInput.model_validate(self.model_dump(mode="python"))


class ForecastCaseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ForecastRole
    annual_return_rate: DecimalString
    routes: list[ForecastRouteBody] = Field(default_factory=list, max_length=100)
    sweep_enabled: bool = False
    sweep_pool_name: str | None = Field(default=None, max_length=200)
    sweep_pool_id: str | None = Field(default=None, max_length=200)
    adjustments: list[ForecastAdjustmentBody] = Field(default_factory=list, max_length=100)
    events: list[ForecastEventBody] = Field(default_factory=list, max_length=100)
    confirmed: bool = False

    @field_validator("annual_return_rate")
    @classmethod
    def validate_return_rate(cls, value: Decimal) -> Decimal:
        if value <= Decimal(-1):
            raise ValueError("Annual return rate must be greater than -100 percent")
        return value

    def to_domain(self) -> ForecastCaseInput:
        return ForecastCaseInput.model_validate({
            "role": self.role,
            "annual_return_rate": self.annual_return_rate,
            "routes": [item.to_domain() for item in self.routes],
            "sweep_enabled": self.sweep_enabled,
            "sweep_pool_name": self.sweep_pool_name,
            "sweep_pool_id": self.sweep_pool_id,
            "adjustments": [item.to_domain() for item in self.adjustments],
            "events": [item.to_domain() for item in self.events],
            "confirmed": self.confirmed,
        })


class ForecastInputsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1, max_length=200)
    source_revision_number: int = Field(ge=1)
    starting_pools: list[ForecastPoolBody] = Field(min_length=1, max_length=100)
    cases: list[ForecastCaseBody] = Field(min_length=3, max_length=3)
    notes: str = Field(default="", max_length=2000)
    provisional_acknowledged: bool = False

    @field_validator("scenario_id")
    @classmethod
    def normalize_scenario_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Planning scenario is required")
        return value

    def domain_inputs(self) -> tuple[list[ForecastPoolInput], list[ForecastCaseInput]]:
        return (
            [item.to_domain() for item in self.starting_pools],
            [item.to_domain() for item in self.cases],
        )


class ForecastDraftBody(ForecastInputsBody):
    forecast_id: str | None = Field(default=None, max_length=200)


class ForecastCreateBody(ForecastInputsBody):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Forecast name must not be blank")
        return value


class ForecastRevisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_number: int = Field(ge=1)
    starting_pools: list[ForecastPoolBody] = Field(min_length=1, max_length=100)
    cases: list[ForecastCaseBody] = Field(min_length=3, max_length=3)
    notes: str = Field(default="", max_length=2000)
    provisional_acknowledged: bool = False

    def domain_inputs(self) -> tuple[list[ForecastPoolInput], list[ForecastCaseInput]]:
        return (
            [item.to_domain() for item in self.starting_pools],
            [item.to_domain() for item in self.cases],
        )


class ForecastRestoreBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_number: int = Field(ge=1)
    notes: str = Field(default="Restored older forecast revision", max_length=2000)
    provisional_acknowledged: bool = False


class ForecastCloneBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)


class ForecastArchiveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archived: bool = True


class ForecastNetWorthSeedsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_revision_id: str = Field(min_length=1, max_length=200)
    account_keys: list[str] = Field(min_length=1, max_length=100)
    pool_types: dict[str, ForecastPoolType] = Field(default_factory=dict)

    @field_validator("snapshot_revision_id")
    @classmethod
    def normalize_revision_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Net-worth snapshot revision is required")
        return value
