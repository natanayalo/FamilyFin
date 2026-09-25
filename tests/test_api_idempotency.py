from __future__ import annotations

import pytest
from sqlalchemy import text

from family_finance.api.idempotency import IdempotencyKeyReusedError, IdempotencyStore
from family_finance.persistence.db import Database
from family_finance.planning import PlanningService


def test_service_write_rolls_back_with_response_and_retry_replays(tmp_path):
    database = Database(tmp_path / "api-idempotency.sqlite")
    planning = PlanningService(database)
    idempotency = IdempotencyStore(database)
    request = {"name": "Household budget", "currency": "ILS", "start_month": "2026-09"}
    scope = {
        "actor_id": "household-user-1",
        "http_method": "POST",
        "canonical_route": "/api/v1/planning/scenarios",
        "idempotency_key": "attempt-1",
        "request": request,
    }

    def crash_after_domain_write():
        created = planning.create_manual_scenario(
            name=request["name"], currency=request["currency"], start_month=request["start_month"]
        )
        assert database.count("planning_scenarios") == 1
        raise RuntimeError(f"simulated process failure after creating {created.id}")

    with pytest.raises(RuntimeError, match="simulated process failure"):
        idempotency.execute(**scope, operation=crash_after_domain_write)

    # The service used its ordinary write_session gateway, which joined the
    # API-owned transaction. The simulated failure rolled the domain write back.
    assert database.count("planning_scenarios") == 0
    assert database.count("planning_scenario_revisions") == 0

    def create_scenario():
        created = planning.create_manual_scenario(
            name=request["name"], currency=request["currency"], start_month=request["start_month"]
        )
        return 201, created.model_dump(mode="json")

    first = idempotency.execute(**scope, operation=create_scenario)
    assert first.status_code == 201
    assert first.replayed is False
    assert database.count("planning_scenarios") == 1
    assert database.count("planning_scenario_revisions") == 1

    replay = idempotency.execute(
        **scope,
        operation=lambda: pytest.fail("a committed idempotency response must skip the service"),
    )
    assert replay.status_code == first.status_code
    assert replay.body == first.body
    assert replay.replayed is True
    assert database.count("planning_scenarios") == 1
    assert database.count("planning_scenario_revisions") == 1

    with pytest.raises(IdempotencyKeyReusedError):
        idempotency.execute(
            **{**scope, "request": {**request, "name": "Different request"}},
            operation=lambda: pytest.fail("a reused key must never invoke the service"),
        )


def test_caught_exception_from_joined_read_session_marks_api_transaction_rollback_only(tmp_path):
    database = Database(tmp_path / "api-rollback-only.sqlite")
    planning = PlanningService(database)
    idempotency = IdempotencyStore(database)

    def write_then_catch_inner_session_error():
        planning.create_manual_scenario(name="Will roll back", start_month="2026-09")
        try:
            with database.session():
                raise ValueError("simulated joined read failure")
        except ValueError:
            pass
        # Even though the callback catches the inner error, a success response
        # must not allow the earlier domain write to commit.
        return 201, {"created": True}

    with pytest.raises(RuntimeError, match="marked rollback-only"):
        idempotency.execute(
            actor_id="household-user-1",
            http_method="POST",
            canonical_route="/api/v1/planning/scenarios",
            idempotency_key="caught-inner-error",
            request={"name": "Will roll back"},
            operation=write_then_catch_inner_session_error,
        )

    assert database.count("planning_scenarios") == 0
    assert database.count("planning_scenario_revisions") == 0
    with database.session() as session:
        assert session.execute(text("SELECT COUNT(*) FROM api_idempotency_records")).scalar_one() == 0
