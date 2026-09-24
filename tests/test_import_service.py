from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from family_finance.config import Settings
from family_finance.services import ImportService, ImportValidationError, PreviewStaleError

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


def test_unique_non_exact_candidate_requires_reconciliation(tmp_path, familybiz_row):
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

    assert second.statistics.updated == 0
    assert second.statistics.unresolved == 1
    assert app.database.count("transactions") == 1
    assert app.database.count("reconciliation_cases") == 1


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


@pytest.mark.parametrize(
    ("field_index", "changed_value"),
    [
        pytest.param(3, "20/09/2026", id="allocation-date"),
        pytest.param(4, "refund", id="movement-type"),
        pytest.param(5, "restaurants", id="category"),
    ],
)
def test_source_field_change_requires_reconciliation_without_updating_transaction(
    tmp_path, familybiz_row, field_index, changed_value
):
    app = service(tmp_path)
    initial = make_workbook([familybiz_row])
    initial_preview = app.preview_import(initial, "initial.xlsx")
    app.commit_import(initial, initial_preview.preview_token, "initial.xlsx")

    with app.database.connect() as connection:
        original = tuple(connection.execute(text(
            "SELECT booking_date, allocation_date, amount, currency, description, "
            "movement_type, category, original_currency, original_amount "
            "FROM transactions WHERE id=1"
        )).fetchone().values())

    revised = list(familybiz_row)
    revised[field_index] = changed_value
    payload = make_workbook([revised])
    preview = app.preview_import(payload, "source-field-revision.xlsx")
    result = app.commit_import(payload, preview.preview_token, "source-field-revision.xlsx")

    assert preview.predicted_statistics is not None
    assert preview.predicted_statistics.model_dump() == result.statistics.model_dump()
    assert result.statistics.unresolved == 1
    assert result.statistics.unchanged == 0
    assert result.statistics.inserted == 0
    assert app.database.count("transactions") == 1
    with app.database.connect() as connection:
        after = tuple(connection.execute(text(
            "SELECT booking_date, allocation_date, amount, currency, description, "
            "movement_type, category, original_currency, original_amount "
            "FROM transactions WHERE id=1"
        )).fetchone().values())
    assert after == original


def test_booking_date_change_is_reconciliation_candidate_not_new_transaction(
    tmp_path, familybiz_row
):
    app = service(tmp_path)
    initial = make_workbook([familybiz_row])
    initial_preview = app.preview_import(initial, "initial.xlsx")
    app.commit_import(initial, initial_preview.preview_token, "initial.xlsx")
    metrics_before = app.metrics_service.monthly_metrics("2026-09")

    revised = list(familybiz_row)
    revised[0] = "20/09/2026"
    payload = make_workbook([revised])
    preview = app.preview_import(payload, "booking-date-change.xlsx")
    result = app.commit_import(payload, preview.preview_token, "booking-date-change.xlsx")

    assert preview.predicted_statistics is not None
    assert preview.predicted_statistics.model_dump() == result.statistics.model_dump()
    assert result.statistics.unresolved == 1
    assert result.statistics.inserted == 0
    assert app.database.count("transactions") == 1
    metrics_after = app.metrics_service.monthly_metrics("2026-09")
    assert (
        metrics_after.gross_income,
        metrics_after.gross_consumption,
        metrics_after.refunds,
        metrics_after.net_consumption,
        metrics_after.spending_by_category,
    ) == (
        metrics_before.gross_income,
        metrics_before.gross_consumption,
        metrics_before.refunds,
        metrics_before.net_consumption,
        metrics_before.spending_by_category,
    )


