"""Opt-in forecast assumptions for the disposable browser QA household."""

from pathlib import Path
from tempfile import gettempdir

from family_finance.forecasting import SavingsForecastService
from family_finance.persistence.db import Database
from family_finance.planning import PlanningService


def seed_forecasts_qa(database: Database) -> dict[str, str]:
    path = database.path.resolve()
    if not path.is_relative_to(Path(gettempdir()).resolve()) or not path.parent.parent.name.startswith("familyfin-live-"):
        raise ValueError("Forecast QA requires a disposable familyfin-live database")
    service = SavingsForecastService(database)
    if service.list_forecasts(include_archived=True):
        raise ValueError("QA forecasts already exist; existing records will not be changed")
    planning = PlanningService(database)
    scenarios = planning.list_scenarios()
    scenario = next((item for item in scenarios if item.name == "בדיקה - התקציב המשפחתי"), None)
    if scenario is None:
        raise ValueError("Seed the Planning QA fixture first")
    revision = planning.get_revision(scenario.scenario_id)
    pool_name = "בדיקה - חיסכון משפחתי"
    cases = [{"role": role, "annual_return_rate": rate, "confirmed": True,
                  "routes": [{"source_item_id": item.id, "pool_name": pool_name} for item in revision.items
                          if str(item.kind) in ("savings_contribution", "savings_withdrawal")],
                  "sweep_enabled": False, "sweep_pool_name": None, "adjustments": [], "events": []}
             for role, rate in (("conservative", "0"), ("baseline", "0.03"), ("optimistic", "0.06"))]
    result = service.create_forecast("בדיקה - חיסכון לשלוש שנים", scenario.scenario_id,
        [{"name": pool_name, "pool_type": "investment", "opening_balance": "42000.25", "as_of_date": scenario.start_month}],
        cases, source_revision_number=revision.revision_number, notes="הנחות המחשה סינתטיות בלבד")
    return {"forecast_id": result.forecast_id}
