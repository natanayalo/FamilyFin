from __future__ import annotations

from family_finance.services import ImportService
from tests.conftest import make_workbook
from tests.test_api_auth import ApiTestClient, make_api


def _sign_in(client: ApiTestClient) -> None:
    response = client.post(
        "/api/v1/auth/session",
        json={"username": "sam", "password": "Long-test-password-One!"},
        headers={"Origin": "https://testserver"},
    )
    assert response.status_code == 200
    client.csrf_token = response.json()["data"]["csrf_token"]


def test_authenticated_dashboard_filters_and_contributor_contract(tmp_path):
    settings, database, _auth, app = make_api(tmp_path)
    import_service = ImportService(settings=settings, database=database)
    workbook = make_workbook(
        [
            ["01/09/2026", 1000, "synthetic salary", "01/09/2026", "credit", "salary", "ILS", "ILS", 1000],
            ["02/09/2026", -17.4, "synthetic grocery", "02/09/2026", "purchase", "food", "ILS", "ILS", -17.4],
        ],
        provider="בנק",
        reference="synthetic-dashboard-bank",
        report_end="30/09/2026",
    )
    preview = import_service.preview_import(workbook, "synthetic-dashboard.xlsx")
    import_service.commit_import(workbook, preview.preview_token, "synthetic-dashboard.xlsx")

    with ApiTestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/v1/dashboard/overview").status_code == 401
        _sign_in(client)

        defaults = client.get("/api/v1/dashboard/overview")
        assert defaults.status_code == 200
        assert defaults.json()["data"]["filters"]["end_month"] == "2026-09-01"
        assert defaults.json()["data"]["filters"]["currency"] == "ILS"

        overview_response = client.get(
            "/api/v1/dashboard/overview",
            params={"start_month": "2026-09-18", "end_month": "2026-09", "currency": "ils"},
        )
        assert overview_response.status_code == 200, overview_response.text
        assert overview_response.headers["cache-control"] == "private, no-store"
        overview = overview_response.json()["data"]
        assert overview["filters"] == {
            "start_month": "2026-09-01",
            "end_month": "2026-09-01",
            "currency": "ILS",
        }
        assert overview["selected_month"]["metrics"]["gross_income"] == "1000"
        assert overview["selected_month"]["metrics"]["net_consumption"] == "17.4"
        assert isinstance(overview["headline"]["income"], str)
        assert "request_id" in overview_response.json()["meta"]

        expenses_response = client.get(
            "/api/v1/dashboard/expenses",
            params={"start_month": "2026-09", "end_month": "2026-09-30", "currency": "ILS"},
        )
        assert expenses_response.status_code == 200
        expenses = expenses_response.json()["data"]
        food = next(item for item in expenses["categories"] if item["category"] == "food")
        assert food["amount"] == "17.4"
        assert isinstance(food["contributor_transaction_ids"][0], int)

        usd = client.get(
            "/api/v1/dashboard/expenses",
            params={"start_month": "2026-09", "end_month": "2026-09", "currency": "USD"},
        )
        assert usd.status_code == 200
        assert usd.json()["data"]["currency"] == "USD"
        assert usd.json()["data"]["series"] == []
        assert usd.json()["data"]["categories"] == []

        contributor_ids = food["contributor_transaction_ids"]
        contributors = client.post(
            "/api/v1/dashboard/contributors/query",
            json={"transaction_ids": contributor_ids},
            headers={"Origin": "https://testserver", "X-CSRF-Token": client.csrf_token},
        )
        assert contributors.status_code == 200
        row = contributors.json()["data"][0]
        assert row["transaction_id"] == contributor_ids[0]
        assert row["description"] == "synthetic grocery"
        assert row["amount"] == "-17.4"

        duplicate = client.post(
            "/api/v1/dashboard/contributors/query",
            json={"transaction_ids": [contributor_ids[0], contributor_ids[0]]},
            headers={"Origin": "https://testserver", "X-CSRF-Token": client.csrf_token},
        )
        assert duplicate.status_code == 422
        too_many = client.post(
            "/api/v1/dashboard/contributors/query",
            json={"transaction_ids": list(range(1, 102))},
            headers={"Origin": "https://testserver", "X-CSRF-Token": client.csrf_token},
        )
        assert too_many.status_code == 422
        csrf_missing = client.post(
            "/api/v1/dashboard/contributors/query",
            json={"transaction_ids": contributor_ids},
            headers={"Origin": "https://testserver"},
        )
        assert csrf_missing.status_code == 403
        malformed = client.post(
            "/api/v1/dashboard/contributors/query",
            json={"transaction_ids": [float(contributor_ids[0])]},
            headers={"Origin": "https://testserver", "X-CSRF-Token": client.csrf_token},
        )
        assert malformed.status_code == 422
        nonexistent = client.post(
            "/api/v1/dashboard/contributors/query",
            json={"transaction_ids": [999999]},
            headers={"Origin": "https://testserver", "X-CSRF-Token": client.csrf_token},
        )
        assert nonexistent.status_code == 404
        assert nonexistent.json()["error"]["code"] == "TRANSACTION_NOT_FOUND"

        reversed_range = client.get(
            "/api/v1/dashboard/overview",
            params={"start_month": "2026-10", "end_month": "2026-09"},
        )
        assert reversed_range.status_code == 422
        partial_range = client.get("/api/v1/dashboard/overview", params={"start_month": "2026-09"})
        assert partial_range.status_code == 422
