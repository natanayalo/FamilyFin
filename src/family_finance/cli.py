"""Small command-line entry point for local inspection and smoke checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from family_finance.audit import AuditService
from family_finance.backup import BackupService
from family_finance.config import Settings
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
    args = parser.parse_args()

    if args.command == "inspect":
        inspection = ImportService().inspect_familybiz(args.path.read_bytes())
        print(json.dumps(inspection.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return

    settings = Settings.from_environment()
    if args.command == "audit":
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
