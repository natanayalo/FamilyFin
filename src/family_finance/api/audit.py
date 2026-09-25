"""Safe actor-attribution metadata for authenticated API actions."""

from __future__ import annotations

import re
import uuid

from sqlalchemy.orm import Session

from family_finance.persistence.db import utc_now
from family_finance.persistence.models import ActorAuditEventRow

_SAFE_LABEL = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


def record_actor_audit(
    session: Session,
    *,
    actor_id: str,
    event_type: str,
    request_id: str,
    target_type: str | None = None,
    outcome: str = "success",
) -> None:
    """Append only identifiers and outcome codes, never request/domain values.

    Call with the same SQLAlchemy session as the financial write when the
    actor event must commit atomically with a mutation.
    """

    for label, value in (("event_type", event_type), ("outcome", outcome)):
        if not _SAFE_LABEL.fullmatch(value):
            raise ValueError(f"{label} must be a short lower-case code")
    if target_type is not None and not _SAFE_LABEL.fullmatch(target_type):
        raise ValueError("target_type must be a short lower-case code")
    if not actor_id or len(actor_id) > 100 or not request_id or len(request_id) > 100:
        raise ValueError("Actor and request identifiers must be non-empty and bounded")
    session.add(
        ActorAuditEventRow(
            id=str(uuid.uuid4()),
            actor_id=actor_id,
            event_type=event_type,
            request_id=request_id,
            target_type=target_type,
            outcome=outcome,
            created_at=utc_now(),
        )
    )