def test_reporting_and_original_amount_change_remains_a_reconciliation_candidate(
    tmp_path, familybiz_row
):
    app = service(tmp_path)
    initial = make_workbook([familybiz_row])
    initial_preview = app.preview_import(initial, "initial.xlsx")
    app.commit_import(initial, initial_preview.preview_token, "initial.xlsx")
    metrics_before = app.metrics_service.monthly_metrics("2026-09")

    revised = list(familybiz_row)
    revised[1] = -18.40
    revised[8] = -18.40
    payload = make_workbook([revised])
    preview = app.preview_import(payload, "amounts-change.xlsx")
    result = app.commit_import(payload, preview.preview_token, "amounts-change.xlsx")

    assert preview.predicted_statistics is not None
    assert preview.predicted_statistics.model_dump() == result.statistics.model_dump()
    assert result.statistics.unresolved == 1
    assert result.statistics.inserted == 0
    assert app.database.count("transactions") == 1
    metrics_after = app.metrics_service.monthly_metrics("2026-09")
    assert (
        metrics_after.gross_income,
        metrics_after.gross_consumption,
        metrics_after.refunds,
        metrics_after.net_consumption,
        metrics_after.spending_by_category,
    ) == (
        metrics_before.gross_income,
        metrics_before.gross_consumption,
        metrics_before.refunds,
        metrics_before.net_consumption,
        metrics_before.spending_by_category,
    )


def test_compound_revision_outside_candidate_signatures_is_recorded_as_new(
    tmp_path, familybiz_row
):
    app = service(tmp_path)
    initial = make_workbook([familybiz_row])
    initial_preview = app.preview_import(initial, "initial.xlsx")
    app.commit_import(initial, initial_preview.preview_token, "initial.xlsx")

    revised = list(familybiz_row)
    revised[0] = "22/09/2026"
    revised[1] = -35.75
    revised[2] = "revised merchant descriptor"
    revised[8] = -35.75
    payload = make_workbook([revised])
    preview = app.preview_import(payload, "compound-revision.xlsx")
    result = app.commit_import(payload, preview.preview_token, "compound-revision.xlsx")

    assert preview.predicted_statistics is not None
    assert preview.predicted_statistics.model_dump() == result.statistics.model_dump()
    assert result.statistics.inserted == 1
    assert result.statistics.unresolved == 0
    assert app.database.count("transactions") == 2
    with app.database.connect() as connection:
        rows = connection.execute(text(
            "SELECT booking_date, amount, description FROM transactions ORDER BY id"
        )).fetchall()
    assert tuple(rows[0].values()) == ("2026-09-19", "-17.4", "merchant")
    assert tuple(rows[1].values()) == (
        "2026-09-22",
        "-35.75",
        "revised merchant descriptor",
    )


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


def test_exact_match_reservation_precedes_competing_non_exact_candidate(
    tmp_path, familybiz_row
):
    app = service(tmp_path)
    original = make_workbook([familybiz_row])
    first = app.preview_import(original, "original.xlsx")
    app.commit_import(original, first.preview_token, "original.xlsx")

    non_exact = list(familybiz_row)
    non_exact[2] = "alternate description"
    payload = make_workbook([non_exact, familybiz_row])
    preview = app.preview_import(payload, "exact-wins.xlsx")
    decisions = json.loads(preview.decision_plan_json)

    assert preview.predicted_statistics.unchanged == 1
    assert preview.predicted_statistics.inserted == 1
    assert preview.predicted_statistics.ambiguous == 0
    assert {item["decision_type"] for item in decisions["groups"]} == {
        "exact_match",
        "new",
    }
    result = app.commit_import(payload, preview.preview_token, "exact-wins.xlsx")
    assert result.statistics.unchanged == 1
    assert result.statistics.inserted == 1
    assert app.database.count("transactions") == 2


def test_exact_reservation_leaves_remaining_duplicate_occurrence_for_reconciliation(
    tmp_path, familybiz_row
):
    app = service(tmp_path)
    alternative = list(familybiz_row)
    alternative[2] = "alternate description"
    seeded = make_workbook([familybiz_row, alternative])
    seeded_preview = app.preview_import(seeded, "seeded.xlsx")
    app.commit_import(seeded, seeded_preview.preview_token, "seeded.xlsx")

    repeated = make_workbook([familybiz_row, familybiz_row])
    preview = app.preview_import(repeated, "repeated.xlsx")
    assert preview.predicted_statistics.unchanged == 1
    assert preview.predicted_statistics.ambiguous == 1
    assert preview.predicted_statistics.inserted == 0
    decisions = json.loads(preview.decision_plan_json)["groups"]
    assert sorted(group["decision_type"] for group in decisions) == [
        "ambiguous",
        "exact_match",
    ]


