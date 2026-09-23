"""Privacy-safe rotating JSON-lines event logging."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class JsonEventLogger:
    """Emit only aggregate operational fields; never accept arbitrary context."""

    def __init__(self, path: str | Path, *, max_bytes: int = 1_000_000, backup_count: int = 5) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(f"family_finance.events.{self.path}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        if not self._logger.handlers:
            handler = RotatingFileHandler(
                self.path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)

    def event(
        self,
        name: str,
        *,
        status: str | None = None,
        duration_ms: float | None = None,
        counts: dict[str, int] | None = None,
        issue_codes: list[str] | tuple[str, ...] | None = None,
        error_codes: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "event": str(name),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if duration_ms is not None:
            payload["duration_ms"] = round(float(duration_ms), 3)
        if status is not None:
            payload["status"] = str(status)
        if counts:
            payload["counts"] = {str(key): int(value) for key, value in counts.items()}
        if issue_codes:
            payload["issue_codes"] = sorted({str(code) for code in issue_codes})
        if error_codes:
            payload["error_codes"] = sorted({str(code) for code in error_codes})
        self._logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


__all__ = ["JsonEventLogger"]
