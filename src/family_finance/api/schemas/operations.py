"""Bounded request shapes for operational and user preference routes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AutomationRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool


class AttentionCommitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm: Literal[True]


class AppPreferencesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_currency: str = Field(default="ILS", min_length=3, max_length=3)
    default_months: int = Field(default=12, ge=1, le=60)

    @field_validator("default_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha() or not normalized.isascii():
            raise ValueError("Currency must be a three-letter ISO code")
        return normalized


class InsightPreferencesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planning_scenario_id: str | None = Field(default=None, max_length=100)
    planning_revision_id: str | None = Field(default=None, max_length=100)
    forecast_id: str | None = Field(default=None, max_length=100)
    forecast_revision_id: str | None = Field(default=None, max_length=100)
    forecast_role: str | None = Field(default=None, max_length=32)
    apartment_study_id: str | None = Field(default=None, max_length=100)
    apartment_revision_id: str | None = Field(default=None, max_length=100)
    apartment_alternative_name: str | None = Field(default=None, max_length=100)
