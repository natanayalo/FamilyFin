"""Transport contracts for classification review and reusable rules."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from family_finance.models import (
    ClassificationReviewItem,
    EconomicClass,
    ExpenseBehavior,
)


class OverrideBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_override_version: int = Field(ge=0)
    expected_classification_state: str = Field(pattern=r"^[0-9a-f]{64}$")
    economic_class: EconomicClass | None = None
    analysis_category: str | None = Field(default=None, max_length=200)
    expense_behavior: ExpenseBehavior | None = None
    reason: str = Field(default="Saved from classification review", max_length=500)

    def decision_fields(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in ("economic_class", "analysis_category", "expense_behavior")
            if getattr(self, name) is not None
        }

    @field_validator("analysis_category")
    @classmethod
    def analysis_category_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("analysis_category must be omitted or cleared")
        return value


class ClearOverrideBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_override_version: int = Field(ge=0)
    expected_classification_state: str = Field(pattern=r"^[0-9a-f]{64}$")
    fields: list[Literal["economic_class", "analysis_category", "expense_behavior"]] | None = Field(
        default=None, min_length=1, max_length=3
    )
    reason: str = Field(default="Override cleared", max_length=500)


class RuleFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_kind: str = Field(min_length=1, max_length=64)
    direction: Literal["debit", "credit", "zero"]
    source_category: str = Field(min_length=1, max_length=200)
    source_movement_type: str | None = Field(default=None, max_length=200)
    currency: str = Field(min_length=3, max_length=8)
    economic_class: EconomicClass
    analysis_category: str | None = Field(default=None, max_length=200)
    expense_behavior: ExpenseBehavior | None = None
    reason: str = Field(default="Saved from classification review", max_length=500)

    @field_validator("account_kind")
    @classmethod
    def account_kind_not_blank(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("account_kind must not be blank")
        return value

    @field_validator("source_category")
    @classmethod
    def source_category_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_category must not be blank")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if not value.isascii() or not value.isalpha():
            raise ValueError("currency must contain letters only")
        return value

    @field_validator("analysis_category")
    @classmethod
    def rule_analysis_category_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("analysis_category must be omitted")
        return value

    def service_payload(self) -> dict[str, object]:
        # ClassificationService applies its existing class-dependent behavior
        # default when expense_behavior is omitted.
        return self.model_dump(exclude_none=True, exclude={"expected_current_rule_id"})


class RuleCreateBody(RuleFields):
    # Null means the preview saw no rule for this exact-match key. Making the
    # property required distinguishes an intentional null precondition from an
    # older client that does not implement conditional rule writes.
    expected_current_rule_id: int | None = Field(..., ge=1)


class RuleDisableBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_current_rule_id: int = Field(ge=1)
    reason: str = Field(default="Reusable rule disabled", max_length=500)


class ReviewQueueItem(ClassificationReviewItem):
    expected_override_version: int = Field(ge=0)
    expected_classification_state: str = Field(pattern=r"^[0-9a-f]{64}$")


__all__ = [
    "ClearOverrideBody",
    "OverrideBody",
    "ReviewQueueItem",
    "RuleCreateBody",
    "RuleDisableBody",
    "RuleFields",
]
