from __future__ import annotations

import asyncio

from sqlalchemy import select

from family_finance.persistence.models import ActorAuditEventRow
from tests.conftest import make_workbook
from tests.test_api_auth import ApiTestClient, make_api

ORIGIN = "https://testserver"
LOGIN = {"username": "sam", "password": "Long-test-password-One!"}


def _rows():
    return [
        ["09/09/2026", -75, "Synthetic market", "09/09/2026", "purchase", "food", "ILS", "ILS", -75],
        ["11/09/2026", 250, "Synthetic refund", "11/09/2026", "refund", "refund", "ILS", "ILS", 250],
    ]


def _sign_in(client):
    response = client.post("/api/v1/auth/session", json=LOGIN, headers={"Origin": ORIGIN})
    assert response.status_code == 200
    data = response.json()["data"]
    return data["csrf_token"]


def _import_rows(client):
    service = client.app.state.services
    workbook = make_workbook(_rows(), provider="בנק", reference="classification-bank", report_end="30/09/2026")
    preview = service.preview_import(workbook, "classification-fixture.xlsx")
    service.commit_import(workbook, preview.preview_token, "classification-fixture.xlsx")


def test_classification_queue_filters_coverage_override_clear_and_rules(tmp_path):
    _, database, _, app = make_api(tmp_path)
    with ApiTestClient(app, base_url=ORIGIN) as client:
        csrf = _sign_in(client)
        _import_rows(client)

        queue = client.get(
            "/api/v1/classification/review-queue",
            params={
                "month": "2026-09",
                "currency": "ILS",
                "economic_class": "consumption",
                "include_resolved": "true",
            },
        )
        assert queue.status_code == 200
        items = queue.json()["data"]
        assert [item["transaction_id"] for item in items] == [1]
        assert items[0]["expected_override_version"] == 0
        initial_classification_state = items[0]["expected_classification_state"]

        first_page = client.get(
            "/api/v1/classification/review-queue", params={"include_resolved": "true", "limit": 1}
        )
        next_cursor = first_page.json()["meta"]["next_cursor"]
        assert first_page.json()["data"][0]["transaction_id"] == 1
        second_page = client.get(
            "/api/v1/classification/review-queue",
            params={"include_resolved": "true", "limit": 1, "cursor": next_cursor},
        )
        assert second_page.json()["data"][0]["transaction_id"] == 2
        assert second_page.json()["meta"]["next_cursor"] is None
        wrong_filter_cursor = client.get(
            "/api/v1/classification/review-queue",
            params={"include_resolved": "false", "limit": 1, "cursor": next_cursor},
        )
        assert wrong_filter_cursor.status_code == 422

        invalid_month = client.get(
            "/api/v1/classification/review-queue", params={"month": "2026-13"}
        )
        assert invalid_month.status_code == 422
        assert invalid_month.json()["error"]["code"] == "VALIDATION_ERROR"

        coverage = client.get(
            "/api/v1/classification/coverage", params={"month": "2026-09", "currency": "ils"}
        )
        coverage_data = coverage.json()["data"]
        assert coverage_data["total_accepted"] == 2
        assert coverage_data["classified_count"] == 2
        assert coverage_data["unclassified_count"] == 0
        assert coverage_data["by_economic_class"]["consumption"] == 1
        assert coverage_data["by_economic_class"]["refund"] == 1
        assert coverage_data["classification_coverage_percent"] == "100.0"
        empty_coverage = client.get(
            "/api/v1/classification/coverage", params={"month": "2025-01", "currency": "ILS"}
        ).json()["data"]
        assert empty_coverage["total_accepted"] == 0
        assert empty_coverage["classification_coverage_percent"] is None

        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        refund_state = client.get(
            "/api/v1/classification/review-queue", params={"include_resolved": "true"}
        ).json()["data"][1]["expected_classification_state"]
        refund_rule_body = {
            "account_kind": "bank",
            "direction": "credit",
            "source_category": "refund",
            "source_movement_type": "refund",
            "currency": "ILS",
            "economic_class": "refund",
            "expense_behavior": "unknown",
        }
        refund_preview = client.post(
            "/api/v1/classification/rules/previews", headers=headers, json=refund_rule_body
        ).json()["data"]
        refund_rule = client.post(
            "/api/v1/classification/rules",
            headers=headers,
            json={**refund_rule_body, "expected_current_rule_id": refund_preview["expected_current_rule_id"]},
        )
        assert refund_rule.status_code == 201
        stale_after_rule_change = client.post(
            "/api/v1/classification/transactions/2/override",
            headers=headers,
            json={
                "expected_override_version": 0,
                "expected_classification_state": refund_state,
                "economic_class": "refund",
            },
        )
        assert stale_after_rule_change.status_code == 409
        assert stale_after_rule_change.json()["error"]["code"] == "STALE_CLASSIFICATION"

        saved = client.post(
            "/api/v1/classification/transactions/1/override",
            headers=headers,
            json={
                "expected_override_version": 0,
                "expected_classification_state": initial_classification_state,
                "analysis_category": "groceries",
                "reason": "Reviewed synthetic transaction",
            },
        )
        assert saved.status_code == 200
        assert saved.json()["data"]["result"]["analysis_category"] == "groceries"
        override_version = saved.json()["data"]["override_version"]
        saved_classification_state = saved.json()["data"]["expected_classification_state"]
        assert override_version > 0

        stale_save = client.post(
            "/api/v1/classification/transactions/1/override",
            headers=headers,
            json={
                "expected_override_version": 0,
                "expected_classification_state": initial_classification_state,
                "economic_class": "consumption",
            },
        )
        assert stale_save.status_code == 409
        assert stale_save.json()["error"]["code"] == "STALE_CLASSIFICATION"

        cleared = client.loop.run_until_complete(
            client.client.request(
                "DELETE",
                "/api/v1/classification/transactions/1/override",
                headers=headers,
                json={
                    "expected_override_version": override_version,
                    "expected_classification_state": saved_classification_state,
                },
            )
        )
        assert cleared.status_code == 200
        assert cleared.json()["data"]["result"]["source"] == "builtin_rule"
        cleared_version = cleared.json()["data"]["override_version"]
        cleared_state = cleared.json()["data"]["expected_classification_state"]
        assert cleared_version > override_version

        invalid_sign = client.post(
            "/api/v1/classification/transactions/1/override",
            headers=headers,
            json={
                "expected_override_version": cleared_version,
                "expected_classification_state": cleared_state,
                "economic_class": "income",
            },
        )
        assert invalid_sign.status_code == 200
        invalid_result = invalid_sign.json()["data"]["result"]
        assert invalid_result["economic_class"] == "unclassified"
        assert "INVALID_CLASS_SIGN" in {issue["code"] for issue in invalid_result["issues"]}
        cleared_invalid = client.loop.run_until_complete(
            client.client.request(
                "DELETE",
                "/api/v1/classification/transactions/1/override",
                headers=headers,
                json={
                    "expected_override_version": invalid_sign.json()["data"]["override_version"],
                    "expected_classification_state": invalid_sign.json()["data"]["expected_classification_state"],
                },
            )
        )
        assert cleared_invalid.status_code == 200

        rule_body = {
            "account_kind": "bank",
            "direction": "debit",
            "source_category": "food",
            "source_movement_type": "purchase",
            "currency": "ils",
            "economic_class": "consumption",
            "analysis_category": "groceries",
            "expense_behavior": "variable",
            "reason": "Reviewed exact source labels",
        }
        preview = client.post(
            "/api/v1/classification/rules/previews", headers=headers, json=rule_body
        )
        assert preview.status_code == 200
        assert preview.json()["data"]["count"] == 1
        assert preview.json()["data"]["expected_current_rule_id"] is None

        created = client.post(
            "/api/v1/classification/rules",
            headers=headers,
            json={**rule_body, "expected_current_rule_id": None},
        )
        assert created.status_code == 201
        rule_id = created.json()["data"]["id"]
        assert created.json()["data"]["revision"] == 1

        stale_create = client.post(
            "/api/v1/classification/rules",
            headers=headers,
            json={**rule_body, "expected_current_rule_id": None},
        )
        assert stale_create.status_code == 409
        assert stale_create.json()["error"]["code"] == "STALE_RULE"

        preview_revision = client.post(
            "/api/v1/classification/rules/previews", headers=headers, json=rule_body
        ).json()["data"]
        assert preview_revision["expected_current_rule_id"] == rule_id
        revision = client.post(
            "/api/v1/classification/rules",
            headers=headers,
            json={
                **rule_body,
                "reason": "Updated after review",
                "expected_current_rule_id": rule_id,
            },
        )
        assert revision.status_code == 201
        current_rule_id = revision.json()["data"]["id"]
        assert revision.json()["data"]["revision"] == 2

        rules = client.get("/api/v1/classification/rules?limit=1")
        assert len(rules.json()["data"]) == 1
        assert rules.json()["meta"]["next_cursor"]
        second_rule_page = client.get(
            "/api/v1/classification/rules?limit=1&cursor=" + rules.json()["meta"]["next_cursor"]
        )
        assert len(second_rule_page.json()["data"]) == 1
        assert second_rule_page.json()["data"][0]["id"] != rules.json()["data"][0]["id"]
        old_rule_disable = client.post(
            f"/api/v1/classification/rules/{rule_id}/disable",
            headers=headers,
            json={"expected_current_rule_id": rule_id},
        )
        assert old_rule_disable.status_code == 409
        disabled = client.post(
            f"/api/v1/classification/rules/{current_rule_id}/disable",
            headers=headers,
            json={"expected_current_rule_id": current_rule_id},
        )
        assert disabled.status_code == 200
        assert disabled.json()["data"]["tombstone"] is True

        with database.session() as session:
            audit = session.execute(select(ActorAuditEventRow)).scalars().all()
        assert {item.event_type for item in audit} >= {
            "classification.override_saved",
            "classification.override_cleared",
            "classification.rule_created",
            "classification.rule_disabled",
        }


