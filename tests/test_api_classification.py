from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import select

from family_finance.dashboard import DashboardService
from family_finance.persistence.models import ActorAuditEventRow, TransactionRow
from tests.conftest import make_workbook
from tests.test_api_auth import ApiTestClient, make_api

ORIGIN = "https://testserver"
LOGIN = {"username": "sam", "password": "Long-test-password-One!"}


def test_amount_resolution_is_atomic_audited_reversible_and_updates_reports(tmp_path):
    _, database, _, app = make_api(tmp_path)
    with ApiTestClient(app, base_url=ORIGIN) as client:
        csrf = _sign_in(client)
        service = app.state.services
        payload = make_workbook([["15/09/2026", 72.4, "Cloud fixture", "15/09/2026", None, "הכנסות מעסק", "ILS", "ILS", -72.4]], provider="בנק", reference="resolution-fixture")
        preview = service.preview_import(payload)
        service.commit_import(payload, preview.preview_token, "resolution.xlsx")
        classifier = service.classification_service
        classifier.save_override(1, economic_class="consumption", analysis_category="אחסון ענן", reason="Legacy conflicting decision")
        source_before = classifier.repository.source_info(1)
        transaction_before = classifier.repository.transaction(1)
        item = client.get("/api/v1/classification/review-queue").json()["data"][0]
        assert item["saved_override"]["analysis_category"] == "אחסון ענן"
        assert item["saved_override"]["economic_class"] == "consumption"
        assert item["effective_classification"]["original_amount"] == "-72.4"
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        body = {"expected_override_version": item["expected_override_version"], "expected_classification_state": item["expected_classification_state"], "economic_class": "consumption", "analysis_category": "אחסון ענן", "expense_behavior": "fixed", "reason": "Confirmed debit against original"}
        count_before = database.count("analysis_overrides")
        bad = client.post("/api/v1/classification/transactions/1/override", headers=headers, json=body)
        assert bad.status_code == 422
        assert database.count("analysis_overrides") == count_before
        for amount in ("NaN", "Infinity", "1.000000001", "1e30"):
            invalid = client.post("/api/v1/classification/transactions/1/override", headers=headers, json={**body, "effective_amount": amount})
            assert invalid.status_code == 422
        no_reason = client.post("/api/v1/classification/transactions/1/override", headers=headers, json={**body, "effective_amount": "-72.4", "reason": " "})
        assert no_reason.status_code == 422
        assert database.count("analysis_overrides") == count_before
        saved = client.post("/api/v1/classification/transactions/1/override", headers=headers, json={**body, "effective_amount": "-72.4"})
        assert saved.status_code == 200
        data = saved.json()["data"]
        assert data["result"]["amount"] == "-72.4"
        assert data["result"]["imported_amount"] == "72.4"
        assert data["result"]["economic_class"] == "consumption"
        assert client.get("/api/v1/classification/review-queue").json()["data"] == []
        dashboard = DashboardService(database)
        metrics = dashboard.metrics.calculate_monthly_metrics("2026-09")
        assert metrics.gross_consumption == Decimal("72.4")
        assert metrics.spending_by_category == {"אחסון ענן": Decimal("72.4")}
        assert dashboard.contributors([1])[0].amount == Decimal("-72.4")
        assert classifier.repository.source_info(1) == source_before
        assert classifier.repository.transaction(1) == transaction_before
        stale = client.post("/api/v1/classification/transactions/1/override", headers=headers, json={**body, "effective_amount": "-72.4"})
        assert stale.status_code == 409
        cleared = client.loop.run_until_complete(client.client.request("DELETE", "/api/v1/classification/transactions/1/override", headers=headers, json={"expected_override_version": data["override_version"], "expected_classification_state": data["expected_classification_state"]}))
        assert cleared.status_code == 200
        assert cleared.json()["data"]["result"]["amount"] == "72.4"
        assert classifier.repository.transaction(1) == transaction_before
        assert all(item["value"] is None for item in classifier.repository.latest_overrides(1))
        with database.session() as session:
            events = session.scalars(select(ActorAuditEventRow)).all()
        assert {item.event_type for item in events} >= {"classification.override_saved", "classification.override_cleared"}


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
        assert invalid_sign.status_code == 422
        assert invalid_sign.json()["error"]["code"] == "CLASSIFICATION_DIRECTION_CONFLICT"
        assert client.get("/api/v1/classification/review-queue", params={"include_resolved": "true"}).json()["data"][0]["expected_override_version"] == cleared_version

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


