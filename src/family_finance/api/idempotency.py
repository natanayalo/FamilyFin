"""Atomic request idempotency for API mutations that join service transactions.

This module is infrastructure only. A route may use it only when every
database mutation it invokes goes through ``Database.write_session`` (or
``Database.session``) on the same Database instance and it has no unhandled
filesystem or other external side effects.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from family_finance.persistence.db import Database, utc_now
from family_finance.persistence.models import ApiIdempotencyRecordRow


class IdempotencyKeyReusedError(ValueError):
    """An idempotency key was already committed for a different request."""


@dataclass(frozen=True)
class IdempotencyResponse:
    status_code: int
    body: Any
    replayed: bool


def canonical_json(value: Any) -> str:
    """Serialize a JSON transport value deterministically, rejecting NaN/Infinity."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_request_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class IdempotencyStore:
    """Run a mutation and persist its completed response in one SQLite commit."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def execute(
        self,
        *,
        actor_id: str,
        http_method: str,
        canonical_route: str,
        idempotency_key: str,
        request: Any,
        operation: Callable[[], tuple[int, Any]],
    ) -> IdempotencyResponse:
        """Execute once or replay a matching committed response.

        The write lock is acquired before the lookup, so concurrent same-key
        requests serialize and the later request observes the committed row.
        Raising from ``operation`` or response serialization rolls back both
        service writes and the idempotency record.
        """

        scope = (actor_id.strip(), http_method.upper(), canonical_route.strip(), idempotency_key.strip())
        if any(not value for value in scope):
            raise ValueError("Idempotency scope fields must be non-empty")
        method = scope[1]
        if method not in {"POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("Idempotency is only supported for mutating HTTP methods")
        request_hash = canonical_request_hash(request)

        with self.database.api_write_unit_of_work() as session:
            statement = select(ApiIdempotencyRecordRow).where(
                ApiIdempotencyRecordRow.actor_id == scope[0],
                ApiIdempotencyRecordRow.http_method == method,
                ApiIdempotencyRecordRow.canonical_route == scope[2],
                ApiIdempotencyRecordRow.idempotency_key == scope[3],
            )
            existing = session.execute(statement).scalar_one_or_none()
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise IdempotencyKeyReusedError(
                        "Idempotency key was already used for a different request"
                    )
                result = IdempotencyResponse(
                    status_code=existing.response_status,
                    body=json.loads(existing.response_body),
                    replayed=True,
                )
            else:
                status_code, body = operation()
                if not 100 <= int(status_code) <= 599:
                    raise ValueError("Response status must be a valid HTTP status code")
                body_json = canonical_json(body)
                session.add(
                    ApiIdempotencyRecordRow(
                        id=str(uuid.uuid4()),
                        actor_id=scope[0],
                        http_method=method,
                        canonical_route=scope[2],
                        idempotency_key=scope[3],
                        request_hash=request_hash,
                        response_status=int(status_code),
                        response_body=body_json,
                        created_at=utc_now(),
                    )
                )
                result = IdempotencyResponse(
                    status_code=int(status_code), body=json.loads(body_json), replayed=False
                )

        # The context commits before a caller can send this response.
        return result
