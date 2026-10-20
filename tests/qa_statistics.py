"""Opt-in monthly transactions for the disposable browser QA household."""

from pathlib import Path
from tempfile import gettempdir

from family_finance.config import Settings
from family_finance.persistence.db import Database
from family_finance.services import ImportService
from tests.conftest import make_workbook


def seed_statistics_qa(database: Database) -> None:
    path = database.path.resolve()
    if not path.is_relative_to(Path(gettempdir()).resolve()) or not path.parent.parent.name.startswith("familyfin-live-"):
        raise ValueError("Statistics QA requires a disposable familyfin-live database")
    service = ImportService(settings=Settings(data_root=path.parent), database=database)
    if any(item["description"].startswith("Statistics QA ") for item in service.classification_service.repository.accepted_transactions()):
        raise ValueError("Statistics QA already exists; existing transactions will not be changed")
    rows = []
    for month in range(1, 9):
        day = f"{31 if month == 8 else 15:02d}/{month:02d}/2026"
        for kind, amount, category in (("income", 24000.50 + month * 100, "משכורת"), ("expense", -(14000.25 + month * 750), "קניות")):
            rows.append([day, amount, f"Statistics QA {kind} {month}", day, kind, category, "ILS", "ILS", amount])
    payload = make_workbook(rows, provider="בנק בדיקה", reference="statistics-qa-only", report_end="31/08/2026")
    preview = service.preview_import(payload)
    service.commit_import(payload, preview.preview_token, "statistics-qa.xlsx")
    for item in service.classification_service.repository.accepted_transactions():
        if item["description"].startswith("Statistics QA "):
            service.classification_service.save_override(item["id"], economic_class="income" if "income" in item["description"] else "consumption", reason="Synthetic Statistics QA")
