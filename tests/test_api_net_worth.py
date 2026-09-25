from __future__ import annotations

import csv
import io

from family_finance.api.auth import SESSION_COOKIE_NAME
from family_finance.models import ForecastActualComparison
from tests.test_api_auth import ApiTestClient, make_api


def _sign_in(client: ApiTestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/session",
        json={"username": "sam", "password": "Long-test-password-One!"},
        headers={"Origin": "https://testserver"},
    )
    assert response.status_code == 200
    assert client.cookies.get(SESSION_COOKIE_NAME)
    return {"Origin": "https://testserver", "X-CSRF-Token": response.json()["data"]["csrf_token"]}


def _account_payload(key: str, name: str, *, side: str, category: str, liquidity: str | None):
    return {
        "account_key": key,
        "display_name": name,
        "side": side,
        "category": category,
        "liquidity": liquidity,
        "owner_label": None,
        "active_from": "2020-01-01",
        "active_to": None,
        "stale_after_days": 45,
    }


def _add_accounts(client: ApiTestClient, headers: dict[str, str]):
    asset = client.post(
        "/api/v1/net-worth/accounts",
        json=_account_payload("cash", "Household cash", side="asset", category="cash", liquidity="liquid"),
        headers=headers,
    )
    liability = client.post(
        "/api/v1/net-worth/accounts",
        json=_account_payload("loan", "Personal loan", side="liability", category="loan", liquidity=None),
        headers=headers,
    )
    assert asset.status_code == 201
    assert liability.status_code == 201
    return asset.json()["data"], liability.json()["data"]


