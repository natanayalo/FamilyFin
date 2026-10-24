"""Strict transport contracts for apartment purchase planning."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from family_finance.models import (
    ApartmentGuardrails,
    HousingCostInput,
    MortgageAssumption,
    PoolDrawInput,
    PurchaseAlternativeInput,
    PurchaseCostInput,
)


def _decimal_string(value: object) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("Amounts, ratios, and rates must be decimal strings")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Value is not a valid decimal") from exc
    if not number.is_finite():
        raise ValueError("Values must be finite decimals")
    return number


DecimalString = Annotated[Decimal, BeforeValidator(_decimal_string)]


class ApartmentGuardrailsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_remaining_liquidity: DecimalString | None = None
    maximum_housing_cost_to_income_ratio: DecimalString | None = None

    def to_domain(self) -> ApartmentGuardrails:
        return ApartmentGuardrails.model_validate(self.model_dump(mode="python"))


class PurchaseCostBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=200)
    amount: DecimalString

    def to_domain(self) -> PurchaseCostInput:
        return PurchaseCostInput.model_validate(self.model_dump(mode="python"))


class PoolDrawBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pool_name: str | None = Field(default=None, max_length=200)
    pool_id: str | None = Field(default=None, max_length=200)
    amount: DecimalString

    def to_domain(self) -> PoolDrawInput:
        return PoolDrawInput.model_validate(self.model_dump(mode="python"))


class HousingCostBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=200)
    amount: DecimalString

    def to_domain(self) -> HousingCostInput:
        return HousingCostInput.model_validate(self.model_dump(mode="python"))


class MortgageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal: DecimalString
    annual_nominal_rate: DecimalString
    term_months: int = Field(ge=12, le=480)

    def to_domain(self) -> MortgageAssumption:
        return MortgageAssumption.model_validate(self.model_dump(mode="python"))


class EquityRequirementBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["percentage", "amount"] = "percentage"
    value: DecimalString


class ApartmentAlternativeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    forecast_role: Literal["conservative", "baseline", "optimistic"]
    purchase_month: int = Field(ge=1, le=36)
    property_price: DecimalString
    family_gift: DecimalString = Decimal(0)
    purchase_costs: list[PurchaseCostBody] = Field(default_factory=list, max_length=100)
    equity_requirement: EquityRequirementBody = Field(
        default_factory=lambda: EquityRequirementBody(mode="percentage", value=Decimal("0.2"))
    )
    mortgage: MortgageBody
    pool_draws: list[PoolDrawBody] = Field(default_factory=list, max_length=100)
    stopped_housing_line_ids: list[str] = Field(default_factory=list, max_length=100)
    housing_costs: list[HousingCostBody] = Field(default_factory=list, max_length=100)
    confirmed: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Alternative name must not be blank")
        return value

    @model_validator(mode="after")
    def validate_children(self) -> ApartmentAlternativeBody:
        for cost in self.purchase_costs:
            cost.to_domain()
        for draw in self.pool_draws:
            draw.to_domain()
        for cost in self.housing_costs:
            cost.to_domain()
        self.mortgage.to_domain()
        return self

    def to_domain(self) -> PurchaseAlternativeInput:
        return PurchaseAlternativeInput.model_validate({
            "name": self.name,
            "forecast_role": self.forecast_role,
            "purchase_month": self.purchase_month,
            "property_price": self.property_price,
            "family_gift": self.family_gift,
            "purchase_costs": [item.to_domain() for item in self.purchase_costs],
            "equity_requirement": self.equity_requirement.model_dump(mode="python"),
            "mortgage": self.mortgage.to_domain(),
            "pool_draws": [item.to_domain() for item in self.pool_draws],
            "stopped_housing_line_ids": self.stopped_housing_line_ids,
            "housing_costs": [item.to_domain() for item in self.housing_costs],
            "confirmed": self.confirmed,
        })


class ApartmentInputsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forecast_id: str = Field(min_length=1, max_length=200)
    forecast_revision_number: int = Field(ge=1)
    guardrails: ApartmentGuardrailsBody = Field(default_factory=ApartmentGuardrailsBody)
    alternatives: list[ApartmentAlternativeBody] = Field(min_length=2, max_length=4)
    notes: str = Field(default="", max_length=2000)
    source_quality_acknowledged: bool = False

    @field_validator("forecast_id")
    @classmethod
    def normalize_forecast_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Saved forecast is required")
        return value

    def domain_inputs(self):
        return self.guardrails.to_domain(), [item.to_domain() for item in self.alternatives]


class ApartmentPreviewBody(ApartmentInputsBody):
    pass


class ApartmentCreateBody(ApartmentInputsBody):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Study name must not be blank")
        return value


class ApartmentRevisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_number: int = Field(ge=1)
    guardrails: ApartmentGuardrailsBody = Field(default_factory=ApartmentGuardrailsBody)
    alternatives: list[ApartmentAlternativeBody] = Field(min_length=2, max_length=4)
    notes: str = Field(default="", max_length=2000)
    source_quality_acknowledged: bool = False

    def domain_inputs(self):
        return self.guardrails.to_domain(), [item.to_domain() for item in self.alternatives]


class ApartmentRestoreBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_number: int = Field(ge=1)
    notes: str = Field(default="Restored older apartment study revision", max_length=2000)
    source_quality_acknowledged: bool = False


class ApartmentCloneBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)


class ApartmentArchiveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archived: bool = True
