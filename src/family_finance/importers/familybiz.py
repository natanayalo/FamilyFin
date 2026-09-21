"""Strict, privacy-safe FamilyBiz XLSX inspection and normalization."""

from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from family_finance.config import Settings
from family_finance.models import (
    AccountDescriptor,
    DataQualityIssue,
    ImportInspection,
    ParsedSourceRecord,
)

HEADERS = [
    "תאריך",
    "סכום",
    "תאור",
    "תאריך ביעדים",
    "סוג תנועה",
    "קטגוריה",
    "מטבע",
    "מטבע מקורי",
    "תנועה מקורית",
]
REPORT_END_RE = re.compile(r"(\d{2}/\d{2}/\d{4})\s*:עד תאריך")
REPORT_START_RE = re.compile(r"(\d{2}/\d{2}/\d{4})\s*:מתאריך")


class FamilyBizSchemaError(ValueError):
    """Raised when a workbook cannot be safely interpreted as FamilyBiz."""


@dataclass(frozen=True)
class ParsedWorkbook:
    inspection: ImportInspection
    records: list[ParsedSourceRecord]
    issues: list[DataQualityIssue]


def normalize_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("_x000D_", "\n")
    text = text.strip()
    while text.startswith("'"):
        text = text[1:].lstrip()
    return text.strip() or None


def normalize_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value).strip().lstrip("'"))
    except (InvalidOperation, ValueError) as exc:
        raise FamilyBizSchemaError(f"Non-numeric amount: {value!r}") from exc
    if not result.is_finite():
        raise FamilyBizSchemaError(f"Non-finite amount: {value!r}")
    return result


def parse_date(value: Any, *, field: str, row_number: int) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = normalize_text(value)
    if not text:
        raise FamilyBizSchemaError(f"Missing {field} at source row {row_number}")
    try:
        return datetime.strptime(text, "%d/%m/%Y").date()  # noqa: DTZ007
    except ValueError as exc:
        raise FamilyBizSchemaError(
            f"Invalid {field} {text!r} at source row {row_number}; expected dd/mm/yyyy"
        ) from exc