def test_competing_non_exact_occurrences_share_canonical_ambiguity_group(
    tmp_path, familybiz_row
):
    app = service(tmp_path)
    original = make_workbook([familybiz_row])
    first = app.preview_import(original, "original.xlsx")
    app.commit_import(original, first.preview_token, "original.xlsx")

    first_revision = list(familybiz_row)
    first_revision[2] = "alternate merchant A"
    second_revision = list(familybiz_row)
    second_revision[2] = "alternate merchant B"
    payload_a = make_workbook([first_revision, second_revision])
    payload_b = make_workbook([second_revision, first_revision])
    preview_a = app.preview_import(payload_a, "order-a.xlsx")
    preview_b = app.preview_import(payload_b, "order-b.xlsx")
    groups_a = json.loads(preview_a.decision_plan_json)["groups"]
    groups_b = json.loads(preview_b.decision_plan_json)["groups"]

    def economic_groups(groups):
        return sorted(
            (
                group["decision_type"],
                tuple(group["candidate_references"]),
                group["ambiguity_group"],
                group["multiplicity"],
            )
            for group in groups
        )

    assert economic_groups(groups_a) == economic_groups(groups_b)
    assert preview_a.predicted_statistics.ambiguous == 2
    assert len({group["ambiguity_group"] for group in groups_a}) == 1
    assert all(group["decision_type"] == "ambiguous" for group in groups_a)


def test_older_unresolved_case_does_not_reserve_later_exact_candidate(
    tmp_path, familybiz_row
):
    app = service(tmp_path)
    original = make_workbook([familybiz_row])
    first = app.preview_import(original, "original.xlsx")
    app.commit_import(original, first.preview_token, "original.xlsx")

    revision = list(familybiz_row)
    revision[1] = -19.40
    changed = make_workbook([revision])
    changed_preview = app.preview_import(changed, "revision.xlsx")
    app.commit_import(changed, changed_preview.preview_token, "revision.xlsx")
    old_case = app.database.open_reconciliation_cases()[0]

    extra = list(familybiz_row)
    extra[0] = "18/09/2026"
    later = make_workbook([familybiz_row, extra])
    later_preview = app.preview_import(later, "later-exact.xlsx")
    result = app.commit_import(later, later_preview.preview_token, "later-exact.xlsx")

    assert result.statistics.unchanged == 1
    assert result.statistics.inserted == 1
    assert app.database.open_reconciliation_cases()[0]["id"] == old_case["id"]
    assert app.database.count("transactions") == 2


def test_relevant_transaction_change_without_new_batch_stales_preview(
    tmp_path, familybiz_row
):
    from family_finance.persistence.models import TransactionRow

    app = service(tmp_path)
    initial = make_workbook([familybiz_row])
    initial_preview = app.preview_import(initial, "initial.xlsx")
    app.commit_import(initial, initial_preview.preview_token, "initial.xlsx")

    proposed = list(familybiz_row)
    proposed[2] = "a changed description"
    payload = make_workbook([proposed])
    preview = app.preview_import(payload, "proposed.xlsx")
    def counts():
        with app.database.session() as session:
            source_files = session.execute(
                text("SELECT COUNT(*) FROM source_files")
            ).scalar_one()
        return {
            "transactions": app.database.count("transactions"),
            "source_records": app.database.count("source_records"),
            "source_files": source_files,
            "import_batches": app.database.count("import_batches"),
        }

    counts_before = counts()
    archived_before = sorted(path.name for path in app.settings.archive_root.glob("*"))
    with app.database.write_session() as session:
        transaction = session.get(TransactionRow, 1)
        transaction.description = "changed after preview"

    with pytest.raises(PreviewStaleError, match="matching state changed"):
        app.commit_import(payload, preview.preview_token, "proposed.xlsx")
    assert counts() == counts_before
    assert sorted(path.name for path in app.settings.archive_root.glob("*")) == archived_before


