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

    @property
    def database_path(self) -> Path:
        return self.data_root / "family_finance.sqlite3"

    @property
    def archive_root(self) -> Path:
        return self.data_root / "imports"

    @property
    def log_root(self) -> Path:
        return self.data_root / "logs"

    @property
    def log_path(self) -> Path:
        return self.log_root / "family_finance.jsonl"

    @classmethod
    def from_environment(cls) -> Settings:
        root = Path(os.environ.get("FAMILY_FINANCE_DATA_ROOT", cls.data_root))
        return cls(data_root=root)

    def ensure_directories(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.archive_root.mkdir(parents=True, exist_ok=True)
        self.log_root.mkdir(parents=True, exist_ok=True)
