"""Application configuration with privacy-safe local defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_MAX_JSON_BODY_BYTES = 1 * 1024 * 1024


@dataclass(frozen=True)
class Settings:
    project_root: Path = PROJECT_ROOT
    data_root: Path = PROJECT_ROOT / "data" / "local"
    max_compressed_bytes: int = 25 * 1024 * 1024
    max_uncompressed_bytes: int = 100 * 1024 * 1024
    max_rows: int = 50_000
    parser_version: str = "familybiz-v2"
    planning_csv_max_bytes: int = 10 * 1024 * 1024
    planning_csv_max_rows: int = 5_000
    planning_csv_max_columns: int = 100
    planning_csv_max_field_length: int = 10_000
    planning_parser_version: str = "planning-csv-v1"
    net_worth_csv_max_bytes: int = 10 * 1024 * 1024
    net_worth_csv_max_rows: int = 10_000
    net_worth_csv_max_columns: int = 20
    net_worth_csv_max_field_length: int = 10_000
    net_worth_parser_version: str = "net-worth-csv-v1"
    automation_stability_delay_seconds: float = 0.05
    automation_algorithm_version: str = "phase8-insights-v1"
    automation_backup_root: Path | None = None
    api_session_hours: int = 8
    api_max_request_bytes: int = 1 * 1024 * 1024
    api_public_origin: str | None = None
    api_trusted_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")

    def __post_init__(self) -> None:
        if not 1 <= self.api_session_hours <= 24:
            raise ValueError("API session lifetime must be between 1 and 24 hours")
        if not 1024 <= self.api_max_request_bytes <= API_MAX_JSON_BODY_BYTES:
            raise ValueError("API JSON request limit must be between 1 KiB and 1 MiB")

    @property
    def database_path(self) -> Path:
        return self.data_root / "family_finance.sqlite3"

    @property
    def archive_root(self) -> Path:
        return self.data_root / "imports"

    @property
    def planning_archive_root(self) -> Path:
        return self.data_root / "planning-imports"

    @property
    def net_worth_archive_root(self) -> Path:
        return self.data_root / "net-worth-imports"

    @property
    def automation_root(self) -> Path:
        return self.data_root / "automation"

    @property
    def automation_inbox_root(self) -> Path:
        return self.automation_root / "inbox"

    @property
    def automation_processed_root(self) -> Path:
        return self.automation_root / "processed"

    @property
    def automation_needs_review_root(self) -> Path:
        return self.automation_root / "needs-review"

    @property
    def automation_lock_path(self) -> Path:
        return self.automation_root / "automation.lock"

    @property
    def log_root(self) -> Path:
        return self.data_root / "logs"

    @property
    def log_path(self) -> Path:
        return self.log_root / "family_finance.jsonl"

    @classmethod
    def from_environment(cls) -> Settings:
        root = Path(os.environ.get("FAMILY_FINANCE_DATA_ROOT", cls.data_root))
        backup_value = os.environ.get("FAMILY_FINANCE_AUTOMATION_BACKUP_ROOT", "").strip()
        trusted_hosts = tuple(
            item.strip()
            for item in os.environ.get(
                "FAMILY_FINANCE_API_TRUSTED_HOSTS", "localhost,127.0.0.1"
            ).split(",")
            if item.strip()
        )
        return cls(
            data_root=root,
            automation_backup_root=Path(backup_value).expanduser() if backup_value else None,
            api_session_hours=min(
                24, max(1, int(os.environ.get("FAMILY_FINANCE_API_SESSION_HOURS", "8")))
            ),
            api_max_request_bytes=min(
                API_MAX_JSON_BODY_BYTES,
                max(
                    1024,
                    int(os.environ.get("FAMILY_FINANCE_API_MAX_REQUEST_BYTES", str(1024 * 1024))),
                ),
            ),
            api_public_origin=os.environ.get("FAMILY_FINANCE_API_PUBLIC_ORIGIN", "").strip() or None,
            api_trusted_hosts=trusted_hosts or ("localhost", "127.0.0.1"),
        )

    def ensure_directories(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.archive_root.mkdir(parents=True, exist_ok=True)
        self.planning_archive_root.mkdir(parents=True, exist_ok=True)
        self.net_worth_archive_root.mkdir(parents=True, exist_ok=True)
        self.automation_inbox_root.mkdir(parents=True, exist_ok=True)
        self.automation_processed_root.mkdir(parents=True, exist_ok=True)
        self.automation_needs_review_root.mkdir(parents=True, exist_ok=True)
        self.log_root.mkdir(parents=True, exist_ok=True)
