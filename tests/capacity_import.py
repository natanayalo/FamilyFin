"""Standalone subprocess capacity check for the pinned Python 3.12 runtime.

Run with ``.venv/bin/python tests/capacity_import.py``. It deliberately stays
outside the correctness-test suite because generating and parsing a full-sized
workbook is a separate, resource-intensive check. The initial 200,000-row
target exceeded 512 MiB RSS; ``Settings.max_rows`` is now 50,000, and this
check runs the same row mix at that configured maximum.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from family_finance.config import Settings
from family_finance.importers.familybiz import HEADERS

TOTAL_ROWS = 50_000
LONG_DESCRIPTION = " with a deliberately long description " + ("detail " * 124) + "detail"


def _transaction_row(kind: str, index: int) -> list[object]:
    if kind == "repeat":
        booking = date(2010, 1, 1)
        amount = -27.31
        description = "same repeated purchase"
    else:
        day_offset = index
        booking = date(2000, 1, 1) + timedelta(days=day_offset)
        amount = -float((index % 8000) + 1)
        description = f"{kind} transaction {index}"
    if index % 10 == 0:
        description += LONG_DESCRIPTION
    formatted = booking.strftime("%d/%m/%Y")
    return [formatted, amount, description, formatted, "purchase", "household", "ILS", "ILS", amount]


def _write_workbook(path: Path) -> None:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("FamilyBiz")
    sheet.append(["", "", "", "", "", "", "", "", "", ""])
    sheet.append([None] * 10)
    sheet.append(["כאל", "capacity-account", None, None, None, None, None, None, None, None])
    sheet.append([None] * 10)
    sheet.append([None, *HEADERS])

    exact_count = int(TOTAL_ROWS * 0.45)
    repeat_count = int(TOTAL_ROWS * 0.15)
    plausible_count = int(TOTAL_ROWS * 0.15)
    new_count = TOTAL_ROWS - exact_count - repeat_count - plausible_count
    for index in range(exact_count):
        sheet.append([None, *_transaction_row("exact", index)])
    for index in range(repeat_count):
        sheet.append([None, *_transaction_row("repeat", index)])
    for index in range(plausible_count):
        incoming = _transaction_row("candidate", 300_000 + index)
        incoming[2] = f"revised candidate {index}"
        if index % 10 == 0:
            incoming[2] += LONG_DESCRIPTION
        sheet.append([None, *incoming])
    for index in range(new_count):
        sheet.append([None, *_transaction_row("new", 600_000 + index)])
    workbook.save(path)


def _worker(source_path: Path, data_root: Path) -> None:
    worker_code = r'''
import hashlib, json, resource, sqlite3, sys
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "src"))
from family_finance.config import Settings
from family_finance.services import ImportService

root = Path(sys.argv[1])
workbook_path = Path(sys.argv[2])
data_root = Path(sys.argv[3])
app = ImportService(Settings(project_root=root, data_root=data_root))
connection = sqlite3.connect(app.settings.database_path)
connection.execute(
    "INSERT INTO accounts (account_kind, provider, source_reference_fingerprint, display_label, currency) "
    "VALUES (?, ?, ?, ?, ?)",
    ("card", "כאל", "", "כאל card", "ILS"),
)
account_id = connection.execute("SELECT id FROM accounts").fetchone()[0]
reference_fingerprint = hashlib.sha256(json.dumps(
    {"provider": "כאל", "reference": "capacity-account"},
    ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8")).hexdigest()
connection.execute("UPDATE accounts SET source_reference_fingerprint=? WHERE id=?",
                   (reference_fingerprint, account_id))
created_at = "2026-01-01T00:00:00+00:00"
source_file_id = connection.execute(
    "INSERT INTO source_files (sha256, original_filename, archived_path, compressed_bytes, "
    "uncompressed_bytes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
    ("b" * 64, "capacity-history.xlsx", str(data_root / "capacity-history.xlsx"), 1, 1, created_at),
).lastrowid
batch_id = "capacity-history"
connection.execute(
    "INSERT INTO import_batches (id, source_file_id, parser_version, baseline_batch_id, report_start, "
    "report_end, max_transaction_date, freshness_days, status, statistics_json, error_code, created_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    (batch_id, source_file_id, "familybiz-v2", None, None, None, None, None, "committed",
     json.dumps({"total_records": 30_000, "inserted": 30_000}), None, created_at),
)
insert_transaction_sql = (
    "INSERT INTO transactions (account_id, booking_date, allocation_date, amount, currency, "
    "original_currency, original_amount, description, movement_type, category, state, created_at, updated_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
insert_source_sql = (
    "INSERT INTO source_records (id, import_batch_id, account_id, sheet_name, section_index, "
    "source_row_number, raw_payload_json, normalized_json, row_fingerprint, validation_state, "
    "issues_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
insert_link_sql = (
    "INSERT INTO transaction_sources (transaction_id, source_record_id, match_method, linked_at) "
    "VALUES (?, ?, ?, ?)"
)
transaction_id_start = connection.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM transactions").fetchone()[0]
source_record_id_start = connection.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM source_records").fetchone()[0]

for offset in range(0, 30_000, 1_000):
    transaction_rows = []
    source_rows = []
    link_rows = []
    for local_index in range(min(1_000, 30_000 - offset)):
        index = offset + local_index
        if index < 22_500:
            logical_index = index
            date_offset = logical_index
            description = f"exact transaction {logical_index}"
            if logical_index % 10 == 0:
                description += " with a deliberately long description " + ("detail " * 124) + "detail"
        else:
            logical_index = index - 22_500
            date_offset = 300_000 + logical_index
            description = f"candidate transaction {logical_index}"
        booking = date(2000, 1, 1) + timedelta(days=date_offset)
        amount = -float((date_offset % 8000) + 1)
        value = str(amount)
        transaction_id = transaction_id_start + index
        source_record_id = source_record_id_start + index
        transaction_rows.append((
            account_id, booking.isoformat(), booking.isoformat(), value, "ILS", "ILS", value,
            description, "purchase", "household", "accepted", created_at, created_at,
        ))
        normalized = {
            "booking_date": booking.isoformat(),
            "allocation_date": booking.isoformat(),
            "amount": value,
            "currency": "ILS",
            "original_currency": "ILS",
            "original_amount": value,
            "description": description,
            "movement_type": "purchase",
            "category": "household",
        }
        source_rows.append((
            source_record_id, batch_id, account_id, "FamilyBiz", 1, 6 + index, "{}",
            json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            f"capacity-source-{source_record_id}", "accepted", "[]", created_at,
        ))
        link_rows.append((transaction_id, source_record_id, "inserted", created_at))
    connection.executemany(insert_transaction_sql, transaction_rows)
    connection.executemany(insert_source_sql, source_rows)
    connection.executemany(insert_link_sql, link_rows)
connection.commit()
connection.close()

payload = workbook_path.read_bytes()
preview = app.preview_import(payload, workbook_path.name)
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
if sys.platform != "darwin":
    peak *= 1024
statistics = preview.predicted_statistics
print(json.dumps({
    "python": sys.version.split()[0],
    "rows": preview.candidate_count,
    "uncompressed_bytes": preview.inspection.uncompressed_bytes,
    "peak_rss_bytes": peak,
    "inserted": statistics.inserted,
    "unchanged": statistics.unchanged,
    "ambiguous": statistics.ambiguous,
    "plan_bytes": len(preview.decision_plan_json.encode("utf-8")),
}, sort_keys=True))
'''
    result = subprocess.run(
        [sys.executable, "-c", worker_code, str(ROOT), str(source_path), str(data_root)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise SystemExit(result.stderr or f"Capacity worker exited {result.returncode}")
    report = json.loads(result.stdout.strip().splitlines()[-1])
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["rows"] != TOTAL_ROWS:
        raise SystemExit(f"Expected {TOTAL_ROWS:,} rows, got {report['rows']:,}")
    if report["peak_rss_bytes"] >= 512 * 1024 * 1024:
        raise SystemExit(
            f"Peak RSS {report['peak_rss_bytes'] / 1024 / 1024:.1f} MiB exceeds 512 MiB"
        )
    if (report["unchanged"], report["ambiguous"], report["inserted"]) != (22_500, 7_500, 20_000):
        raise SystemExit(f"Unexpected decision totals: {report}")


def main() -> None:
    if Settings().max_rows != TOTAL_ROWS:
        raise SystemExit(
            f"Capacity fixture is for {TOTAL_ROWS:,} rows, configured cap is {Settings().max_rows:,}"
        )
    with tempfile.TemporaryDirectory(prefix="familyfin-import-capacity-") as temp:
        temp_root = Path(temp)
        source = temp_root / "capacity.xlsx"
        _write_workbook(source)
        _worker(source, temp_root / "local-data")


if __name__ == "__main__":
    main()