def test_net_worth_routes_require_authentication_and_keep_decimal_strings(tmp_path):
    settings, database, _, app = make_api(tmp_path)
    with ApiTestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/v1/net-worth/accounts").status_code == 401
        headers = _sign_in(client)
        cash, loan = _add_accounts(client, headers)

        saved = client.post(
            "/api/v1/net-worth/snapshots",
            json={
                "snapshot_date": "2026-04-30",
                "balances": [
                    {"account_key": "cash", "amount_ils": "1250.50", "valuation_date": "2026-04-30"},
                    {"account_key": "loan", "amount_ils": "350.25", "valuation_date": "2026-04-30"},
                ],
            },
            headers=headers,
        )
        assert saved.status_code == 201
        revision = saved.json()["data"]
        assert revision["balances"][0]["amount_ils"] == "1250.50"
        assert revision["content_hash"]
        assert revision["complete"] is True

        summary = client.get("/api/v1/net-worth/summary?snapshot_id=" + revision["snapshot_id"])
        assert summary.status_code == 200
        assert summary.json()["data"]["total_assets"] == "1250.50"
        assert summary.json()["data"]["total_liabilities"] == "350.25"
        assert summary.json()["data"]["net_worth"] == "900.25"
        assert summary.headers["cache-control"] == "private, no-store"

        history = client.get("/api/v1/net-worth/accounts/cash/history")
        assert history.status_code == 200
        assert history.json()["data"][0]["amount_ils"] == "1250.50"
        trend = client.get("/api/v1/net-worth/trend")
        assert trend.status_code == 200
        assert trend.json()["data"][0]["revision_id"] == revision["revision_id"]

        update = client.post(
            f"/api/v1/net-worth/snapshots/{revision['snapshot_id']}/revisions",
            json={
                "expected_revision_number": 1,
                "balances": [
                    {"account_key": "cash", "amount_ils": "1300", "valuation_date": "2026-04-30"},
                    {"account_key": "loan", "amount_ils": "350.25", "valuation_date": "2026-04-30"},
                ],
            },
            headers=headers,
        )
        assert update.status_code == 201
        assert update.json()["data"]["revision_number"] == 2
        stale = client.post(
            f"/api/v1/net-worth/snapshots/{revision['snapshot_id']}/revisions",
            json={
                "expected_revision_number": 1,
                "balances": [
                    {"account_key": "cash", "amount_ils": "1400", "valuation_date": "2026-04-30"},
                    {"account_key": "loan", "amount_ils": "350.25", "valuation_date": "2026-04-30"},
                ],
            },
            headers=headers,
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "STALE_REVISION"
        old_revision = client.get(
            f"/api/v1/net-worth/snapshots/{revision['snapshot_id']}/revisions/1"
        )
        assert old_revision.status_code == 200
        assert old_revision.json()["data"]["balances"][0]["amount_ils"] == "1250.50"

        closed = client.post(
            "/api/v1/net-worth/accounts/cash/close",
            json={"closed_on": "2026-12-31"},
            headers=headers,
        )
        assert closed.status_code == 200
        assert closed.json()["data"]["active_to"] == "2026-12-31"
        reactivated = client.post(
            "/api/v1/net-worth/accounts/cash/reactivate",
            json={"active_from": "2020-01-01"},
            headers=headers,
        )
        assert reactivated.status_code == 200
        assert reactivated.json()["data"]["active_to"] is None
        assert cash["side"] == "asset" and loan["side"] == "liability"
        assert database.path == settings.database_path


def test_net_worth_csv_template_preview_commit_and_strict_headers(tmp_path):
    _, _, _, app = make_api(tmp_path)
    with ApiTestClient(app, base_url="https://testserver") as client:
        headers = _sign_in(client)
        _add_accounts(client, headers)

        template = client.get("/api/v1/net-worth/csv-template?snapshot_date=2026-05-31")
        assert template.status_code == 200
        assert template.headers["content-type"].startswith("text/csv")
        assert "net-worth-template.csv" in template.headers["content-disposition"]
        assert template.headers["cache-control"] == "private, no-store"

        rows = list(csv.DictReader(io.StringIO(template.text)))
        for row in rows:
            row["amount_ils"] = "800.75" if row["account_key"] == "cash" else "100.25"
        content = io.StringIO(newline="")
        writer = csv.DictWriter(content, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        csv_bytes = content.getvalue().encode("utf-8")

        preview = client.post(
            "/api/v1/net-worth/csv/previews",
            files={"file": ("balances.csv", csv_bytes, "text/csv")},
            headers=headers,
        )
        assert preview.status_code == 200
        preview_data = preview.json()["data"]
        assert preview_data["valid"] is True
        assert preview_data["snapshot_date"] == "2026-05-31"
        assert preview_data["row_count"] == 2

        committed = client.post(
            "/api/v1/net-worth/csv/commits",
            files={"file": ("balances.csv", csv_bytes, "text/csv")},
            data={
                "preview_token": preview_data["preview_token"],
                "filename": "balances.csv",
                "create_new_revision": "false",
                "quality_acknowledged": "false",
            },
            headers=headers,
        )
        assert committed.status_code == 201
        assert committed.json()["data"]["origin"] == "csv"
        assert committed.json()["data"]["balances"][0]["amount_ils"] == "800.75"

        malformed = client.post(
            "/api/v1/net-worth/csv/previews",
            files={
                "file": (
                    "bad.csv",
                    template.content.replace(b"liquidity", b"liquidity_type", 1),
                    "text/csv",
                )
            },
            headers=headers,
        )
        assert malformed.status_code == 200
        assert "CSV_HEADERS_INVALID" in malformed.json()["data"]["issues"]

        missing_date = client.post(
            "/api/v1/net-worth/csv/previews",
            files={"file": ("no-date.csv", b"not,a,net-worth,csv\n", "text/csv")},
            headers=headers,
        )
        assert missing_date.status_code == 422
        assert "CSV file is invalid" in missing_date.json()["error"]["message"]
        assert "SQL" not in missing_date.text


def test_net_worth_snapshot_coverage_archive_and_forecast_compare_contract(tmp_path, monkeypatch):
    _, _, _, app = make_api(tmp_path)
    with ApiTestClient(app, base_url="https://testserver") as client:
        headers = _sign_in(client)
        _add_accounts(client, headers)
        strict_amount = client.post(
            "/api/v1/net-worth/snapshots",
            json={
                "snapshot_date": "2026-06-30",
                "balances": [
                    {"account_key": "cash", "amount_ils": 20, "valuation_date": "2026-06-30"},
                    {"account_key": "loan", "amount_ils": "5", "valuation_date": "2026-06-30"},
                ],
            },
            headers=headers,
        )
        assert strict_amount.status_code == 422
        incomplete = client.post(
            "/api/v1/net-worth/snapshots",
            json={
                "snapshot_date": "2026-06-30",
                "balances": [{"account_key": "cash", "amount_ils": "20", "valuation_date": "2026-06-30"}],
            },
            headers=headers,
        )
        assert incomplete.status_code == 422

        created = client.post(
            "/api/v1/net-worth/snapshots",
            json={
                "snapshot_date": "2026-06-30",
                "balances": [
                    {"account_key": "cash", "amount_ils": "20", "valuation_date": "2026-06-30"},
                    {"account_key": "loan", "amount_ils": "5", "valuation_date": "2026-06-30"},
                ],
            },
            headers=headers,
        )
        revision = created.json()["data"]
        snapshot_id = revision["snapshot_id"]
        archived = client.post(
            f"/api/v1/net-worth/snapshots/{snapshot_id}/archive",
            json={"archived": True},
            headers=headers,
        )
        assert archived.status_code == 200
        assert archived.json()["data"]["archived"] is True
        blocked_restore = client.post(
            f"/api/v1/net-worth/snapshots/{snapshot_id}/revisions/1/restore",
            json={"expected_revision_number": 1},
            headers=headers,
        )
        assert blocked_restore.status_code == 409

        expected = ForecastActualComparison(
            forecast_id="forecast-1", forecast_revision_id="forecast-revision-1",
            forecast_revision_number=3, role="baseline", observed_snapshot_revision_id=revision["revision_id"],
            observed_snapshot_date=revision["snapshot_date"], projected_month="2026-06-01",
            account_deltas={"cash": "2.5"}, projected_by_account={"cash": "17.5"},
            observed_by_account={"cash": "20"}, projected_total="17.5", observed_total="20",
            aggregate_delta="2.5", timing_warning="month-end timing", valuation_date_warning=None,
        )
        service = app.state.services.net_worth_service
        monkeypatch.setattr(service, "compare_forecast_actual", lambda *args, **kwargs: expected)
        comparison = client.post(
            "/api/v1/net-worth/forecast-comparisons",
            json={
                "forecast_id": "forecast-1", "forecast_revision_number": 3,
                "observed_snapshot_revision_id": revision["revision_id"], "role": "baseline",
            },
            headers=headers,
        )
        assert comparison.status_code == 200
        assert comparison.json()["data"]["aggregate_delta"] == "2.5"
        assert comparison.json()["data"]["timing_warning"] == "month-end timing"
