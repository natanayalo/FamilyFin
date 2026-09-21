from __future__ import annotations

import json
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from family_finance.config import Settings
from family_finance.services import ImportService

from .conftest import make_workbook


def service(tmp_path):
    return ImportService(Settings(data_root=tmp_path / "local"))


def test_exact_duplicate_multiplicity_and_file_idempotency(tmp_path, familybiz_row):
    app = service(tmp_path)
    file_bytes = make_workbook([familybiz_row, familybiz_row])

    preview = app.preview_import(file_bytes, "duplicates.xlsx")
    result = app.commit_import(file_bytes, preview.preview_token, "duplicates.xlsx")

    assert result.statistics.inserted == 2
    assert app.database.count("transactions") == 2
    assert app.database.count("source_records") == 2

    duplicate_preview = app.preview_import(file_bytes, "duplicates.xlsx")
    duplicate = app.commit_import(file_bytes, duplicate_preview.preview_token, "duplicates.xlsx")
    assert duplicate.status.value == "duplicate"
    assert app.database.count("transactions") == 2
    assert app.database.count("import_batches") == 2


def test_unique_core_match_updates_non_monetary_fields(tmp_path, familybiz_row):
    app = service(tmp_path)
    original = make_workbook([familybiz_row])
    preview = app.preview_import(original, "one.xlsx")
    first = app.commit_import(original, preview.preview_token, "one.xlsx")
    assert first.statistics.inserted == 1

    changed = list(familybiz_row)
    changed[2] = "updated description"
    changed[5] = "updated category"
    second_preview = app.preview_import(make_workbook([changed]), "two.xlsx")
    second = app.commit_import(make_workbook([changed]), second_preview.preview_token, "two.xlsx")

    assert second.statistics.updated == 1
    assert app.database.count("transactions") == 1


def test_monetary_change_creates_open_reconciliation_case(tmp_path, familybiz_row):
    app = service(tmp_path)
    original = make_workbook([familybiz_row])
    first_preview = app.preview_import(original, "one.xlsx")
    app.commit_import(original, first_preview.preview_token, "one.xlsx")

    changed = list(familybiz_row)
    changed[1] = -19.40
    changed_file = make_workbook([changed])
    second_preview = app.preview_import(changed_file, "two.xlsx")
    second = app.commit_import(changed_file, second_preview.preview_token, "two.xlsx")

    assert second.status.value == "needs_review"
    assert second.statistics.ambiguous == 1
    assert app.database.count("reconciliation_cases") == 1
    assert app.database.count("transactions") == 1


def test_reconciliation_can_link_existing_candidate(tmp_path, familybiz_row):
    app = service(tmp_path)
    original = make_workbook([familybiz_row])
    first_preview = app.preview_import(original, "one.xlsx")
    app.commit_import(original, first_preview.preview_token, "one.xlsx")

    changed = list(familybiz_row)
    changed[1] = -19.40
    changed_file = make_workbook([changed])
    second_preview = app.preview_import(changed_file, "two.xlsx")
    second = app.commit_import(changed_file, second_preview.preview_token, "two.xlsx")
    case = app.database.open_reconciliation_cases()[0]
    candidate_id = int(json.loads(case["candidate_transaction_ids_json"])[0])

    result = app.resolve_reconciliation(
        case["id"],
        {"resolution": "link_existing", "transaction_id": candidate_id},
    )

    assert result.status.value == "committed"
    assert result.statistics.updated == 1
    assert result.statistics.unresolved == 0
    assert not app.database.open_reconciliation_cases()
    assert app.database.count("transactions") == 1
    with app.database.connect() as connection:
        amount = connection.execute("SELECT amount FROM transactions").fetchone()["amount"]
    assert amount == "-19.4"
    batch = next(item for item in app.history() if item["id"] == second.batch_id)
    assert batch["status"] == "committed"
    assert batch["statistics"]["unresolved"] == 0
    assert batch["statistics"]["updated"] == 1


def test_accept_as_new_resolution_reports_inserted_statistics(tmp_path, familybiz_row):
    app = service(tmp_path)
    original = make_workbook([familybiz_row])
    first_preview = app.preview_import(original, "one.xlsx")
    app.commit_import(original, first_preview.preview_token, "one.xlsx")

    changed = list(familybiz_row)
    changed[1] = -19.40
    changed_file = make_workbook([changed])
    second_preview = app.preview_import(changed_file, "two.xlsx")
    second = app.commit_import(changed_file, second_preview.preview_token, "two.xlsx")
    case = app.database.open_reconciliation_cases()[0]

    result = app.resolve_reconciliation(case["id"], {"resolution": "accept_as_new"})

    assert result.status.value == "committed"
    assert result.statistics.inserted == 1
    assert result.statistics.updated == 0
    assert result.statistics.unresolved == 0
    batch = next(item for item in app.history() if item["id"] == second.batch_id)
    assert batch["statistics"]["inserted"] == 1


