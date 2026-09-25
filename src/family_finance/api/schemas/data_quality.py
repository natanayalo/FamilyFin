"""Transport models for import review and data quality."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from family_finance.models import ImportInspection, ImportStatistics


class ImportHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_file_id: int | None = None
    parser_version: str
    baseline_batch_id: str | None = None
    report_start: date | None = None
    report_end: date | None = None
    max_transaction_date: date | None = None
    freshness_days: int | None = None
    status: str
    statistics: ImportStatistics
    issue_codes: list[str] = Field(default_factory=list)
    error_code: str | None = None
    created_at: str


class DataQualitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_rows: int
    freshness_date: date | None = None
    covered_start: date | None = None
    covered_end: date | None = None
    currencies: dict[str, int]
    issue_counts: dict[str, int]
    incomplete_months: list[date]
    open_reconciliation_cases: int
    unclassified_transaction_count: int
    unclassified_absolute_amount: Decimal
    source_coverage: str
    latest_import: ImportHistoryItem | None = None


class FamilyBizPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_token: str
    inspection: ImportInspection
    parser_version: str
    file_sha256: str
    baseline_batch_id: str | None = None
    baseline_fingerprint: str
    matching_baseline_json: str
    matcher_version: str
    decision_plan_version: str
    decision_plan_fingerprint: str
    decision_plan_json: str
    candidate_count: int
    warning_count: int
    rejected_count: int
    issue_counts: dict[str, int]
    preview_rows: list[dict[str, object]]
    predicted_statistics: ImportStatistics | None = None


class ReconciliationSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    booking_date: date
    allocation_date: date
    amount: Decimal
    currency: str
    original_currency: str | None = None
    original_amount: Decimal | None = None
    description: str
    movement_type: str | None = None
    category: str


class ReconciliationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    account: str
    booking_date: date
    allocation_date: date
    amount: Decimal
    currency: str
    original_currency: str | None = None
    original_amount: Decimal | None = None
    description: str
    movement_type: str | None = None
    category: str


class ReconciliationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    import_batch_id: str
    source_record_id: int
    reason: str
    created_at: str
    source: ReconciliationSource | None = None
    candidates: list[ReconciliationCandidate]


class ReconciliationResolutionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: Literal["accept_as_new", "dismiss", "link_existing"]
    transaction_id: int | None = None

    @field_validator("transaction_id")
    @classmethod
    def require_positive_transaction_id(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("transaction_id must be positive")
        return value

    @model_validator(mode="after")
    def transaction_id_matches_resolution(self) -> ReconciliationResolutionBody:
        if self.resolution == "link_existing" and self.transaction_id is None:
            raise ValueError("link_existing requires transaction_id")
        if self.resolution != "link_existing" and self.transaction_id is not None:
            raise ValueError("transaction_id is only valid for link_existing")
        return self


def import_history_item(row: dict[str, object]) -> ImportHistoryItem:
    """Convert the service's JSON statistics field to the feature DTO."""

    values = dict(row)
    statistics = values.pop("statistics", {})
    if isinstance(statistics, str):
        import json

        statistics = json.loads(statistics)
    return ImportHistoryItem.model_validate({**values, "statistics": statistics})
