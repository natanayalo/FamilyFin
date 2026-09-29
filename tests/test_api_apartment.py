from __future__ import annotations

from sqlalchemy import select

from family_finance.models import PurchaseAlternativeInput
from family_finance.persistence.models import PlanningScenarioRevisionRow
from tests.test_api_auth import ApiTestClient, make_api
from tests.test_api_forecasts import _forecast_payload, _planning_scenario, _sign_in, _sign_in_isolated


def _apartment_payload(forecast_id: str, *, confirmed: bool = True, source_acknowledged: bool = False):
    def alternative(name: str, price: str, mortgage: str, gift: str, draw: str, month: int):
        return {
            "name": name,
            "forecast_role": "baseline",
            "purchase_month": month,
            "property_price": price,
            "family_gift": gift,
            "purchase_costs": [
                {"label": "Tax", "amount": "10.125"},
                {"label": "Inspection", "amount": "3.75"},
            ],
            "equity_requirement": {"mode": "percentage", "value": "0.2"},
            "mortgage": {"principal": mortgage, "annual_nominal_rate": "0.045", "term_months": 240},
            "pool_draws": [{"pool_name": "Household cash", "amount": draw}],
            "stopped_housing_line_ids": [],
            "housing_costs": [{"label": "Maintenance", "amount": "25.10"}],
            "confirmed": confirmed,
        }

    return {
        "name": "Apartment study",
        "forecast_id": forecast_id,
        "forecast_revision_number": 1,
        "guardrails": {
            "minimum_remaining_liquidity": "5.25",
            "maximum_housing_cost_to_income_ratio": "0.4",
        },
        "alternatives": [
            alternative("City", "500.123456789012345678", "300", "25", "100", 12),
            alternative("Suburb", "620", "350", "50", "120", 18),
        ],
        "notes": "exact decimal values",
        "source_quality_acknowledged": source_acknowledged,
    }


