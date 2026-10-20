"""Opt-in sample balances for the disposable live-browser QA household only."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import gettempdir

from family_finance.net_worth import NetWorthService
from family_finance.persistence.db import Database


def seed_net_worth_qa(database: Database, *, as_of: date) -> dict[str, str | int]:
    path = database.path.resolve()
    if not path.is_relative_to(Path(gettempdir()).resolve()) or not path.parent.parent.name.startswith("familyfin-live-"):
        raise ValueError("Net-worth QA data requires a disposable familyfin-live temporary database")
    service = NetWorthService(database)
    if service.list_accounts() or service.list_snapshots(include_archived=True):
        raise ValueError("QA net-worth setup is already populated; existing records will not be changed")

    previous = as_of.replace(day=1) - timedelta(days=1)
    earlier = previous.replace(day=1) - timedelta(days=1)
    # Key, Hebrew label, side, category, liquidity, latest amount, monthly change.
    accounts = [
        ("qa-current", "בדיקה - חשבון עו״ש", "asset", "cash", "liquid", "18500.25", "1000"),
        ("qa-savings", "בדיקה - חיסכון חירום", "asset", "savings", "liquid", "42000", "1000"),
        ("qa-investment", "בדיקה - תיק השקעות", "asset", "investment", "liquid", "158750.40", "5000"),
        ("qa-pension", "בדיקה - פנסיה", "asset", "pension", "restricted", "245000", "5000"),
        ("qa-training", "בדיקה - קרן השתלמות", "asset", "training_fund", "restricted", "68500.35", "1500"),
        ("qa-property", "בדיקה - דירה", "asset", "property", "illiquid", "1650000", "0"),
        ("qa-mortgage", "בדיקה - יתרת משכנתה", "liability", "mortgage", None, "630000", "-1000"),
        ("qa-loan", "בדיקה - יתרת הלוואה", "liability", "loan", None, "18000", "-1000"),
    ]
    with database.api_write_unit_of_work():
        for key, name, side, category, liquidity, _, _ in accounts:
            service.create_account({
                "account_key": key, "display_name": name, "side": side, "category": category,
                "liquidity": liquidity, "owner_label": "משפחה לדוגמה",
                "active_from": earlier.replace(day=1), "stale_after_days": 30 if key == "qa-investment" else 120,
            })
        for offset, captured_on in zip((2, 1, 0), (earlier, previous, as_of), strict=True):
            snapshot = service.create_snapshot(captured_on, [
                {
                    "account_key": key,
                    "amount_ils": Decimal(amount) - Decimal(change) * offset,
                    "valuation_date": min(captured_on, as_of - timedelta(days=60)) if key == "qa-investment" else captured_on,
                    "notes": "נתוני בדיקה בלבד",
                }
                for key, _, _, _, _, amount, change in accounts
            ], notes="תמונת מצב לדוגמה - נתוני QA בלבד", quality_acknowledged=True)
    summary = service.summary(snapshot_id=snapshot.snapshot_id)
    return {
        "accounts": len(accounts), "snapshots": 3, "as_of": as_of.isoformat(),
        "assets": str(summary.total_assets), "liabilities": str(summary.total_liabilities),
        "net_worth": str(summary.net_worth),
    }
