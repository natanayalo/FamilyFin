"""Small command-line entry point for local inspection and smoke checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from family_finance.services import ImportService


def main() -> None:
    parser = argparse.ArgumentParser(prog="family-finance")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect", help="Inspect a FamilyBiz XLSX")
    inspect_parser.add_argument("path", type=Path)
    args = parser.parse_args()

    if args.command == "inspect":
        inspection = ImportService().inspect_familybiz(args.path.read_bytes())
        print(json.dumps(inspection.model_dump(mode="json"), ensure_ascii=False, indent=2))

