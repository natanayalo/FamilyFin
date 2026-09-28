from __future__ import annotations

import json

from family_finance.api.auth import SESSION_COOKIE_NAME
from tests.test_api_auth import ApiTestClient, make_api


def _sign_in_as(client: ApiTestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/session",
        json={"username": username, "password": password},
        headers={"Origin": "https://testserver"},
    )
    assert response.status_code == 200, response.text
    token = client.cookies.get(SESSION_COOKIE_NAME)
    assert token
    csrf = response.json()["data"]["csrf_token"]
    client.cookies.clear()
    return {"Origin": "https://testserver", "X-CSRF-Token": csrf, "Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def _item(
    kind: str,
    label: str,
    amount: str,
    *,
    category: str | None = None,
    frequency: str = "monthly",
    start: str = "2026-10-01",
    end: str = "2027-09-01",
    occurrence: str | None = None,
):
    return {
        "kind": kind,
        "label": label,
        "category": category,
        "amount": amount,
        "frequency": frequency,
        "start_month": start if frequency == "monthly" else None,
        "end_month": end if frequency == "monthly" else None,
        "occurrence_month": occurrence if frequency == "one_time" else None,
    }


def _revision_item(item: dict, *, amount: str | None = None):
    return {
        "source_item_id": item["id"],
        "kind": item["kind"],
        "label": item["label"],
        "category": item["category"],
        "amount": amount if amount is not None else item["amount"],
        "frequency": item["frequency"],
        "start_month": item["start_month"],
        "end_month": item["end_month"],
        "occurrence_month": item["occurrence_month"],
    }


def _create(client: ApiTestClient, headers: dict[str, str], *, name: str = "Baseline"):
    return client.post(
        "/api/v1/planning/scenarios",
        json={
            "name": name,
            "currency": "ILS",
            "start_month": "2026-10",
            "items": [
                _item("income", "Salary", "10000.25", category="salary"),
                _item("expense", "Rent", "2500", category="housing"),
                _item("savings_contribution", "Savings transfer", "1000"),
                _item("savings_withdrawal", "One-time transfer", "100", frequency="one_time", occurrence="2026-11-01"),
            ],
        },
        headers=headers,
    )


def test_planning_api_projection_matches_python_and_keeps_exact_decimal_strings(tmp_path):
    _, _, _, app = make_api(tmp_path, maximum_bytes=256_000)
    with ApiTestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/v1/planning/scenarios").status_code == 401
        headers = _sign_in_as(client, "sam", "Long-test-password-One!")
        created = _create(client, headers)
        assert created.status_code == 201, created.text
        scenario = created.json()["data"]
        assert scenario["start_month"] == "2026-10-01"
        assert scenario["currency"] == "ILS"
        manual_revision = client.get(
            f"/api/v1/planning/scenarios/{scenario['scenario_id']}/revisions/1",
            headers=headers,
        ).json()["data"]
        assert all(item["origin"] == "manual" for item in manual_revision["items"])
        assert all(item["provenance"] == {} for item in manual_revision["items"])
        assert all(item["contributor_transaction_ids"] == [] for item in manual_revision["items"])

        forged_manual = client.post(
            "/api/v1/planning/scenarios",
            json={
                "name": "Forged provenance",
                "currency": "ILS",
                "start_month": "2026-10",
                "items": [
                    {**_item("expense", "Rent", "10"), "origin": "csv", "provenance": {"forged": True}}
                ],
            },
            headers=headers,
        )
        assert forged_manual.status_code == 422

        saved_projection = client.get(f"/api/v1/planning/scenarios/{scenario['scenario_id']}/projection", headers=headers)
        python_projection = app.state.services.planning_service.project_draft(scenario["scenario_id"])
        assert saved_projection.status_code == 200
        first = saved_projection.json()["data"]["months"][0]
        assert first["income"] == str(python_projection.months[0].income) == "10000.25"
        assert first["expenses"] == str(python_projection.months[0].expenses) == "2500"
        assert first["operating_surplus"] == str(python_projection.months[0].operating_surplus) == "7500.25"
        assert first["cash_remaining_after_savings"] == "6500.25"
        november = saved_projection.json()["data"]["months"][1]
        assert november["savings_withdrawals"] == "100"
        assert len(saved_projection.json()["data"]["months"]) == 12

        numeric_amount = client.post(
            "/api/v1/planning/scenarios",
            json={"name": "String amount", "currency": "ILS", "start_month": "2026-10", "items": [_item("expense", "Rent", "25")]},
            headers=headers,
        )
        assert numeric_amount.status_code == 201  # String amounts remain accepted as supplied.
        bad_body = {"name": "Wrong type", "currency": "ILS", "start_month": "2026-10", "items": [_item("expense", "Rent", "25")]}
        bad_body["items"][0]["amount"] = 25
        invalid = client.post("/api/v1/planning/scenarios", json=bad_body, headers=headers)
        assert invalid.status_code == 422