def test_concurrent_override_and_rule_writes_reject_stale_second_writer(tmp_path):
    _, _, _, app = make_api(tmp_path)
    with ApiTestClient(app, base_url=ORIGIN) as client:
        csrf = _sign_in(client)
        _import_rows(client)
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        queue_version = client.get(
            "/api/v1/classification/review-queue", params={"include_resolved": "true"}
        ).json()["data"][0]["expected_classification_state"]

        async def concurrent_posts(url: str, first: dict, second: dict):
            return await asyncio.gather(
                client.client.post(url, headers=headers, json=first),
                client.client.post(url, headers=headers, json=second),
            )

        override_url = "/api/v1/classification/transactions/1/override"
        override_responses = client.loop.run_until_complete(
            concurrent_posts(
                override_url,
                {
                    "expected_override_version": 0,
                    "expected_classification_state": queue_version,
                    "analysis_category": "groceries",
                },
                {
                    "expected_override_version": 0,
                    "expected_classification_state": queue_version,
                    "analysis_category": "household",
                },
            )
        )
        assert sorted(response.status_code for response in override_responses) == [200, 409]
        assert sum(response.json().get("error", {}).get("code") == "STALE_CLASSIFICATION" for response in override_responses) == 1
        service = client.app.state.services.classification_service
        assert len(service.repository.latest_overrides(1)) == 1

        rule_body = {
            "account_kind": "bank",
            "direction": "debit",
            "source_category": "food",
            "source_movement_type": "purchase",
            "currency": "ILS",
            "economic_class": "consumption",
        }
        rule_responses = client.loop.run_until_complete(
            concurrent_posts(
                "/api/v1/classification/rules",
                {**rule_body, "expected_current_rule_id": None},
                {**rule_body, "expected_current_rule_id": None, "reason": "Second stale writer"},
            )
        )
        assert sorted(response.status_code for response in rule_responses) == [201, 409]
        assert sum(response.json().get("error", {}).get("code") == "STALE_RULE" for response in rule_responses) == 1


def test_classification_routes_require_authenticated_session(tmp_path):
    _, _, _, app = make_api(tmp_path)
    with ApiTestClient(app, base_url=ORIGIN) as client:
        response = client.get("/api/v1/classification/coverage")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
