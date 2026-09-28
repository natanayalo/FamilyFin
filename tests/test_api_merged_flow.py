"""Exercise the merged PWA API as one household session."""

from __future__ import annotations

from decimal import Decimal

from tests.conftest import make_workbook
from tests.test_api_auth import ApiTestClient, make_api

ORIGIN = "https://testserver"
MONTH = {"start_month": "2026-09", "end_month": "2026-09", "currency": "ILS"}


def _upload(
    client: ApiTestClient, headers: dict[str, str], filename: str, rows: list[list[object]]
):
    workbook = make_workbook(
        rows, provider="בנק", reference="merged-flow-bank", report_end="30/09/2026"
    )
    preview = client.post(
        "/api/v1/imports/familybiz/previews",
        files={"file": (filename, workbook)},
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    committed = client.post(
        "/api/v1/imports/familybiz/commits",
        files={
            "file": (filename, workbook),
            "preview_token": (None, preview.json()["data"]["preview_token"]),
        },
        headers=headers,
    )
    assert committed.status_code == 200, committed.text
    return committed.json()["data"]


def test_merged_router_openapi_and_household_flow(tmp_path):
    _, _, _, app = make_api(tmp_path)
    schema = app.openapi()
    required_operations = {
        ("/api/v1/auth/session", "post"),
        ("/api/v1/imports/familybiz/previews", "post"),
        ("/api/v1/imports/familybiz/commits", "post"),
        ("/api/v1/reconciliation/cases/{case_id}/resolution", "post"),
        ("/api/v1/classification/review-queue", "get"),
        ("/api/v1/classification/transactions/{transaction_id}/override", "post"),
        ("/api/v1/dashboard/overview", "get"),
        ("/api/v1/dashboard/quality", "get"),
        ("/api/v1/net-worth/accounts", "post"),
        ("/api/v1/net-worth/snapshots", "post"),
        ("/api/v1/net-worth/summary", "get"),
        ("/api/v1/auth/session", "delete"),
    }
    assert all(method in schema["paths"][path] for path, method in required_operations)
    assert schema["components"]["schemas"]

    salary = [
        "01/09/2026",
        1000,
        "Synthetic salary",
        "01/09/2026",
        "credit",
        "salary",
        "ILS",
        "ILS",
        1000,
    ]
    grocery = [
        "02/09/2026",
        -17.4,
        "Synthetic grocery",
        "02/09/2026",
        "purchase",
        "food",
        "ILS",
        "ILS",
        -17.4,
    ]
    changed_grocery = [*grocery[:5], "changed source category", *grocery[6:]]

    with ApiTestClient(app, base_url=ORIGIN) as client:
        for path in (
            "/api/v1/dashboard/overview",
            "/api/v1/dashboard/quality",
            "/api/v1/classification/review-queue",
            "/api/v1/net-worth/accounts",
        ):
            assert client.get(path).status_code == 401

        login = client.post(
            "/api/v1/auth/session",
            json={"username": "sam", "password": "Long-test-password-One!"},
            headers={"Origin": ORIGIN},
        )
        assert login.status_code == 200, login.text
        headers = {"Origin": ORIGIN, "X-CSRF-Token": login.json()["data"]["csrf_token"]}

        first = _upload(client, headers, "household-initial.xlsx", [salary, grocery])
        assert first["statistics"]["inserted"] == 2
        second = _upload(client, headers, "household-overlap.xlsx", [salary, changed_grocery])
        assert second["statistics"]["unresolved"] == 1
        cases = client.get("/api/v1/reconciliation/cases").json()["data"]["items"]
        assert len(cases) == 1
        assert (
            client.get("/api/v1/dashboard/quality").json()["data"]["open_reconciliation_cases"] == 1
        )
        resolved = client.post(
            f"/api/v1/reconciliation/cases/{cases[0]['id']}/resolution",
            json={"resolution": "dismiss"},
            headers={**headers, "Idempotency-Key": "merged-household-resolution"},
        )
        assert resolved.status_code == 200, resolved.text
        assert client.get("/api/v1/reconciliation/cases").json()["data"]["items"] == []
        quality = client.get("/api/v1/dashboard/quality").json()["data"]
        assert quality["accepted_rows"] == 2
        assert quality["open_reconciliation_cases"] == 0

        queue = client.get(
            "/api/v1/classification/review-queue", params={"include_resolved": "true"}
        )
        assert queue.status_code == 200, queue.text
        grocery_item = next(
            item for item in queue.json()["data"] if item["description"] == "Synthetic grocery"
        )
        saved = client.post(
            f"/api/v1/classification/transactions/{grocery_item['transaction_id']}/override",
            json={
                "expected_override_version": grocery_item["expected_override_version"],
                "expected_classification_state": grocery_item["expected_classification_state"],
                "analysis_category": "groceries",
                "reason": "Household review",
            },
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"]["result"]["analysis_category"] == "groceries"

        overview = client.get("/api/v1/dashboard/overview", params=MONTH)
        expenses = client.get("/api/v1/dashboard/expenses", params=MONTH)
        assert overview.status_code == expenses.status_code == 200
        metrics = overview.json()["data"]["selected_month"]["metrics"]
        assert Decimal(metrics["gross_income"]) == Decimal(1000)
        assert Decimal(metrics["net_consumption"]) == Decimal("17.4")
        assert Decimal(metrics["spending_by_category"]["groceries"]) == Decimal("17.4")
        category = next(
            item
            for item in expenses.json()["data"]["categories"]
            if item["category"] == "groceries"
        )
        assert category["contributor_transaction_ids"] == [grocery_item["transaction_id"]]
        contributor = client.post(
            "/api/v1/dashboard/contributors/query",
            json={"transaction_ids": category["contributor_transaction_ids"]},
            headers=headers,
        )
        assert contributor.status_code == 200
        assert contributor.json()["data"][0]["analysis_category"] == "groceries"

        for key, side, category_name, liquidity in (
            ("cash", "asset", "cash", "liquid"),
            ("loan", "liability", "loan", None),
        ):
            account = client.post(
                "/api/v1/net-worth/accounts",
                json={
                    "account_key": key,
                    "display_name": key.title(),
                    "side": side,
                    "category": category_name,
                    "liquidity": liquidity,
                    "owner_label": None,
                    "active_from": "2020-01-01",
                    "active_to": None,
                    "stale_after_days": 45,
                },
                headers=headers,
            )
            assert account.status_code == 201, account.text
        snapshot = client.post(
            "/api/v1/net-worth/snapshots",
            json={
                "snapshot_date": "2026-09-30",
                "balances": [
                    {
                        "account_key": "cash",
                        "amount_ils": "1250.50",
                        "valuation_date": "2026-09-30",
                    },
                    {"account_key": "loan", "amount_ils": "350.25", "valuation_date": "2026-09-30"},
                ],
            },
            headers=headers,
        )
        assert snapshot.status_code == 201, snapshot.text
        summary = client.get(
            "/api/v1/net-worth/summary",
            params={"snapshot_id": snapshot.json()["data"]["snapshot_id"]},
        )
        assert summary.status_code == 200, summary.text
        assert summary.json()["data"]["net_worth"] == "900.25"

        logout = client.delete("/api/v1/auth/session", headers=headers)
        assert logout.status_code == 204
        for path in (
            "/api/v1/dashboard/overview",
            "/api/v1/dashboard/quality",
            "/api/v1/classification/review-queue",
            "/api/v1/net-worth/accounts",
        ):
            assert client.get(path).status_code == 401
