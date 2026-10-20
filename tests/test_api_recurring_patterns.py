from __future__ import annotations

import pytest
from sqlalchemy import select

from family_finance.persistence.models import ActorAuditEventRow, RecurringPatternReviewRow
from family_finance.services import ImportService
from tests.conftest import make_workbook
from tests.test_api_auth import ApiTestClient, make_api

SCOPE = {"start_month": "2026-06-01", "end_month": "2026-09-01", "currency": "ILS"}


def seed(tmp_path):
    settings, database, _, app = make_api(tmp_path)
    importer = ImportService(settings=settings, database=database)
    workbook = make_workbook([
        [f"15/{month:02}/2026", -50, "synthetic subscription", f"15/{month:02}/2026",
         "purchase", "food", "ILS", "ILS", -50]
        for month in range(6, 10)
    ], provider="בנק", report_end="30/09/2026")
    preview = importer.preview_import(workbook, "recurring.xlsx")
    importer.commit_import(workbook, preview.preview_token, "recurring.xlsx")
    return database, app


def sign_in(client, username="sam", password="Long-test-password-One!"):
    response = client.post("/api/v1/auth/session", json={"username": username, "password": password},
                           headers={"Origin": "https://testserver"})
    assert response.status_code == 200
    return {"Origin": "https://testserver", "X-CSRF-Token": response.json()["data"]["csrf_token"]}


def report(client, scope=None):
    response = client.get("/api/v1/dashboard/expenses", params=scope or SCOPE)
    assert response.status_code == 200
    return response.json()["data"]


def test_recurring_decisions_persist_across_ranges_and_household_logins(tmp_path):
    database, app = seed(tmp_path)
    with ApiTestClient(app, base_url="https://testserver") as client:
        headers = sign_in(client)
        before = report(client)
        pattern = before["potential_recurring_spending"][0]
        pattern_id = pattern["pattern_id"]
        path = f"/api/v1/insights/recurring-patterns/{pattern_id}"
        assert len(pattern_id) == 64
        # The same merchant/category/account/currency has a stable identity as
        # new months join or leave the detector's window.
        narrower = report(client, {**SCOPE, "start_month": "2026-07-01"})
        assert narrower["potential_recurring_spending"][0]["pattern_id"] == pattern_id
        for status in ("approved", "approved", "stopped", "pending", "dismissed", "pending", "approved"):
            response = client.put(path, json={**SCOPE, "status": status}, headers=headers)
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "private, no-store"
            assert response.json()["data"]["status"] == status
        after = report(client)
        assert after["recurring_pattern_reviews"][0]["status"] == "approved"
        assert after["selected_month"] == before["selected_month"]
        assert after["behavior_totals"] == before["behavior_totals"]
        # Saved approved patterns stay accessible even with no new detection.
        short = report(client, {**SCOPE, "start_month": "2026-09-01"})
        assert short["potential_recurring_spending"] == []
        assert short["recurring_pattern_reviews"][0]["pattern"] == pattern
        assert report(client, {**SCOPE, "currency": "USD"})["recurring_pattern_reviews"] == []
        headers = sign_in(client, "lee", "Long-test-password-Two!")
        assert report(client)["recurring_pattern_reviews"][0]["status"] == "approved"
        with database.session() as session:
            assert len(session.scalars(select(RecurringPatternReviewRow)).all()) == 1
            events = session.scalars(select(ActorAuditEventRow).where(
                ActorAuditEventRow.event_type.like("insights.recurring.%")
            )).all()
            assert len(events) == 7
        # A household member can undo a saved decision outside its detection
        # window without inventing a new pattern or reclassifying transactions.
        response = client.put(path, json={**SCOPE, "start_month": "2026-09-01", "status": "pending"}, headers=headers)
        assert response.status_code == 200


def test_recurring_review_requires_auth_csrf_real_pattern_and_valid_state(tmp_path):
    database, app = seed(tmp_path)
    with ApiTestClient(app, base_url="https://testserver") as client:
        path = "/api/v1/insights/recurring-patterns/unknown"
        assert client.put(path, json={**SCOPE, "status": "approved"}, headers={"Origin": "https://testserver"}).status_code == 401
        headers = sign_in(client)
        pattern_id = report(client)["potential_recurring_spending"][0]["pattern_id"]
        path = f"/api/v1/insights/recurring-patterns/{pattern_id}"
        assert client.put(path, json={**SCOPE, "status": "approved"}, headers={"Origin": "https://testserver"}).status_code == 403
        assert client.put(path, json={**SCOPE, "status": "stopped"}, headers=headers).status_code == 409
        assert client.put(path, json={**SCOPE, "status": "bogus"}, headers=headers).status_code == 422
        assert client.put(path, json={**SCOPE, "status": "approved", "median_amount": "1"}, headers=headers).status_code == 422
        assert client.put(path, json={**SCOPE, "status": "approved", "start_month": "2027-01-01"}, headers=headers).status_code == 422
        assert client.put(path, json={**SCOPE, "status": "approved", "currency": "USD"}, headers=headers).status_code == 404
        assert client.put(path, json={**SCOPE, "status": "approved", "start_month": "2026-09-01"}, headers=headers).status_code == 404
        assert report(client)["recurring_pattern_reviews"] == []
        with database.session() as session:
            assert session.scalars(select(RecurringPatternReviewRow)).all() == []


def test_recurring_review_rolls_back_if_actor_audit_fails(tmp_path, monkeypatch):
    _, app = seed(tmp_path)
    with ApiTestClient(app, base_url="https://testserver") as client:
        headers = sign_in(client)
        pattern_id = report(client)["potential_recurring_spending"][0]["pattern_id"]
        def fail_audit(*args, **kwargs):
            raise RuntimeError("audit unavailable")
        monkeypatch.setattr("family_finance.api.routers.insights.record_actor_audit", fail_audit)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            client.put(f"/api/v1/insights/recurring-patterns/{pattern_id}",
                       json={**SCOPE, "status": "approved"}, headers=headers)
        assert report(client)["recurring_pattern_reviews"] == []