def _create_forecast(client, headers, scenario):
    body = _forecast_payload(client, headers, scenario)
    response = client.post("/api/v1/forecasts", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"], body


def test_apartment_preview_is_decimal_exact_and_matches_service_with_pinned_source(tmp_path):
    _, _, _, app = make_api(tmp_path, maximum_bytes=128 * 1024)
    with ApiTestClient(app, base_url="https://testserver") as client:
        headers = _sign_in(client)
        scenario = _planning_scenario(client, headers)
        forecast, _forecast_body = _create_forecast(client, headers, scenario)
        forecast_revision = client.get(
            f"/api/v1/forecasts/{forecast['forecast_id']}/revisions/1", headers=headers
        ).json()["data"]
        payload = _apartment_payload(forecast["forecast_id"])

        options = client.get(
            "/api/v1/apartment/options",
            params={"forecast_id": forecast["forecast_id"], "forecast_revision_number": 1},
            headers=headers,
        )
        assert options.status_code == 200, options.text
        source = options.json()["data"]
        assert source["forecast_revision"]["assumption_hash"] == forecast_revision["assumption_hash"]
        assert source["planning_source"]["at_creation"]["revision_number"] == 1
        assert source["planning_source"]["at_creation"]["revision_id"] == forecast["source_revision_id"]

        preview_payload = {key: value for key, value in payload.items() if key != "name"}
        preview = client.post("/api/v1/apartment/previews", json=preview_payload, headers=headers)
        assert preview.status_code == 200, preview.text
        actual = preview.json()["data"]
        service = app.state.services.apartment_planning_service
        expected = service.project_draft(
            forecast["forecast_id"],
            [PurchaseAlternativeInput.model_validate(item) for item in payload["alternatives"]],
            forecast_revision_number=1,
            guardrails=payload["guardrails"],
        )
        assert actual["assumption_hash"] == expected.assumption_hash
        assert actual["projections"][0]["purchase_price"] == "500.123456789012345678"
        assert actual["projections"][0]["funding_gap"] == str(expected.projections[0].funding_gap)
        assert actual["projections"][0]["mortgage_schedule"][0]["payment"] == str(
            expected.projections[0].mortgage_schedule[0].payment
        )
        assert actual["projections"][0]["source_projection"]["source_revision_number"] == 1
        saved = client.post("/api/v1/apartment/studies", json=payload, headers=headers)
        assert saved.status_code == 201, saved.text
        study_id = saved.json()["data"]["study_id"]
        saved_revision = client.get(
            f"/api/v1/apartment/studies/{study_id}/revisions/1", headers=headers
        ).json()["data"]
        assert saved_revision["assumption_hash"] == actual["assumption_hash"]

        numeric_json_amount = {**preview_payload, "alternatives": [{
            **payload["alternatives"][0], "property_price": 500.12,
        }, payload["alternatives"][1]]}
        rejected = client.post("/api/v1/apartment/previews", json=numeric_json_amount, headers=headers)
        assert rejected.status_code == 422
        invalid_term = {**preview_payload, "alternatives": [{
            **payload["alternatives"][0], "mortgage": {**payload["alternatives"][0]["mortgage"], "term_months": 11},
        }, payload["alternatives"][1]]}
        assert client.post("/api/v1/apartment/previews", json=invalid_term, headers=headers).status_code == 422
        negative_price = {**preview_payload, "alternatives": [{
            **payload["alternatives"][0], "property_price": "-1",
        }, payload["alternatives"][1]]}
        assert client.post("/api/v1/apartment/previews", json=negative_price, headers=headers).status_code == 422


def test_apartment_provisional_ack_history_stale_conflict_clone_archive_and_restore(tmp_path):
    _, database, _, app = make_api(tmp_path, maximum_bytes=128 * 1024)
    with ApiTestClient(app, base_url="https://testserver") as client:
        sam = _sign_in_isolated(client, "sam", "Long-test-password-One!")
        lee = _sign_in_isolated(client, "lee", "Long-test-password-Two!")
        scenario = _planning_scenario(client, sam)
        with database.write_session() as session:
            planning_revision = session.execute(
                select(PlanningScenarioRevisionRow).where(
                    PlanningScenarioRevisionRow.scenario_id == scenario["scenario_id"],
                    PlanningScenarioRevisionRow.revision_number == 1,
                )
            ).scalar_one()
            planning_revision.provisional = True
            planning_revision.issue_codes_json = '["PROVISIONAL_SOURCE"]'
        forecast_payload = _forecast_payload(client, sam, scenario)
        forecast_payload["provisional_acknowledged"] = True
        created_forecast = client.post("/api/v1/forecasts", json=forecast_payload, headers=sam)
        assert created_forecast.status_code == 201, created_forecast.text
        forecast = created_forecast.json()["data"]
        forecast_id = forecast["forecast_id"]
        forecast_hash = client.get(f"/api/v1/forecasts/{forecast_id}/revisions/1", headers=sam).json()["data"]["assumption_hash"]
        payload = _apartment_payload(forecast["forecast_id"])

        missing_alternative_confirmation = {
            **payload,
            "alternatives": [{**payload["alternatives"][0], "confirmed": False}, payload["alternatives"][1]],
            "source_quality_acknowledged": True,
        }
        unconfirmed = client.post("/api/v1/apartment/studies", json=missing_alternative_confirmation, headers=sam)
        assert unconfirmed.status_code == 422
        assert unconfirmed.json()["error"]["code"] == "QUALITY_ACKNOWLEDGEMENT_REQUIRED"

        missing_source_ack = {**payload, "source_quality_acknowledged": False}
        refused = client.post("/api/v1/apartment/studies", json=missing_source_ack, headers=sam)
        assert refused.status_code == 422
        assert refused.json()["error"]["code"] == "QUALITY_ACKNOWLEDGEMENT_REQUIRED"

        payload["source_quality_acknowledged"] = True
        created = client.post("/api/v1/apartment/studies", json=payload, headers=sam)
        assert created.status_code == 201, created.text
        study = created.json()["data"]
        study_id = study["study_id"]
        assert study["forecast_revision_number"] == 1
        assert study["forecast_assumption_hash"] == forecast_hash
        saved_projection = client.get(
            f"/api/v1/apartment/studies/{study_id}/revisions/1/projection", headers=sam
        )
        assert saved_projection.status_code == 200, saved_projection.text
        saved_projection_data = saved_projection.json()["data"]
        assert saved_projection_data["snapshot"]["source_quality_acknowledged"] is True
        assert saved_projection_data["source_verification"]["at_creation"]["provisional"] is True
        assert saved_projection_data["draft"]["source_quality_warning"] is True

        first = client.get(f"/api/v1/apartment/studies/{study_id}/revisions/1", headers=sam).json()["data"]
        changed_alternatives = [dict(item) for item in payload["alternatives"]]
        changed_alternatives[0] = {**changed_alternatives[0], "property_price": "510", "confirmed": True}
        saved = client.post(
            f"/api/v1/apartment/studies/{study_id}/revisions",
            json={
                "expected_revision_number": 1,
                "guardrails": payload["guardrails"],
                "alternatives": changed_alternatives,
                "notes": "revision two",
                "source_quality_acknowledged": True,
            },
            headers=sam,
        )
        assert saved.status_code == 201, saved.text
        assert saved.json()["data"]["revision_number"] == 2
        assert saved.json()["data"]["forecast_assumption_hash"] == forecast_hash

        stale = client.post(
            f"/api/v1/apartment/studies/{study_id}/revisions",
            json={
                "expected_revision_number": 1,
                "guardrails": payload["guardrails"],
                "alternatives": payload["alternatives"],
                "source_quality_acknowledged": True,
            },
            headers=lee,
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "STALE_REVISION"
        assert stale.json()["error"]["fields"]["current_revision_number"] == ["2"]

        forecast_revision = client.post(
            f"/api/v1/forecasts/{forecast_id}/revisions",
            json={
                "expected_revision_number": 1,
                "starting_pools": forecast_payload["starting_pools"],
                "cases": [{**item, "annual_return_rate": "0"} for item in forecast_payload["cases"]],
                "notes": "newer forecast assumptions",
                "provisional_acknowledged": True,
            },
            headers=sam,
        )
        assert forecast_revision.status_code == 201, forecast_revision.text
        latest_study = client.get(f"/api/v1/apartment/studies/{study_id}", headers=sam).json()["data"]
        assert latest_study["forecast_revision_number"] == 1
        assert latest_study["forecast_assumption_hash"] == forecast_hash

        restored = client.post(
            f"/api/v1/apartment/studies/{study_id}/revisions/1/restore",
            json={"expected_revision_number": 2, "source_quality_acknowledged": True},
            headers=lee,
        )
        assert restored.status_code == 201, restored.text
        assert restored.json()["data"]["revision_number"] == 3
        after_restore = client.get(f"/api/v1/apartment/studies/{study_id}/revisions/1", headers=sam).json()["data"]
        assert after_restore["assumption_hash"] == first["assumption_hash"]
        assert after_restore["alternatives"][0]["property_price"] == first["alternatives"][0]["property_price"]

        clone = client.post(f"/api/v1/apartment/studies/{study_id}/clone", json={}, headers=sam)
        assert clone.status_code == 201, clone.text
        clone_summary = clone.json()["data"]
        assert clone_summary["clone_of_study_id"] == study_id
        assert clone_summary["forecast_revision_number"] == 1
        archived = client.post(f"/api/v1/apartment/studies/{study_id}/archive", json={"archived": True}, headers=lee)
        assert archived.status_code == 200 and archived.json()["data"]["archived"] is True
        assert all(item["study_id"] != study_id for item in client.get("/api/v1/apartment/studies", headers=sam).json()["data"])
        unarchived = client.post(f"/api/v1/apartment/studies/{study_id}/archive", json={"archived": False}, headers=sam)
        assert unarchived.status_code == 200 and unarchived.json()["data"]["archived"] is False
