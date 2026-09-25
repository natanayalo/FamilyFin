"""Small command-line entry point for local inspection and smoke checks."""

from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path

from family_finance.api.auth import AuthService, BootstrapAccount
from family_finance.audit import AuditService
from family_finance.automation import AutomationService
from family_finance.backup import BackupService
from family_finance.config import Settings
from family_finance.persistence.db import Database
from family_finance.services import ImportService


def main() -> None:
    parser = argparse.ArgumentParser(prog="family-finance")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect", help="Inspect a FamilyBiz XLSX")
    inspect_parser.add_argument("path", type=Path)
    subparsers.add_parser("audit", help="Audit the local database and archived imports")
    backup_parser = subparsers.add_parser("backup", help="Create a verified local backup")
    backup_parser.add_argument("destination", type=Path)
    verify_parser = subparsers.add_parser("verify-backup", help="Verify a local backup")
    verify_parser.add_argument("backup_directory", type=Path)
    automate_parser = subparsers.add_parser(
        "automate", help="Run the local FamilyBiz automation inbox"
    )
    automate_parser.add_argument("--dry-run", action="store_true")
    subparsers.add_parser(
        "auth-bootstrap", help="Securely configure the two household API accounts once"
    )
    reset_parser = subparsers.add_parser(
        "auth-reset-password", help="Recover an API account password from the local host"
    )
    reset_parser.add_argument("username")
    args = parser.parse_args()

    if args.command == "inspect":
        inspection = ImportService().inspect_familybiz(args.path.read_bytes())
        print(json.dumps(inspection.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return

    settings = Settings.from_environment()
    if args.command == "auth-bootstrap":
        accounts = []
        for label in ("First", "Second"):
            username = input(f"{label} account username: ").strip()
            display_name = input(f"{label} account display name: ").strip()
            password = getpass.getpass(f"{label} account password (14+ characters): ")
            confirmation = getpass.getpass("Confirm password: ")
            if password != confirmation:
                raise SystemExit("Password confirmation did not match")
            accounts.append(BootstrapAccount(username, display_name, password))
        settings.ensure_directories()
        auth = AuthService(Database(settings.database_path), settings)
        auth.bootstrap_accounts(accounts)
        print("Two household API accounts were configured.")
        return

    if args.command == "auth-reset-password":
        password = getpass.getpass("New password (14+ characters): ")
        confirmation = getpass.getpass("Confirm new password: ")
        if password != confirmation:
            raise SystemExit("Password confirmation did not match")
        settings.ensure_directories()
        auth = AuthService(Database(settings.database_path), settings)
        auth.reset_password(username=args.username, password=password)
        print("Password updated; active sessions were revoked.")
        return

    if args.command == "automate":
        result = AutomationService(settings=settings).run(dry_run=args.dry_run)
        print(json.dumps({
            "run_id": result.run_id,
            "status": result.status,
            "dry_run": result.dry_run,
            "audit_passed": result.audit_passed,
            "counts": result.counts,
            "issue_codes": result.issue_codes,
            "files": [
                {
                    "sha256": item.sha256,
                    "status": item.status,
                    "reason_code": item.reason_code,
                    "batch_id": item.batch_id,
                }
                for item in result.files
            ],
        }, ensure_ascii=False, indent=2))
        if result.status in {"failed", "blocked_audit", "blocked_backup", "failed_audit", "busy"}:
            raise SystemExit(1)
    elif args.command == "audit":
        report = AuditService(settings=settings).run()
        print(report.model_dump_json(indent=2))
        if not report.passed:
            raise SystemExit(1)
    elif args.command == "backup":
        manifest = BackupService(settings=settings).create(args.destination)
        print(manifest.model_dump_json(indent=2))
    elif args.command == "verify-backup":
        verification = BackupService(settings=settings).verify(args.backup_directory)
        print(verification.model_dump_json(indent=2))
        if not verification.passed:
            raise SystemExit(1)
