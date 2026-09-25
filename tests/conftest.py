from __future__ import annotations

import csv
import io

import pytest
from openpyxl import Workbook

from family_finance.importers.familybiz import HEADERS


def make_workbook(
    rows: list[list[object]],
    *,
    provider: str = "כאל",
    reference: str = "masked-reference",
    report_end: str = "30/09/2026",
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.cell(1, 1).value = f"{report_end} :עד תאריך"
    sheet.cell(1, 2).value = "01/09/2025 :מתאריך "
    sheet.cell(3, 1).value = provider
    sheet.cell(3, 2).value = reference
    for column, value in enumerate(HEADERS, start=2):
        sheet.cell(5, column).value = value
    for row_number, row in enumerate(rows, start=6):
        for column, value in enumerate([None, *row], start=1):
            sheet.cell(row_number, column).value = value
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


@pytest.fixture
def familybiz_row() -> list[object]:
    return [
        "19/09/2026",
        -17.40,
        "merchant",
        "19/09/2026",
        "food",
        "household_x000D_\n",
        "ILS",
        "ILS",
        -17.40,
    ]


@pytest.fixture
def familybiz_workbook_bytes(familybiz_row: list[object]) -> bytes:
    """Provide a small synthetic import for tests that need source history."""
    return make_workbook([familybiz_row])


@pytest.fixture
def planning_csv_bytes() -> bytes:
    """Provide a deterministic multi-block planning CSV without household data."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        ["קטגוריה", "מיני קטגוריה", "יעד", "הערות", "הוצאות חודשי", "הכנסות", "סכום", "חסכון"]
    )
    for index in range(24):
        category = "household" if index == 0 else f"Synthetic category {index}"
        note = f"Synthetic note {index}" if index < 9 else ""
        writer.writerow([category, "", "100", note, "", "", "", ""])
    writer.writerow(["סהכ הוצאות", "", "2500", "", "", "", "", ""])
    writer.writerow(["", "", "", "", "", "משכורת", "10000", ""])
    writer.writerow(["", "", "", "", "", "Salary bonus", "1000", ""])
    writer.writerow(["", "", "", "", "2500", "סהכ הכנסות", "11000", "5000"])
    return output.getvalue().encode("utf-8")