def test_zero_amount_can_be_reviewed_without_financial_effect_and_undone(tmp_path):
    _, database, _, app = make_api(tmp_path)
    with ApiTestClient(app, base_url=ORIGIN) as client:
        headers = {"Origin": ORIGIN, "X-CSRF-Token": _sign_in(client)}
        service = app.state.services
        payload = make_workbook([["15/09/2026", 0, "Synthetic waived card fee", "15/09/2026", "fee", "שונות", "ILS", "ILS", -17.9]])
        preview = service.preview_import(payload)
        service.commit_import(payload, preview.preview_token, "waived-fee.xlsx")
        classifier = service.classification_service
        classifier.save_override(1, economic_class="consumption", expense_behavior="fixed", reason="Legacy fee decision")
        source_before = classifier.repository.source_info(1)
        transaction_before = classifier.repository.transaction(1)
        item = client.get("/api/v1/classification/review-queue").json()["data"][0]
        preconditions = {"expected_override_version": item["expected_override_version"], "expected_classification_state": item["expected_classification_state"]}
        saved = client.post("/api/v1/classification/transactions/1/override", headers=headers, json={**preconditions, "economic_class": "no_financial_effect", "reason": "Confirmed the fee was waived"})
        assert saved.status_code == 200
        data = saved.json()["data"]
        assert data["result"]["amount"] == "0"
        assert data["result"]["economic_class"] == "no_financial_effect"
        assert data["result"]["expense_behavior"] == "not_applicable"
        assert data["result"]["issues"] == []
        assert client.get("/api/v1/classification/review-queue").json()["data"] == []
        metrics = DashboardService(database).metrics.calculate_monthly_metrics("2026-09")
        assert metrics.gross_consumption == metrics.gross_income == metrics.refunds == 0
        assert metrics.unclassified_transaction_count == 0
        assert metrics.completeness.classification_complete
        assert metrics.contributors_for("gross_consumption") == []
        assert classifier.repository.source_info(1) == source_before
        assert classifier.repository.transaction(1) == transaction_before
        assert any(issue["code"] == "ZERO_AMOUNT_WITH_ORIGINAL_VALUE" for issue in source_before["issues"])
        cleared = client.loop.run_until_complete(client.client.request("DELETE", "/api/v1/classification/transactions/1/override", headers=headers, json={"expected_override_version": data["override_version"], "expected_classification_state": data["expected_classification_state"]}))
        assert cleared.status_code == 200
        assert cleared.json()["data"]["result"]["economic_class"] == "unclassified"
        item = client.get("/api/v1/classification/review-queue").json()["data"][0]
        # Confirm again, then simulate changed source data. The saved zero decision
        # must never suppress a subsequently charged fee.
        saved = client.post("/api/v1/classification/transactions/1/override", headers=headers, json={"expected_override_version": item["expected_override_version"], "expected_classification_state": item["expected_classification_state"], "economic_class": "no_financial_effect"})
        assert saved.status_code == 200
        with database.write_session() as session:
            session.get(TransactionRow, 1).amount = "-17.9"
        item = client.get("/api/v1/classification/review-queue").json()["data"][0]
        assert item["effective_classification"]["economic_class"] == "unclassified"
        count_before = database.count("analysis_overrides")
        bad = client.post("/api/v1/classification/transactions/1/override", headers=headers, json={"expected_override_version": item["expected_override_version"], "expected_classification_state": item["expected_classification_state"], "economic_class": "no_financial_effect", "effective_amount": "0", "reason": "Must not hide a charge"})
        assert bad.status_code == 422
        assert database.count("analysis_overrides") == count_before
        with database.session() as session:
            events = session.scalars(select(ActorAuditEventRow)).all()
        assert {event.event_type for event in events} >= {"classification.override_saved", "classification.override_cleared"}