def test_overlapping_recurring_occurrences_are_inserted(tmp_path, familybiz_row):
    app = service(tmp_path)
    recurring_a = list(familybiz_row)
    recurring_b = list(familybiz_row)
    recurring_b[0] = "19/08/2026"
    first_file = make_workbook([recurring_a, recurring_b])
    first_preview = app.preview_import(first_file, "one.xlsx")
    app.commit_import(first_file, first_preview.preview_token, "one.xlsx")

    recurring_c = list(familybiz_row)
    recurring_c[0] = "19/07/2026"
    overlap_file = make_workbook([recurring_a, recurring_b, recurring_c])
    overlap_preview = app.preview_import(overlap_file, "two.xlsx")
    overlap = app.commit_import(overlap_file, overlap_preview.preview_token, "two.xlsx")

    assert overlap.statistics.unchanged == 2
    assert overlap.statistics.inserted == 1
    assert overlap.statistics.unresolved == 0
    assert app.database.count("transactions") == 3


def test_revision_inside_recurring_series_stays_reconcilable(tmp_path, familybiz_row):
    app = service(tmp_path)
    recurring_a = list(familybiz_row)
    recurring_b = list(familybiz_row)
    recurring_b[0] = "19/08/2026"
    first_file = make_workbook([recurring_a, recurring_b])
    first_preview = app.preview_import(first_file, "one.xlsx")
    app.commit_import(first_file, first_preview.preview_token, "one.xlsx")

    revised_b = list(recurring_b)
    revised_b[1] = -19.40
    recurring_c = list(familybiz_row)
    recurring_c[0] = "19/07/2026"
    # Put the revision before the unchanged rows to exercise order-independent claiming.
    overlap_file = make_workbook([revised_b, recurring_c, recurring_a])
    overlap_preview = app.preview_import(overlap_file, "two.xlsx")
    overlap = app.commit_import(overlap_file, overlap_preview.preview_token, "two.xlsx")

    assert overlap.statistics.inserted == 1
    assert overlap.statistics.unresolved == 1
    assert app.database.count("transactions") == 3
    assert app.database.count("reconciliation_cases") == 1


def test_multiple_recurring_revisions_are_not_duplicated(tmp_path, familybiz_row):
    app = service(tmp_path)
    recurring_a = list(familybiz_row)
    recurring_b = list(familybiz_row)
    recurring_b[0] = "19/08/2026"
    first_file = make_workbook([recurring_a, recurring_b])
    first_preview = app.preview_import(first_file, "one.xlsx")
    app.commit_import(first_file, first_preview.preview_token, "one.xlsx")

    revised_a = list(recurring_a)
    revised_a[1] = -18.40
    revised_b = list(recurring_b)
    revised_b[1] = -19.40
    overlap_file = make_workbook([revised_a, revised_b])
    overlap_preview = app.preview_import(overlap_file, "two.xlsx")
    overlap = app.commit_import(overlap_file, overlap_preview.preview_token, "two.xlsx")

    assert overlap.statistics.inserted == 0
    assert overlap.statistics.unresolved == 2
    assert app.database.count("transactions") == 2
    assert app.database.count("reconciliation_cases") == 2


def test_preview_baseline_change_aborts_commit(tmp_path, familybiz_row):
    app = service(tmp_path)
    file_a = make_workbook([familybiz_row])
    preview = app.preview_import(file_a, "a.xlsx")
    file_b = make_workbook([list(familybiz_row)])
    preview_b = app.preview_import(file_b, "b.xlsx")
    app.commit_import(file_b, preview_b.preview_token, "b.xlsx")

    try:
        app.commit_import(file_a, preview.preview_token, "a.xlsx")
    except ValueError as exc:
        assert "database changed" in str(exc)
    else:
        raise AssertionError("stale preview was accepted")


def test_commit_of_modified_invalid_file_records_rejection_without_transactions(
    tmp_path, familybiz_row
):
    app = service(tmp_path)
    valid = make_workbook([familybiz_row])
    preview = app.preview_import(valid, "one.xlsx")

    result = app.commit_import(b"corrupt", preview.preview_token, "one.xlsx")

    assert result.status.value == "rejected"
    assert result.statistics.rejected == 1
    assert app.database.count("transactions") == 0
    assert app.database.count("import_batches") == 1


def test_runtime_database_setup_records_alembic_revision(tmp_path):
    app = service(tmp_path)
    with app.database.connect() as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    current_head = ScriptDirectory.from_config(config).get_current_head()
    assert revision["version_num"] == current_head
