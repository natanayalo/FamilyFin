from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from family_finance.api.auth import SESSION_COOKIE_NAME
from family_finance.persistence.models import PlanningScenarioRevisionRow
from tests.test_api_auth import ApiTestClient, make_api


def _sign_in(client: ApiTestClient, username="sam", password="Long-test-password-One!"):
    response = client.post(
        "/api/v1/auth/session",
        json={"username": username, "password": password},
        headers={"Origin": "https://testserver"},
    )
    assert response.status_code == 200
    return {"Origin": "https://testserver", "X-CSRF-Token": response.json()["data"]["csrf_token"]}


def _sign_in_isolated(client: ApiTestClient, username: str, password: str):
    headers = _sign_in(client, username, password)
    token = client.cookies.get(SESSION_COOKIE_NAME)
    assert token
    client.cookies.clear()
    return {**headers, "Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def _planning_scenario(client: ApiTestClient, headers, *, start_month="2026-01-01"):
    response = client.post(
        "/api/v1/planning/scenarios",
        json={
            "name": "Forecast source",
            "currency": "ILS",
            "start_month": start_month,
            "items": [
                {
                    "kind": "income", "label": "Salary", "amount": "1000", "frequency": "monthly",
                    "start_month": start_month, "end_month": "2026-12-01",
                },
                {
                    "kind": "expense", "label": "Household", "amount": "500", "frequency": "monthly",
                    "start_month": start_month, "end_month": "2026-12-01",
                },
                {
                    "kind": "savings_contribution", "label": "Monthly transfer", "amount": "100.10",
                    "frequency": "monthly", "start_month": start_month, "end_month": "2026-12-01",
                },
            ],
            "notes": "exact immutable source",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _forecast_payload(client: ApiTestClient, headers, scenario, *, opening="250.10", stale=False):
    revision = client.get(
        f"/api/v1/planning/scenarios/{scenario['scenario_id']}/revisions/1", headers=headers
    ).json()["data"]
    contribution = next(item for item in revision["items"] if item["kind"] == "savings_contribution")
    pools = [{
        "name": "Household cash",
        "pool_type": "cash",
        "opening_balance": opening,
        "as_of_date": scenario["start_month"],
        "source_stale": stale,
        "source_quality_acknowledged": stale,
    }]
    rates = {"conservative": "0", "baseline": "0.12", "optimistic": "0.24"}
    cases = []
    for role, rate in rates.items():
        cases.append({
            "role": role,
            "annual_return_rate": rate,
            "routes": [{"source_item_id": contribution["id"], "pool_name": "Household cash"}],
            "sweep_enabled": True,
            "sweep_pool_name": "Household cash",
            "adjustments": [],
            "events": [],
            "confirmed": True,
        })
    return {
        "name": "Family savings",
        "scenario_id": scenario["scenario_id"],
        "source_revision_number": 1,
        "starting_pools": pools,
        "cases": cases,
        "notes": "baseline assumptions",
    }


def test_forecast_api_requires_auth_and_keeps_decimal_strings(tmp_path):
    _, _, _, app = make_api(tmp_path, maximum_bytes=64 * 1024)
    with ApiTestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/v1/forecasts").status_code == 401
        headers = _sign_in(client)
        scenario = _planning_scenario(client, headers)
        payload = _forecast_payload(client, headers, scenario)
        preview = client.post("/api/v1/forecasts/previews", json={key: value for key, value in payload.items() if key != "name"}, headers=headers)
        assert preview.status_code == 200, preview.text
        data = preview.json()["data"]
        conservative = data["projections"]["conservative"]["months"][0]
        assert conservative["pools"][0]["closing_balance"] == "750.10"
        assert data["projections"]["baseline"]["currency"] == "ILS"
        assert data["source_verification"]["at_creation"]["revision_number"] == 1
        assert data["source_verification"]["current"]["revision_number"] == 1

        invalid = {**payload, "starting_pools": [{**payload["starting_pools"][0], "opening_balance": 250.1}]}
        rejected = client.post("/api/v1/forecasts", json=invalid, headers=headers)
        assert rejected.status_code == 422


def test_forecast_create_save_restore_clone_and_archive_are_immutable(tmp_path):
    _, _, _, app = make_api(tmp_path, maximum_bytes=64 * 1024)
    with ApiTestClient(app, base_url="https://testserver") as client:
        headers = _sign_in(client)
        scenario = _planning_scenario(client, headers)
        payload = _forecast_payload(client, headers, scenario)
        created = client.post("/api/v1/forecasts", json=payload, headers=headers)
        assert created.status_code == 201, created.text
        forecast_id = created.json()["data"]["forecast_id"]
        first_projection = client.get(
            f"/api/v1/forecasts/{forecast_id}/revisions/1/projection", headers=headers
        )
        assert first_projection.status_code == 200, first_projection.text
        first = first_projection.json()["data"]
        assert first["snapshot"]["source_revision_number"] == 1
        assert first["draft"]["projections"]["conservative"]["months"][0]["ending_balance"] == "750.10"

        revision_body = {
            "expected_revision_number": 1,
            "starting_pools": payload["starting_pools"],
            "cases": [{**case, "annual_return_rate": "0"} for case in payload["cases"]],
            "notes": "revision two",
        }
        saved = client.post(
            f"/api/v1/forecasts/{forecast_id}/revisions", json=revision_body, headers=headers
        )
        assert saved.status_code == 201, saved.text
        assert saved.json()["data"]["revision_number"] == 2
        history = client.get(f"/api/v1/forecasts/{forecast_id}/revisions", headers=headers).json()["data"]
        assert [item["revision_number"] for item in history] == [1, 2]
        assert history[0]["assumption_hash"] != history[1]["assumption_hash"]

        restored = client.post(
            f"/api/v1/forecasts/{forecast_id}/revisions/1/restore",
            json={"expected_revision_number": 2},
            headers=headers,
        )
        assert restored.status_code == 201, restored.text
        assert restored.json()["data"]["revision_number"] == 3
        old_after_restore = client.get(
            f"/api/v1/forecasts/{forecast_id}/revisions/1", headers=headers
        ).json()["data"]
        assert old_after_restore["cases"][1]["annual_return_rate"] == "0.12"

        clone = client.post(f"/api/v1/forecasts/{forecast_id}/clone", json={}, headers=headers)
        assert clone.status_code == 201, clone.text
        assert clone.json()["data"]["clone_of_forecast_id"] == forecast_id
        archived = client.post(
            f"/api/v1/forecasts/{forecast_id}/archive", json={"archived": True}, headers=headers
        )
        assert archived.status_code == 200 and archived.json()["data"]["archived"] is True
        active = client.get("/api/v1/forecasts", headers=headers).json()["data"]
        assert all(item["forecast_id"] != forecast_id for item in active)
        archived = client.post(
            f"/api/v1/forecasts/{forecast_id}/archive", json={"archived": False}, headers=headers
        )
        assert archived.json()["data"]["archived"] is False

        expected = app.state.services.savings_forecast_service.project_draft(
            scenario["scenario_id"],
            [
                {"name": "Household cash", "pool_type": "cash", "opening_balance": Decimal("250.10"), "as_of_date": scenario["start_month"]}
            ],
            [
                {
                    **case,
                    "annual_return_rate": Decimal(case["annual_return_rate"]),
                }
                for case in payload["cases"]
            ],
            source_revision_number=1,
        )
        assert first["draft"]["projections"]["optimistic"]["months"][0]["ending_balance"] == str(
            expected.projections[next(role for role in expected.projections if role.value == "optimistic")].months[0].ending_balance
        )


def test_forecast_seed_pins_exact_net_worth_revision_and_requires_stale_ack(tmp_path):
    _, _, _, app = make_api(tmp_path, maximum_bytes=64 * 1024)
    with ApiTestClient(app, base_url="https://testserver") as client:
        headers = _sign_in(client)
        account = client.post(
            "/api/v1/net-worth/accounts",
            json={
                "account_key": "checking", "display_name": "Checking", "side": "asset",
                "category": "cash", "liquidity": "liquid", "active_from": "2020-01-01",
                "stale_after_days": 1,
            },
            headers=headers,
        )
        assert account.status_code == 201
        saved = client.post(
            "/api/v1/net-worth/snapshots",
            json={
                "snapshot_date": "2026-08-31", "quality_acknowledged": True,
                "balances": [{"account_key": "checking", "amount_ils": "1200.45", "valuation_date": "2026-08-01"}],
            },
            headers=headers,
        )
        assert saved.status_code == 201, saved.text
        revision_id = saved.json()["data"]["revision_id"]
        seeded = client.post(
            "/api/v1/forecasts/net-worth-seeds",
            json={"snapshot_revision_id": revision_id, "account_keys": ["checking"], "pool_types": {"checking": "cash"}},
            headers=headers,
        )
        assert seeded.status_code == 200, seeded.text
        pool = seeded.json()["data"][0]
        assert pool["opening_balance"] == "1200.45"
        assert pool["snapshot_revision_id"] == revision_id
        assert pool["stale"] is True

        scenario = _planning_scenario(client, headers, start_month="2026-09-01")
        payload = _forecast_payload(client, headers, scenario, stale=True)
        payload["starting_pools"] = [{
            "name": pool["name"],
            "pool_type": pool["pool_type"],
            "opening_balance": pool["opening_balance"],
            "as_of_date": pool["as_of_date"],
            "net_worth_account_key": pool["account_key"],
            "net_worth_snapshot_revision_id": pool["snapshot_revision_id"],
            "source_valuation_date": pool["valuation_date"],
            "source_stale": pool["stale"],
            "source_quality_acknowledged": False,
        }]
        payload["cases"] = [{
            **case,
            "routes": [{**route, "pool_name": pool["name"]} for route in case["routes"]],
            "sweep_pool_name": pool["name"],
        } for case in payload["cases"]]
        refused = client.post("/api/v1/forecasts", json=payload, headers=headers)
        assert refused.status_code == 422
        assert refused.json()["error"]["code"] == "QUALITY_ACKNOWLEDGEMENT_REQUIRED"
        payload["starting_pools"][0]["source_quality_acknowledged"] = True
        accepted = client.post("/api/v1/forecasts", json=payload, headers=headers)
        assert accepted.status_code == 201, accepted.text

        tampered = {**payload, "starting_pools": [{**payload["starting_pools"][0], "source_stale": False}]}
        rejected_tampering = client.post("/api/v1/forecasts", json=tampered, headers=headers)
        assert rejected_tampering.status_code == 422
        assert rejected_tampering.json()["error"]["code"] == "VALIDATION_ERROR"


def test_provisional_source_acknowledgement_and_two_user_stale_write_conflict(tmp_path):
    _, database, _, app = make_api(tmp_path, maximum_bytes=64 * 1024)
    with ApiTestClient(app, base_url="https://testserver") as client:
        sam = _sign_in_isolated(client, "sam", "Long-test-password-One!")
        lee = _sign_in_isolated(client, "lee", "Long-test-password-Two!")
        scenario = _planning_scenario(client, sam)
        with database.write_session() as session:
            revision = session.execute(
                select(PlanningScenarioRevisionRow).where(
                    PlanningScenarioRevisionRow.scenario_id == scenario["scenario_id"],
                    PlanningScenarioRevisionRow.revision_number == 1,
                )
            ).scalar_one()
            revision.provisional = True
            revision.issue_codes_json = '["PROVISIONAL_SOURCE"]'

        payload = _forecast_payload(client, sam, scenario)
        missing_ack = client.post("/api/v1/forecasts", json=payload, headers=sam)
        assert missing_ack.status_code == 422
        assert missing_ack.json()["error"]["code"] == "QUALITY_ACKNOWLEDGEMENT_REQUIRED"
        payload["provisional_acknowledged"] = True
        created = client.post("/api/v1/forecasts", json=payload, headers=sam)
        assert created.status_code == 201, created.text
        forecast_id = created.json()["data"]["forecast_id"]

        changed = client.post(
            f"/api/v1/forecasts/{forecast_id}/revisions",
            json={
                "expected_revision_number": 1,
                "starting_pools": payload["starting_pools"],
                    "cases": [{**case, "annual_return_rate": "0"} for case in payload["cases"]],
                    "provisional_acknowledged": True,
            },
            headers=lee,
        )
        assert changed.status_code == 201, changed.text
        conflict = client.post(
            f"/api/v1/forecasts/{forecast_id}/revisions",
            json={
                "expected_revision_number": 1,
                "starting_pools": payload["starting_pools"],
                    "cases": payload["cases"],
                    "provisional_acknowledged": True,
            },
            headers=sam,
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "STALE_REVISION"
