"""Application configuration with privacy-safe local defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    project_root: Path = PROJECT_ROOT
    data_root: Path = PROJECT_ROOT / "data" / "local"
    max_compressed_bytes: int = 25 * 1024 * 1024
    max_uncompressed_bytes: int = 100 * 1024 * 1024
    max_rows: int = 200_000
    parser_version: str = "familybiz-v1"
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
        return cls(
            data_root=root,
            automation_backup_root=Path(backup_value).expanduser() if backup_value else None,
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
