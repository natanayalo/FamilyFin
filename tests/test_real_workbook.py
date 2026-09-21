from __future__ import annotations

from pathlib import Path

import pytest

from family_finance.importers.familybiz import FamilyBizParser


@pytest.mark.skipif(
    not Path("data/familybiz report 21-09-26.xlsx").exists(),
    reason="supplied local workbook is not present",
)
def test_supplied_workbook_inspection_matches_source_analysis():
    inspection = FamilyBizParser().inspect(
        Path("data/familybiz report 21-09-26.xlsx").read_bytes(),
        filename="familybiz.xlsx",
    )
    assert inspection.transaction_count == 1452
    assert inspection.section_count == 7
    assert inspection.min_booking_date.isoformat() == "2025-09-01"
    assert inspection.max_booking_date.isoformat() == "2026-09-19"
    assert inspection.currencies == {"ILS": 1438, "USD": 14}

