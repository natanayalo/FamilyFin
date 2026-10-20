"""Real browser-test stack with synthetic data, never the developer's household copy."""

from __future__ import annotations

import os
import signal
import tempfile
import time
from pathlib import Path

from family_finance.api.auth import AuthService, BootstrapAccount
from family_finance.config import Settings
from family_finance.localdev import (
    FRONTEND,
    PYTHON,
    Processes,
    local_environment,
    require_free_ports,
)
from family_finance.persistence.db import Database
from family_finance.services import ImportService
from tests.conftest import make_workbook


def main() -> None:
    os.umask(0o077)

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with tempfile.TemporaryDirectory(prefix="familyfin-live-") as directory:
        root = Path(directory)
        env = local_environment(root / "data", web_port=3101, api_port=8101)
        env["FAMILY_FINANCE_AUTOMATION_BACKUP_ROOT"] = str(root / "backups")
        require_free_ports([3101, 8101])
        os.environ.update(env)
        settings = Settings.from_environment()
        settings.ensure_directories()
        database = Database(settings.database_path)
        AuthService(database, settings).bootstrap_accounts(
            [
                BootstrapAccount("qa-one", "בדיקה מקומית", "Local-test-password-One!"),
                BootstrapAccount("qa-two", "בדיקה שנייה", "Local-test-password-Two!"),
            ]
        )
        row = [
            "19/09/2026",
            -17.40,
            "Synthetic merchant",
            "19/09/2026",
            "food",
            "household",
            "ILS",
            "ILS",
            -17.40,
        ]
        service = ImportService(settings=settings, database=database)
        conflicting = ["15/09/2026", 72.4, "Cloud conflict fixture", "15/09/2026", None, "הכנסות מעסק", "ILS", "ILS", -72.4]
        zero_fee = ["15/09/2026", 0, "Waived card fee fixture", "15/09/2026", "fee", "שונות", "ILS", "ILS", -17.9]
        payload = make_workbook([row, conflicting, zero_fee])
        preview = service.preview_import(payload)
        service.commit_import(payload, preview.preview_token, "seed.xlsx")
        conflict_id = next(item["id"] for item in service.classification_service.repository.accepted_transactions() if item["description"] == "Cloud conflict fixture")
        service.classification_service.save_override(conflict_id, economic_class="consumption", analysis_category="אחסון ענן", expense_behavior="fixed", reason="Stored conflicting fixture")
        zero_id = next(item["id"] for item in service.classification_service.repository.accepted_transactions() if item["description"] == "Waived card fee fixture")
        service.classification_service.save_override(zero_id, economic_class="consumption", expense_behavior="fixed", reason="Stored zero-fee fixture")
        (root / "upload.xlsx").write_bytes(
            make_workbook([row, conflicting, zero_fee, [*row[:2], "Second merchant", *row[3:]]])
        )
        database.engine.dispose()
        fixture_marker = FRONTEND / ".next-local/live-fixture-path"
        fixture_marker.parent.mkdir(parents=True, exist_ok=True)
        fixture_marker.write_text(str(root / "upload.xlsx"))
        with Processes(env) as processes:
            processes.start("API", [str(PYTHON), "-m", "family_finance.api.cli"])
            processes.ready("http://127.0.0.1:8101/api/v1/health")
            processes.start("PWA", ["npm", "run", "start", "--", "--port", "3101"], cwd=FRONTEND)
            processes.ready("http://127.0.0.1:3101/api/v1/health")
            try:
                while True:
                    processes.ensure_running()
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
            finally:
                fixture_marker.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