def test_history_seed_requires_acknowledgement_and_persists_completeness_evidence(tmp_path):
    _, _, _, app = make_api(tmp_path, maximum_bytes=256_000)
    with ApiTestClient(app, base_url="https://testserver") as client:
        headers = _sign_in_as(client, "sam", "Long-test-password-One!")
        preview = client.post(
            "/api/v1/planning/seeds/history/previews",
            json={"name": "History", "currency": "ILS", "start_month": "2026-10", "history_months": 3},
            headers=headers,
        )
        assert preview.status_code == 200, preview.text
        data = preview.json()["data"]
        assert data["provisional"] is True
        assert len(data["completeness_snapshot"]) == 3

        blocked = client.post(
            "/api/v1/planning/seeds/history/commits",
            json={"preview_token": data["preview_token"], "acknowledge_provisional": False},
            headers=headers,
        )
        assert blocked.status_code == 422
        assert blocked.json()["error"]["code"] == "QUALITY_ACKNOWLEDGEMENT_REQUIRED"

        committed = client.post(
            "/api/v1/planning/seeds/history/commits",
            json={"preview_token": data["preview_token"], "acknowledge_provisional": True},
            headers=headers,
        )
        assert committed.status_code == 201, committed.text
        scenario_id = committed.json()["data"]["scenario_id"]
        revision = client.get(f"/api/v1/planning/scenarios/{scenario_id}/revisions/1", headers=headers).json()["data"]
        assert revision["provisional"] is True
        assert revision["issue_codes"] == data["issue_codes"]
        assert revision["completeness_snapshot"] == data["completeness_snapshot"]
        expected = app.state.services.planning_service.get_revision(scenario_id)
        assert revision["revision_id"] == expected.revision_id


