"""Centralized display formatting kept separate from Decimal-safe calculations."""

from __future__ import annotations

from datetime import date
from decimal import Decimal


def format_amount(value: Decimal | None, currency: str = "ILS") -> str:
    if value is None:
        return "Unavailable"
    return f"{value:,.2f} {currency.upper()}"


def format_rate(value: Decimal | None) -> str:
    return "Unavailable" if value is None else f"{value * 100:.1f}%"


def format_month(value: date | None) -> str:
    return value.strftime("%B %Y") if value else "Unavailable"


def direction_aware(text: str) -> str:
    """Allow Hebrew/source text to choose its own direction in custom markup."""
    escaped = (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return f"<span dir=\"auto\">{escaped}</span>"


__all__ = ["direction_aware", "format_amount", "format_month", "format_rate"]
