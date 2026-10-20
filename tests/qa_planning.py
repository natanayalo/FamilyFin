"""Opt-in scenarios for the disposable browser QA database only."""

from pathlib import Path
from tempfile import gettempdir

from family_finance.persistence.db import Database
from family_finance.planning import PlanningService


def seed_planning_qa(database: Database) -> dict[str, str]:
    path = database.path.resolve()
    if not path.is_relative_to(Path(gettempdir()).resolve()) or not path.parent.parent.name.startswith("familyfin-live-"):
        raise ValueError("Planning QA requires a disposable familyfin-live database")
    service = PlanningService(database)
    if service.list_scenarios(include_archived=True):
        raise ValueError("QA planning is already populated; existing scenarios will not be changed")

    def item(kind, label, amount, *, once=False):
        return {"kind": kind, "label": label, "amount": amount, "frequency": "one_time" if once else "monthly",
                    "start_month": None if once else "2026-09-01", "end_month": None if once else "2027-08-01",
                    "occurrence_month": "2026-11-01" if once else None}

    with database.api_write_unit_of_work():
        scenario = service.create_manual_scenario("בדיקה - התקציב המשפחתי", "2026-09-01", [
            item("income", "משכורות", "24000.50"),
            item("expense", "דיור וחשבונות", "10000"),
            item("expense", "קניות, תחבורה ופנאי", "5000.25"),
            item("savings_contribution", "חיסכון חודשי", "4000"),
            item("expense", "חופשה חד־פעמית", "9000", once=True),
        ], notes="נתוני QA סינתטיים בלבד")
    return {"scenario_id": scenario.scenario_id}
