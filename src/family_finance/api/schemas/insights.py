"""Bounded review requests for detected recurring expenses."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RecurringPatternReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: str | None = Field(..., min_length=1, max_length=64)
    status: Literal["approved", "dismissed", "stopped", "pending"]
    start_month: date
    end_month: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("start_month", "end_month")
    @classmethod
    def align_month(cls, value: date) -> date:
        return value.replace(day=1)

    @model_validator(mode="after")
    def ordered_range(self):
        if self.start_month > self.end_month:
            raise ValueError("start_month cannot be after end_month")
        return self