def test_stale_revision_conflict_has_current_revision_and_two_users_cannot_overwrite(tmp_path):
    _, _, _, app = make_api(tmp_path, maximum_bytes=256_000)
    with ApiTestClient(app, base_url="https://testserver") as client:
        sam = _sign_in_as(client, "sam", "Long-test-password-One!")
        lee = _sign_in_as(client, "lee", "Long-test-password-Two!")
        created = _create(client, sam)
        assert created.status_code == 201, created.text
        scenario_id = created.json()["data"]["scenario_id"]
        lee_revision = client.get(f"/api/v1/planning/scenarios/{scenario_id}/revisions/1", headers=lee).json()["data"]
        sam_revision = client.get(f"/api/v1/planning/scenarios/{scenario_id}/revisions/1", headers=sam).json()["data"]
        assert lee_revision["revision_id"] == sam_revision["revision_id"]

        items = [_revision_item(item) for item in lee_revision["items"]]
        salary = next(item for item in items if item["label"] == "Salary")
        salary["amount"] = "11000.75"
        winner = client.post(
            f"/api/v1/planning/scenarios/{scenario_id}/revisions",
            json={"expected_revision_number": 1, "items": items, "notes": "updated by Lee"},
            headers=lee,
        )
        assert winner.status_code == 201, winner.text
        assert winner.json()["data"]["revision_number"] == 2

        stale_items = [_revision_item(item) for item in sam_revision["items"]]
        next(item for item in stale_items if item["label"] == "Salary")["amount"] = "12000"
        stale = client.post(
            f"/api/v1/planning/scenarios/{scenario_id}/revisions",
            json={"expected_revision_number": 1, "items": stale_items, "notes": "stale edit"},
            headers=sam,
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "STALE_REVISION"
        assert stale.json()["error"]["fields"]["current_revision_number"] == ["2"]

        history = client.get(f"/api/v1/planning/scenarios/{scenario_id}/revisions", headers=sam).json()["data"]
        assert [item["revision_number"] for item in history] == [1, 2]
        assert next(item for item in history[0]["items"] if item["label"] == "Salary")["amount"] == "10000.25"
        assert next(item for item in history[1]["items"] if item["label"] == "Salary")["amount"] == "11000.75"


def test_revision_cannot_forge_source_provenance(tmp_path, planning_csv_bytes):
    _, _, _, app = make_api(tmp_path, maximum_bytes=256_000)
    with ApiTestClient(app, base_url="https://testserver") as client:
        headers = _sign_in_as(client, "sam", "Long-test-password-One!")
        preview = client.post(
            "/api/v1/planning/seeds/csv/previews",
            data={"name": "Imported plan", "currency": "ILS", "start_month": "2026-10"},
            files={"file": ("planning.csv", planning_csv_bytes, "text/csv")},
            headers=headers,
        )
        assert preview.status_code == 200, preview.text
        preview_data = preview.json()["data"]
        mappings = [
            {"csv_category": item["csv_category"], "analysis_category": None}
            for item in preview_data["mappings"]
        ]
        committed = client.post(
            "/api/v1/planning/seeds/csv/commits",
            data={
                "preview_token": preview_data["preview_token"],
                "mappings_json": json.dumps({"mappings": mappings}),
                "acknowledge_provisional": "true",
            },
            files={"file": ("planning.csv", planning_csv_bytes, "text/csv")},
            headers=headers,
        )
        assert committed.status_code == 201, committed.text
        scenario_id = committed.json()["data"]["scenario_id"]
        base = client.get(
            f"/api/v1/planning/scenarios/{scenario_id}/revisions/1", headers=headers
        ).json()["data"]
        source = next(item for item in base["items"] if item["kind"] == "expense")
        lineage_fields = (
            "origin", "source_range", "source_row", "policy_version", "completeness_codes",
            "contributor_transaction_ids", "provenance", "notes",
        )
        original_lineage = {field: source[field] for field in lineage_fields}
        editable = _revision_item(source, amount="999.25")
        forged = {
            **editable,
            "origin": "manual",
            "source_range": "R999C1:C8",
            "source_row": 999,
            "policy_version": "forged-v99",
            "completeness_codes": ["FORGED"],
            "contributor_transaction_ids": [999999],
            "provenance": {"forged": True},
            "notes": [{"forged": True}],
        }
        rejected = client.post(
            f"/api/v1/planning/scenarios/{scenario_id}/revisions",
            json={"expected_revision_number": 1, "items": [forged]},
            headers=headers,
        )
        assert rejected.status_code == 422
        current = client.get(
            f"/api/v1/planning/scenarios/{scenario_id}", headers=headers
        ).json()["data"]
        assert current["current_revision_number"] == 1

        saved = client.post(
            f"/api/v1/planning/scenarios/{scenario_id}/revisions",
            json={
                "expected_revision_number": 1,
                "items": [editable],
                "acknowledge_provisional": True,
            },
            headers=headers,
        )
        assert saved.status_code == 201, saved.text
        updated = saved.json()["data"]["items"][0]
        assert updated["amount"] == "999.25"
        assert {field: updated[field] for field in lineage_fields} == original_lineage


def test_csv_seed_requires_explicit_mappings_and_ack_then_rejects_duplicate(tmp_path, planning_csv_bytes):
    _, _, _, app = make_api(tmp_path, maximum_bytes=256_000)
    with ApiTestClient(app, base_url="https://testserver") as client:
        headers = _sign_in_as(client, "sam", "Long-test-password-One!")
        preview = client.post(
            "/api/v1/planning/seeds/csv/previews",
            data={"name": "Imported plan", "currency": "ILS", "start_month": "2026-10"},
            files={"file": ("planning.csv", planning_csv_bytes, "text/csv")},
            headers=headers,
        )
        assert preview.status_code == 200, preview.text
        data = preview.json()["data"]
        assert data["duplicate_scenario_id"] is None
        mappings = [{"csv_category": item["csv_category"], "analysis_category": None} for item in data["mappings"]]
        mapping_body = {"mappings": mappings}
        missing_ack = client.post(
            "/api/v1/planning/seeds/csv/commits",
            data={"preview_token": data["preview_token"], "mappings_json": json.dumps(mapping_body), "acknowledge_provisional": "false"},
            files={"file": ("planning.csv", planning_csv_bytes, "text/csv")},
            headers=headers,
        )
        assert missing_ack.status_code == 422
        assert missing_ack.json()["error"]["code"] == "QUALITY_ACKNOWLEDGEMENT_REQUIRED", missing_ack.text
        committed = client.post(
            "/api/v1/planning/seeds/csv/commits",
            data={"preview_token": data["preview_token"], "mappings_json": json.dumps(mapping_body), "acknowledge_provisional": "true"},
            files={"file": ("planning.csv", planning_csv_bytes, "text/csv")},
            headers=headers,
        )
        assert committed.status_code == 201, committed.text
        revision = app.state.services.planning_service.get_revision(committed.json()["data"]["scenario_id"])
        assert revision.provisional
        assert "CSV_CATEGORY_UNMAPPED" in revision.issue_codes
        assert all(item.category is None for item in revision.items if item.kind.value == "expense")

        duplicate_preview = client.post(
            "/api/v1/planning/seeds/csv/previews",
            data={"name": "Imported plan", "currency": "ILS", "start_month": "2026-10"},
            files={"file": ("planning.csv", planning_csv_bytes, "text/csv")},
            headers=headers,
        )
        duplicate_data = duplicate_preview.json()["data"]
        assert duplicate_data["duplicate_scenario_id"] == committed.json()["data"]["scenario_id"]
        duplicate = client.post(
            "/api/v1/planning/seeds/csv/commits",
            data={"preview_token": duplicate_data["preview_token"], "mappings_json": json.dumps(mapping_body), "acknowledge_provisional": "true"},
            files={"file": ("planning.csv", planning_csv_bytes, "text/csv")},
            headers=headers,
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "DUPLICATE_SEED"


def test_planning_schedule_and_currency_validation(tmp_path):
    _, _, _, app = make_api(tmp_path)
    with ApiTestClient(app, base_url="https://testserver") as client:
        headers = _sign_in_as(client, "sam", "Long-test-password-One!")
        invalid_month = client.post(
            "/api/v1/planning/scenarios",
            json={"name": "Bad schedule", "currency": "ILS", "start_month": "2026-10", "items": [_item("expense", "Rent", "10", start="2025-10-01")]},
            headers=headers,
        )
        assert invalid_month.status_code == 422
        invalid_frequency = client.post(
            "/api/v1/planning/scenarios",
            json={"name": "Bad frequency", "currency": "ILS", "start_month": "2026-10", "items": [_item("expense", "Rent", "10", frequency="weekly")]},
            headers=headers,
        )
        assert invalid_frequency.status_code == 422