def test_relevant_reconciliation_resolution_stales_preview_without_import_writes(
    tmp_path, familybiz_row
):
    app = service(tmp_path)
    initial = make_workbook([familybiz_row])
    initial_preview = app.preview_import(initial, "initial.xlsx")
    app.commit_import(initial, initial_preview.preview_token, "initial.xlsx")

    changed = list(familybiz_row)
    changed[1] = -19.40
    unresolved_payload = make_workbook([changed])
    unresolved_preview = app.preview_import(unresolved_payload, "unresolved.xlsx")
    app.commit_import(unresolved_payload, unresolved_preview.preview_token, "unresolved.xlsx")
    old_case = app.database.open_reconciliation_cases()[0]

    proposed = make_workbook([list(familybiz_row)])
    preview = app.preview_import(proposed, "proposed-exact.xlsx")
    app.resolve_reconciliation(old_case["id"], {"resolution": "dismiss"})

    def counts():
        with app.database.session() as session:
            source_files = session.execute(text("SELECT COUNT(*) FROM source_files")).scalar_one()
        return {
            "transactions": app.database.count("transactions"),
            "source_records": app.database.count("source_records"),
            "source_files": source_files,
            "import_batches": app.database.count("import_batches"),
        }

    counts_after_resolution = counts()
    archive_after_resolution = sorted(path.name for path in app.settings.archive_root.glob("*"))
    with pytest.raises(PreviewStaleError, match="matching state changed"):
        app.commit_import(proposed, preview.preview_token, "proposed-exact.xlsx")
    assert counts() == counts_after_resolution
    assert sorted(path.name for path in app.settings.archive_root.glob("*")) == archive_after_resolution


def test_unrelated_planning_scenario_change_does_not_stale_import_preview(
    tmp_path, familybiz_row
):
    app = service(tmp_path)
    initial = make_workbook([familybiz_row])
    initial_preview = app.preview_import(initial, "initial.xlsx")
    app.commit_import(initial, initial_preview.preview_token, "initial.xlsx")

    changed = list(familybiz_row)
    changed[2] = "reconciliation candidate"
    payload = make_workbook([changed])
    preview = app.preview_import(payload, "proposed.xlsx")
    app.planning_service.create_manual_scenario("Unrelated plan", "2026-09")

    result = app.commit_import(payload, preview.preview_token, "proposed.xlsx")
    assert result.statistics.unresolved == 1


def test_plan_and_not_configured_registry_are_canonical(tmp_path, familybiz_row):
    app = service(tmp_path)
    payload = make_workbook([familybiz_row])
    first = app.preview_import(payload, "one.xlsx")
    second = app.preview_import(payload, "one.xlsx")

    with app.database.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA reverse_unordered_selects=ON")
    reordered_query_preview = app.preview_import(payload, "one.xlsx")

    assert first.decision_plan_version == "familybiz-decision-plan-v1"
    assert first.decision_plan_fingerprint == second.decision_plan_fingerprint
    assert first.decision_plan_json == second.decision_plan_json
    assert first.decision_plan_fingerprint == reordered_query_preview.decision_plan_fingerprint
    assert first.decision_plan_json == reordered_query_preview.decision_plan_json
    registry = json.loads(first.matching_baseline_json)["account_registry"]
    assert registry["configured"] is False
    assert registry["configuration_state"] == "not_configured"


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
    except PreviewStaleError as exc:
        assert "database matching state changed" in str(exc)
    else:
        raise AssertionError("stale preview was accepted")


def test_commit_of_invalid_file_is_validation_error_without_any_write(
    tmp_path, familybiz_row
):
    app = service(tmp_path)
    valid = make_workbook([familybiz_row])
    preview = app.preview_import(valid, "one.xlsx")

    with pytest.raises(ImportValidationError, match="validation failed"):
        app.commit_import(b"corrupt", preview.preview_token, "one.xlsx")
    assert app.database.count("transactions") == 0
    assert app.database.count("import_batches") == 0


def test_runtime_database_setup_records_alembic_revision(tmp_path):
    app = service(tmp_path)
    with app.database.connect() as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    current_head = ScriptDirectory.from_config(config).get_current_head()
    assert revision["version_num"] == current_head
