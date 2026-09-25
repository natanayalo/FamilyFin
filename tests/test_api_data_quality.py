from __future__ import annotations

import pytest
from sqlalchemy import func, select

from family_finance.persistence.models import ApiIdempotencyRecordRow
from family_finance.services import ImportService

from .conftest import make_workbook
from .test_api_auth import ApiTestClient, make_api


def sign_in(client: ApiTestClient) -> str:
    response = client.post(
        "/api/v1/auth/session",
        json={"username": "sam", "password": "Long-test-password-One!"},
        headers={"Origin": "https://testserver"},
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


def mutation_headers(csrf: str, **extra: str) -> dict[str, str]:
    return {"Origin": "https://testserver", "X-CSRF-Token": csrf, **extra}


def test_data_quality_is_authenticated_and_reports_incomplete_month_and_currencies(
    tmp_path, familybiz_row
):
    _, _, _, app = make_api(tmp_path)
    payload = make_workbook(
        [familybiz_row, [*familybiz_row[:6], "USD", "USD", -17.4]],
        report_end="19/09/2026",
    )

    with ApiTestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/v1/dashboard/quality").status_code == 401
        csrf = sign_in(client)
        preview = client.post(
            "/api/v1/imports/familybiz/previews",
            files={"file": ("quality.xlsx", payload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=mutation_headers(csrf),
        )
        assert preview.status_code == 200
        assert app.state.database.count("transactions") == 0
        assert app.state.database.count("import_batches") == 0
        result = client.post(
            "/api/v1/imports/familybiz/commits",
            files={
                "file": ("quality.xlsx", payload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "preview_token": (None, preview.json()["data"]["preview_token"]),
            },
            headers=mutation_headers(csrf),
        )
        assert result.status_code == 200

        response = client.get("/api/v1/dashboard/quality")
        assert response.status_code == 200
        data = response.json()["data"]
        expected = app.state.dashboard_service.data_quality()
        assert data["currencies"] == expected.currencies == {"ILS": 1, "USD": 1}
        assert data["accepted_rows"] == sum(expected.currencies.values()) == 2
        assert data["incomplete_months"] == [month.isoformat() for month in expected.incomplete_months]
        assert data["incomplete_months"]
        assert data["source_coverage"] == expected.source_coverage
        assert data["latest_import"]["id"] == result.json()["data"]["batch_id"]
        assert response.headers["cache-control"] == "private, no-store"


def test_preview_errors_are_safe_and_file_limit_returns_413(tmp_path):
    _, _, _, app = make_api(tmp_path)
    with ApiTestClient(app, base_url="https://testserver") as client:
        csrf = sign_in(client)
        invalid_payload = b"private row details must not leak"
        invalid = client.post(
            "/api/v1/imports/familybiz/previews",
            files={"file": ("bad.xlsx", invalid_payload)},
            headers=mutation_headers(csrf),
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "INVALID_FAMILYBIZ_WORKBOOK"
        assert invalid_payload.decode() not in invalid.text

    size_root = tmp_path / "limited"
    _, _, _, limited_app = make_api(size_root, maximum_compressed_bytes=128)
    with ApiTestClient(limited_app, base_url="https://testserver") as client:
        csrf = sign_in(client)
        oversized = client.post(
            "/api/v1/imports/familybiz/previews",
            files={"file": ("too-large.xlsx", b"x" * 129)},
            headers=mutation_headers(csrf),
        )
        assert oversized.status_code == 413
        assert oversized.json()["error"]["code"] == "REQUEST_TOO_LARGE"


def test_stale_preview_requires_a_new_preview_and_import_history_is_paginated(
    tmp_path, familybiz_row
):
    _, _, _, app = make_api(tmp_path)
    payload = make_workbook([familybiz_row])
    revised_row = list(familybiz_row)
    revised_row[5] = "changed category"
    revised_payload = make_workbook([revised_row])

    with ApiTestClient(app, base_url="https://testserver") as client:
        csrf = sign_in(client)
        preview = client.post(
            "/api/v1/imports/familybiz/previews",
            files={"file": ("review.xlsx", payload)},
            headers=mutation_headers(csrf),
        )
        token = preview.json()["data"]["preview_token"]
        stale = client.post(
            "/api/v1/imports/familybiz/commits",
            files={"file": ("review.xlsx", revised_payload), "preview_token": (None, token)},
            headers=mutation_headers(csrf),
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "PREVIEW_STALE"
        assert app.state.database.count("transactions") == 0

        first = client.post(
            "/api/v1/imports/familybiz/commits",
            files={"file": ("review.xlsx", payload), "preview_token": (None, token)},
            headers=mutation_headers(csrf),
        )
        assert first.status_code == 200
        with app.state.database.session() as session:
            assert session.scalar(select(func.count()).select_from(ApiIdempotencyRecordRow)) == 0
        first_history = client.get("/api/v1/imports/history?limit=1")
        assert first_history.status_code == 200
        assert first_history.json()["data"]["items"][0]["id"] == first.json()["data"]["batch_id"]
        assert first_history.json()["meta"]["limit"] == 1
        assert first_history.json()["meta"]["next_cursor"] is None

        # Import commit has archive effects and does not claim replay safety.


@pytest.mark.parametrize("resolution", ["accept_as_new", "dismiss", "link_existing"])
def test_reconciliation_resolution_is_candidate_checked_and_idempotent(
    tmp_path, familybiz_row, resolution
):
    _, _, _, app = make_api(tmp_path)
    original = make_workbook([familybiz_row])

    with ApiTestClient(app, base_url="https://testserver") as client:
        csrf = sign_in(client)
        service: ImportService = app.state.services
        initial = service.preview_import(original, "initial.xlsx")
        service.commit_import(original, initial.preview_token, "initial.xlsx")
        changed_row = list(familybiz_row)
        changed_row[5] = f"revision for {resolution}"
        changed = make_workbook([changed_row])
        changed_preview = service.preview_import(changed, "changed.xlsx")
        service.commit_import(changed, changed_preview.preview_token, "changed.xlsx")

        listed = client.get("/api/v1/reconciliation/cases?limit=10")
        assert listed.status_code == 200
        case = listed.json()["data"]["items"][0]
        assert case["candidates"]
        batch_history = client.get("/api/v1/imports/history?limit=10").json()["data"]["items"]
        current_batch = next(row for row in batch_history if row["id"] == case["import_batch_id"])
        assert "RECONCILIATION_REQUIRED" in current_batch["issue_codes"]
        if resolution == "link_existing":
            body = {"resolution": resolution, "transaction_id": case["candidates"][0]["id"]}
        else:
            body = {"resolution": resolution}

        key = f"resolution-{resolution}-attempt"
        endpoint = f"/api/v1/reconciliation/cases/{case['id']}/resolution"
        first = client.post(endpoint, json=body, headers=mutation_headers(csrf, **{"Idempotency-Key": key}))
        assert first.status_code == 200
        replay = client.post(endpoint, json=body, headers=mutation_headers(csrf, **{"Idempotency-Key": key}))
        assert replay.status_code == 200
        assert replay.json()["data"] == first.json()["data"]
        assert replay.headers["x-request-id"] != first.headers["x-request-id"]
        assert client.get("/api/v1/reconciliation/cases").json()["data"]["items"] == []

        different_body = (
            {"resolution": "accept_as_new"}
            if body["resolution"] == "dismiss"
            else {"resolution": "dismiss"}
        )
        reused = client.post(
            endpoint,
            json=different_body,
            headers=mutation_headers(csrf, **{"Idempotency-Key": key}),
        )
        assert reused.status_code == 409
        assert reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

        closed = client.post(
            endpoint,
            json=body,
            headers=mutation_headers(csrf, **{"Idempotency-Key": f"new-key-{resolution}"}),
        )
        assert closed.status_code == 409
        assert closed.json()["error"]["code"] == "RECONCILIATION_CONFLICT"


def test_reconciliation_rejects_unlisted_candidate_and_unknown_form_fields(
    tmp_path, familybiz_row
):
    _, _, _, app = make_api(tmp_path)
    original = make_workbook([familybiz_row])
    with ApiTestClient(app, base_url="https://testserver") as client:
        csrf = sign_in(client)
        service: ImportService = app.state.services
        preview = service.preview_import(original, "initial.xlsx")
        service.commit_import(original, preview.preview_token, "initial.xlsx")
        changed_row = list(familybiz_row)
        changed_row[5] = "reconciliation candidate"
        changed = make_workbook([changed_row])
        changed_preview = service.preview_import(changed, "changed.xlsx")
        service.commit_import(changed, changed_preview.preview_token, "changed.xlsx")
        case = client.get("/api/v1/reconciliation/cases").json()["data"]["items"][0]

        invalid_link = client.post(
            f"/api/v1/reconciliation/cases/{case['id']}/resolution",
            json={"resolution": "link_existing", "transaction_id": 999999},
            headers=mutation_headers(csrf, **{"Idempotency-Key": "bad-link"}),
        )
        assert invalid_link.status_code == 409
        assert invalid_link.json()["error"]["code"] == "RECONCILIATION_CONFLICT"
        assert len(client.get("/api/v1/reconciliation/cases").json()["data"]["items"]) == 1

        extra = client.post(
            "/api/v1/imports/familybiz/previews",
            files={"file": ("valid.xlsx", original), "unexpected": (None, "must be rejected")},
            headers=mutation_headers(csrf),
        )
        assert extra.status_code == 422
        assert extra.json()["error"]["code"] == "INVALID_UPLOAD"


def test_reconciliation_pagination_cursor_is_opaque_and_route_scoped(tmp_path, familybiz_row):
    _, _, _, app = make_api(tmp_path)
    with ApiTestClient(app, base_url="https://testserver") as client:
        sign_in(client)
        service: ImportService = app.state.services
        for index in range(3):
            row = list(familybiz_row)
            row[2] = f"merchant {index}"
            payload = make_workbook([row])
            preview = service.preview_import(payload, f"{index}.xlsx")
            service.commit_import(payload, preview.preview_token, f"{index}.xlsx")

        first = client.get("/api/v1/imports/history?limit=1")
        cursor = first.json()["meta"]["next_cursor"]
        assert cursor
        second = client.get(f"/api/v1/imports/history?limit=1&cursor={cursor}")
        assert second.status_code == 200
        assert second.json()["data"]["items"][0]["id"] != first.json()["data"]["items"][0]["id"]
        cross_route = client.get(f"/api/v1/reconciliation/cases?limit=1&cursor={cursor}")
        assert cross_route.status_code == 400
        assert cross_route.json()["error"]["code"] == "INVALID_CURSOR"