def sha256_bytes(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def _safe_json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class FamilyBizParser:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_environment()

    def inspect(self, file_bytes: bytes, filename: str | None = None) -> ImportInspection:
        return self.parse(file_bytes, filename=filename).inspection

    def parse(self, file_bytes: bytes, filename: str | None = None) -> ParsedWorkbook:
        uncompressed_bytes = self._validate_container(file_bytes, filename)
        file_hash = sha256_bytes(file_bytes)
        try:
            workbook = load_workbook(io.BytesIO(file_bytes), read_only=False, data_only=False)
        except (InvalidFileException, OSError, ValueError, zipfile.BadZipFile) as exc:
            raise FamilyBizSchemaError(f"Unable to read XLSX workbook: {exc}") from exc

        if len(workbook.sheetnames) != 1:
            raise FamilyBizSchemaError("Expected exactly one FamilyBiz worksheet")
        worksheet = workbook.active
        matrix = [
            [
                worksheet.cell(row=row_number, column=column).value
                for column in range(1, 11)
            ]
            for row_number in range(1, worksheet.max_row + 1)
        ]
        header_rows = self._find_headers(matrix)
        if not header_rows:
            raise FamilyBizSchemaError("FamilyBiz headers not found")

        report_start = self._report_date(matrix[0] if matrix else [], REPORT_START_RE)
        report_end = self._report_date(matrix[0] if matrix else [], REPORT_END_RE)
        records: list[ParsedSourceRecord] = []
        issues: list[DataQualityIssue] = []
        section_count = len(header_rows)

        for section_number, header_row in enumerate(header_rows, start=1):
            next_header = (
                header_rows[section_number]
                if section_number < section_count
                else len(matrix) + 1
            )
            account = self._account_for_section(matrix, header_row, section_number)
            for source_row_number in range(header_row + 1, next_header):
                raw_row = matrix[source_row_number - 1]
                if not any(value not in (None, "") for value in raw_row):
                    continue
                if raw_row[0] not in (None, ""):
                    is_expected_account_metadata = (
                        source_row_number == next_header - 2
                        and not any(
                            value not in (None, "")
                            for value in matrix[source_row_number]
                        )
                    )
                    if is_expected_account_metadata:
                        # Account metadata for the following section sits between headers.
                        continue
                    raise FamilyBizSchemaError(
                        f"Unexpected non-empty row at source row {source_row_number}"
                    )
                if raw_row[1] in (None, ""):
                    raise FamilyBizSchemaError(
                        f"Unexpected non-empty row without a date at source row {source_row_number}"
                    )
                record = self._parse_record(
                    raw_row,
                    account=account,
                    source_row_number=source_row_number,
                    section_number=section_number,
                    sheet_name=worksheet.title,
                )
                records.append(record)
                issues.extend(record.issues)

        if not records:
            raise FamilyBizSchemaError("FamilyBiz worksheet contains no transaction rows")

        currencies = Counter(record.currency for record in records)
        account_kinds = Counter(record.account.kind for record in records)
        issue_counts = Counter(issue.code for issue in issues)
        dates = [record.booking_date for record in records]
        inspection = ImportInspection(
            parser_version=self.settings.parser_version,
            file_sha256=file_hash,
            filename=Path(filename).name if filename else None,
            compressed_bytes=len(file_bytes),
            uncompressed_bytes=uncompressed_bytes,
            sheet_names=list(workbook.sheetnames),
            section_count=section_count,
            transaction_count=len(records),
            report_start=report_start,
            report_end=report_end,
            min_booking_date=min(dates),
            max_booking_date=max(dates),
            currencies=dict(currencies),
            account_kinds=dict(account_kinds),
            issue_counts=dict(issue_counts),
            preview_rows=[self._preview_row(record) for record in records[:20]],
        )
        return ParsedWorkbook(inspection=inspection, records=records, issues=issues)

    def _validate_container(self, file_bytes: bytes, filename: str | None) -> int:
        if not file_bytes:
            raise FamilyBizSchemaError("Empty upload")
        if filename and Path(filename).suffix.lower() not in {".xlsx"}:
            raise FamilyBizSchemaError("Only .xlsx FamilyBiz exports are supported")
        if len(file_bytes) > self.settings.max_compressed_bytes:
            raise FamilyBizSchemaError(
                "Compressed upload exceeds "
                f"{self.settings.max_compressed_bytes // 1024 // 1024} MiB limit"
            )
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
                names = set(archive.namelist())
                if "xl/vbaProject.bin" in names or any(
                    name.endswith("vbaProject.bin") for name in names
                ):
                    raise FamilyBizSchemaError("Macro-enabled workbooks are not accepted")
                uncompressed = sum(info.file_size for info in archive.infolist())
                if uncompressed > self.settings.max_uncompressed_bytes:
                    raise FamilyBizSchemaError("Uncompressed upload exceeds 100 MiB limit")
                if archive.testzip() is not None:
                    raise FamilyBizSchemaError("Corrupt XLSX ZIP content")
                row_count = 0
                worksheet_entries = [
                    name
                    for name in archive.namelist()
                    if name.startswith("xl/worksheets/") and name.endswith(".xml")
                ]
                for worksheet_entry in worksheet_entries:
                    try:
                        with archive.open(worksheet_entry) as worksheet_xml:
                            for _, element in ElementTree.iterparse(
                                worksheet_xml, events=("end",)
                            ):
                                if element.tag.rsplit("}", 1)[-1] == "row":
                                    row_count += 1
                                    if row_count > self.settings.max_rows:
                                        raise FamilyBizSchemaError(
                                            f"Workbook exceeds {self.settings.max_rows:,} row limit"
                                        )
                                element.clear()
                    except ElementTree.ParseError as exc:
                        raise FamilyBizSchemaError("Malformed worksheet XML") from exc
                return uncompressed
        except zipfile.BadZipFile as exc:
            raise FamilyBizSchemaError("Malformed XLSX ZIP content") from exc

    @staticmethod
    def _find_headers(matrix: list[list[Any]]) -> list[int]:
        rows: list[int] = []
        for index, row in enumerate(matrix, start=1):
            values = [normalize_text(value) for value in row[1:10]]
            if values == HEADERS:
                rows.append(index)
            elif values and values[0] == "תאריך" and any(values):
                raise FamilyBizSchemaError(
                    f"Unknown or changed FamilyBiz headers at source row {index}"
                )
        return rows

    @staticmethod
    def _report_date(row: list[Any], pattern: re.Pattern[str]) -> date | None:
        text = " ".join(normalize_text(value) or "" for value in row[:3])
        match = pattern.search(text)
        if not match:
            return None
        return datetime.strptime(match.group(1), "%d/%m/%Y").date()  # noqa: DTZ007

    def _account_for_section(
        self,
        matrix: list[list[Any]],
        header_row: int,
        section_number: int,
    ) -> AccountDescriptor:
        # FamilyBiz places account metadata two rows before each repeated header.
        metadata_row = matrix[header_row - 3] if header_row >= 3 else []
        provider = normalize_text(metadata_row[0] if len(metadata_row) > 0 else None)
        reference = normalize_text(metadata_row[1] if len(metadata_row) > 1 else None)
        label = normalize_text(metadata_row[2] if len(metadata_row) > 2 else None)
        if not provider or not reference:
            raise FamilyBizSchemaError(
                f"Missing account identity before FamilyBiz section {section_number}"
            )
        kind = "bank" if "בנק" in provider else "card"
        currency = "USD" if reference.upper().endswith("USD") else "ILS"
        if label and label.upper() == "USD":
            currency = "USD"
        return AccountDescriptor(
            provider=provider,
            kind=kind,
            display_label=f"{provider} {kind}",
            source_reference_fingerprint=_fingerprint(
                {"provider": provider, "reference": reference}
            ),
            currency=currency,
        )

    def _parse_record(
        self,
        raw_row: list[Any],
        *,
        account: AccountDescriptor,
        source_row_number: int,
        section_number: int,
        sheet_name: str,
    ) -> ParsedSourceRecord:
        for index, value in enumerate(raw_row[1:10], start=1):
            if isinstance(value, str) and value.startswith("="):
                raise FamilyBizSchemaError(
                    "Formula in required FamilyBiz data cell at source row "
                    f"{source_row_number}, column {index + 1}"
                )
        booking_date = parse_date(
            raw_row[1], field="booking date", row_number=source_row_number
        )
        allocation_date = parse_date(
            raw_row[4], field="allocation date", row_number=source_row_number
        )
        amount = normalize_decimal(raw_row[2])
        if amount is None:
            raise FamilyBizSchemaError(f"Missing amount at source row {source_row_number}")
        description = normalize_text(raw_row[3])
        category = normalize_text(raw_row[6])
        currency = normalize_text(raw_row[7])
        if not description or not category or not currency:
            raise FamilyBizSchemaError(
                f"Missing required transaction value at source row {source_row_number}"
            )
        movement_type = normalize_text(raw_row[5])
        original_currency = normalize_text(raw_row[8])
        original_amount = normalize_decimal(raw_row[9])
        normalized_payload = [_safe_json_value(value) for value in raw_row]
        row_fingerprint = _fingerprint(
            {
                "account": account.source_reference_fingerprint,
                "row": normalized_payload,
            }
        )
        record_issues: list[DataQualityIssue] = []
        if not movement_type:
            record_issues.append(
                DataQualityIssue(
                    code="MISSING_MOVEMENT_TYPE",
                    message="Movement type is missing in the source row",
                    source_row=source_row_number,
                    section_index=section_number,
                )
            )
        if original_currency is None or original_amount is None:
            record_issues.append(
                DataQualityIssue(
                    code="MISSING_ORIGINAL_VALUE",
                    message="Original currency or amount is missing",
                    source_row=source_row_number,
                    section_index=section_number,
                )
            )
        if allocation_date != booking_date:
            record_issues.append(
                DataQualityIssue(
                    code="ALLOCATION_DATE_DIFFERS",
                    message="Allocation date differs from booking date",
                    source_row=source_row_number,
                    section_index=section_number,
                )
            )
        if amount == 0 and original_amount not in (None, Decimal(0)):
            record_issues.append(
                DataQualityIssue(
                    code="ZERO_AMOUNT_WITH_ORIGINAL_VALUE",
                    message="Normalized amount is zero while original amount is non-zero",
                    source_row=source_row_number,
                    section_index=section_number,
                )
            )
        if currency.upper() != "ILS":
            record_issues.append(
                DataQualityIssue(
                    code="NON_ILS_CURRENCY",
                    message="Non-ILS transaction is imported but excluded from ILS analytics",
                    source_row=source_row_number,
                    section_index=section_number,
                )
            )
        return ParsedSourceRecord(
            sheet_name=sheet_name,
            section_index=section_number,
            source_row_number=source_row_number,
            account=account,
            booking_date=booking_date,
            amount=amount,
            description=description,
            allocation_date=allocation_date,
            movement_type=movement_type,
            category=category,
            currency=currency,
            original_currency=original_currency,
            original_amount=original_amount,
            raw_payload={str(i + 1): value for i, value in enumerate(normalized_payload)},
            row_fingerprint=row_fingerprint,
            issues=record_issues,
        )

    @staticmethod
    def _preview_row(record: ParsedSourceRecord) -> dict[str, Any]:
        return {
            "section": record.section_index,
            "source_row": record.source_row_number,
            "account": record.account.display_label,
            "booking_date": record.booking_date.isoformat(),
            "amount": str(record.amount),
            "currency": record.currency,
            "issue_codes": [issue.code for issue in record.issues],
        }