@pytest.mark.parametrize("rule_category", [None, "Rule default"])
def test_explicit_null_clears_only_category_and_restores_underlying_default(tmp_path, rule_category):
    _, _, _, app = make_api(tmp_path)
    with ApiTestClient(app, base_url=ORIGIN) as client:
        headers = {"Origin": ORIGIN, "X-CSRF-Token": _sign_in(client)}
        _import_rows(client)
        classifier = app.state.services.classification_service
        if rule_category:
            classifier.create_rule(account_kind="bank", direction="debit", source_category="food", source_movement_type="purchase", currency="ILS", economic_class="consumption", analysis_category=rule_category)
        classifier.save_override(1, economic_class="consumption", analysis_category="Groceries", expense_behavior="fixed")
        item = next(item for item in client.get("/api/v1/classification/review-queue", params={"include_resolved": True}).json()["data"] if item["transaction_id"] == 1)
        path = "/api/v1/classification/transactions/1/override"
        preconditions = {key: item[key] for key in ("expected_override_version", "expected_classification_state")}
        # Omission preserves the previous category decision.
        omitted = client.post(path, headers=headers, json={**preconditions, "expense_behavior": "variable"})
        assert omitted.status_code == 200
        data = omitted.json()["data"]
        assert data["result"]["analysis_category"] == "Groceries"
        preview = classifier.preview_override(1, {"analysis_category": None})
        assert preview.analysis_category == (rule_category or "food")
        assert classifier.saved_override(1).analysis_category == "Groceries"
        # A category-only explicit null is a valid decision and appends a tombstone.
        cleared = client.post(path, headers=headers, json={"expected_override_version": data["override_version"], "expected_classification_state": data["expected_classification_state"], "analysis_category": None})
        assert cleared.status_code == 200, cleared.text
        result = cleared.json()["data"]["result"]
        assert result["analysis_category"] == (rule_category or "food")
        assert result["economic_class"] == "consumption"
        assert result["expense_behavior"] == "variable"
        category = next(row for row in classifier.repository.latest_overrides(1) if row["field_name"] == "analysis_category")
        assert category["value"] is None
        assert classifier.saved_override(1).analysis_category is None
        # The old screen cannot replay a clear over a newer decision.
        assert client.post(path, headers=headers, json={**preconditions, "analysis_category": None}).status_code == 409


def test_zero_review_rules_are_rejected_and_legacy_rules_cannot_review_future_imports(tmp_path):
    _, database, _, app = make_api(tmp_path)
    with ApiTestClient(app, base_url=ORIGIN) as client:
        headers = {"Origin": ORIGIN, "X-CSRF-Token": _sign_in(client)}
        service = app.state.services
        def import_zero(day):
            payload = make_workbook([[f"{day}/09/2026", 0, f"Synthetic waived fee {day}", f"{day}/09/2026", "fee", "שונות", "ILS", "ILS", -17.9]])
            preview = service.preview_import(payload)
            service.commit_import(payload, preview.preview_token, f"fee-{day}.xlsx")
        import_zero("15")
        item = client.get("/api/v1/classification/review-queue").json()["data"][0]
        fields = {"account_kind": item["account_kind"], "direction": "zero", "source_category": item["source_category"], "source_movement_type": item["source_movement_type"], "currency": "ILS", "economic_class": "no_financial_effect"}
        body = {**fields, "expected_current_rule_id": None}
        assert client.post("/api/v1/classification/rules", headers=headers, json=body).status_code == 422
        assert client.post("/api/v1/classification/rules/previews", headers=headers, json=fields).status_code == 422
        classifier = service.classification_service
        with pytest.raises(ValueError, match="transaction-specific"):
            classifier.create_rule(fields)
        with pytest.raises(ValueError, match="transaction-specific"):
            classifier.preview_rule(fields)
        # Simulate a persisted rule from before this restriction.
        legacy = classifier.repository.save_rule(classifier._rule_model(fields))
        import_zero("16")
        queue = client.get("/api/v1/classification/review-queue").json()["data"]
        assert len(queue) == 2
        for item in queue:
            result = item["effective_classification"]
            assert result["economic_class"] == "unclassified"
            assert "ZERO_AMOUNT_WITH_ORIGINAL_VALUE" in {issue["code"] for issue in result["issues"]}
            assert item["saved_override"] is None
        metrics = DashboardService(database).metrics.calculate_monthly_metrics("2026-09")
        assert metrics.unclassified_transaction_count == 2
        assert not metrics.completeness.classification_complete
        # Transaction-specific review remains available; legacy rules can be disabled.
        item = queue[0]
        reviewed = client.post(f"/api/v1/classification/transactions/{item['transaction_id']}/override", headers=headers, json={"expected_override_version": item["expected_override_version"], "expected_classification_state": item["expected_classification_state"], "economic_class": "no_financial_effect"})
        assert reviewed.status_code == 200
        assert len(client.get("/api/v1/classification/review-queue").json()["data"]) == 1
        assert classifier.disable_rule(legacy.id).tombstone
