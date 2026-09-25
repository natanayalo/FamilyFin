"""HTTP request contracts for the observed net-worth ledger."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from family_finance.models import NetWorthAccountInput


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
        # Pydantic treats ValueError as a field-validation failure; TypeError
        # would escape FastAPI's 422 request-validation mapping.
        raise ValueError("Amounts must be decimal strings")  # noqa: TRY004
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Amount is not a valid decimal") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("Amount must be a finite non-negative decimal")
    return amount


IsoDate = Annotated[date, BeforeValidator(_iso_date)]
DecimalString = Annotated[Decimal, BeforeValidator(_decimal_string)]


class AccountBody(NetWorthAccountInput):
    """Flat account registry body with strict calendar dates."""

    display_name: str = Field(min_length=1, max_length=200)
    active_from: IsoDate = Field(default_factory=date.today)
    active_to: IsoDate | None = None


class AccountCloseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    closed_on: IsoDate | None = None


class AccountReactivateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_from: IsoDate | None = None


class SnapshotBalanceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_key: str = Field(min_length=1, max_length=200)
    amount_ils: DecimalString
    valuation_date: IsoDate
    notes: str = Field(default="", max_length=1000)


class SnapshotCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_date: IsoDate
    balances: list[SnapshotBalanceBody] = Field(min_length=1, max_length=1000)
    notes: str = Field(default="", max_length=2000)
    quality_acknowledged: bool = False


class SnapshotRevisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    balances: list[SnapshotBalanceBody] = Field(min_length=1, max_length=1000)
    expected_revision_number: int = Field(ge=1)
    notes: str = Field(default="", max_length=2000)
    quality_acknowledged: bool = False


class SnapshotRestoreBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_number: int = Field(ge=1)
    quality_acknowledged: bool = False
    notes: str = Field(default="Restored older net-worth revision", max_length=2000)


class SnapshotArchiveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archived: bool = True


class CsvCommitFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_token: str = Field(min_length=1, max_length=4096)
    filename: str | None = Field(default=None, max_length=255)
    create_new_revision: bool = False
    quality_acknowledged: bool = False


class ForecastComparisonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forecast_id: str = Field(min_length=1, max_length=200)
    observed_snapshot_revision_id: str = Field(min_length=1, max_length=200)
    forecast_revision_number: int = Field(ge=1)
    role: Literal["baseline", "conservative", "optimistic"] = "baseline"

    @field_validator("forecast_id", "observed_snapshot_revision_id")
    @classmethod
    def require_identifier(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Identifier must not be empty")
        return value
