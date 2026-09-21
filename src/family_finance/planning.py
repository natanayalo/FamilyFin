"""Local-only twelve-month budget planning domain and application service.

Planning is deliberately kept separate from imported transactions.  The
service owns schedule expansion, seed parsing, projections, and comparisons;
the Streamlit layer only edits typed inputs and renders returned contracts.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select

from family_finance.classification import ClassificationService
from family_finance.config import Settings
from family_finance.metrics import MetricsService
from family_finance.models import (
    ActualPlanComparison,
    ActualPlanMonth,
    MonthlyPlan,
    PlanningFrequency,
    PlanningItem,
    PlanningItemInput,
    PlanningItemKind,
    PlanningProjection,
    PlanningRevision,
    PlanningScenarioSummary,
    PlanningSeedOrigin,
    PlanningSeedPreview,
    ScenarioComparison,
    ScenarioComparisonSeries,
)
from family_finance.persistence.db import Database, json_dumps, utc_now
from family_finance.persistence.models import (
    PlanningItemRow,
    PlanningScenarioRevisionRow,
    PlanningScenarioRow,
    PlanningSeedImportRow,
    PlanningSourceFileRow,
)

PLANNING_POLICY_VERSION = "planning-v1"
ZERO = Decimal(0)
_SPACE_RE = re.compile(r"\s+")
_MONEY_RE = re.compile(
    r"^(?:\([+\-−]?\s*(?:₪|NIS|ILS|\$|€|£)?\s*[0-9][0-9,]*(?:\.[0-9]+)?\)|[+\-−]?\s*(?:₪|NIS|ILS|\$|€|£)?\s*[0-9][0-9,]*(?:\.[0-9]+)?)$",
    re.IGNORECASE,
)


class PlanningValidationError(ValueError):
    """The scenario, item, seed, or mapping violates planning policy."""


class StaleRevisionError(PlanningValidationError):
    """A revision save was based on an older current revision."""


class DuplicateSeedError(PlanningValidationError):
    """The same content-addressed CSV was already committed."""

    def __init__(self, message: str, scenario_id: str | None = None) -> None:
        super().__init__(message)
        self.scenario_id = scenario_id


class PlanningPreviewStaleError(PlanningValidationError):
    """A seed preview no longer describes the submitted source or baseline."""


# Friendly aliases for callers that use the longer names from the product spec.
PlanningStaleRevisionError = StaleRevisionError
PreviewStaleError = PlanningPreviewStaleError


def _month(value: date | str) -> date:
    if isinstance(value, str):
        value = date.fromisoformat(f"{value}-01" if len(value) == 7 else value[:10])
    return value.replace(day=1)


def _next_month(value: date) -> date:
    return date(value.year + 1, 1, 1) if value.month == 12 else date(value.year, value.month + 1, 1)


def _previous_month(value: date) -> date:
    return date(value.year - 1, 12, 1) if value.month == 1 else date(value.year, value.month - 1, 1)


def _month_count(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month + 1


def _month_range(start: date, end: date) -> list[date]:
    start, end = _month(start), _month(end)
    result: list[date] = []
    current = start
    while current <= end:
        result.append(current)
        current = _next_month(current)
    return result


def _horizon_end(start: date) -> date:
    current = _month(start)
    for _ in range(11):
        current = _next_month(current)
    return current


def _decimal_text(value: Decimal | str | float) -> str:
    number = Decimal(str(value))
    if not number.is_finite():
        raise PlanningValidationError("Money must be finite")
    if number == 0:
        return "0"
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _normalize_text(value: Any) -> str:
    return _SPACE_RE.sub(" ", str(value or "").strip().casefold())


def _json_ready(value: Any) -> Any:
    """Convert dates and other simple domain values to JSON-safe values."""

    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _parse_number(value: Any) -> Decimal | None:
    """Parse a standalone numeric/currency cell, never narrative text."""

    text = str(value or "").strip().replace("\u00a0", " ")
    if not text or not _MONEY_RE.fullmatch(text):
        return None
    negative = text.startswith(("-", "−")) or (text.startswith("(") and text.endswith(")"))
    text = text.strip("()")
    text = text.lstrip("+-− ")
    text = re.sub(r"(?i)(₪|NIS|ILS|\$|€|£)", "", text).replace(",", "").strip()
    try:
        result = Decimal(text)
    except InvalidOperation:
        return None
    return -result if negative else result


def _iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _item_model(row: PlanningItemRow) -> PlanningItem:
    return PlanningItem(
        id=row.id,
        kind=row.kind,
        category=row.category,
        label=row.label,
        amount=Decimal(row.amount),
        frequency=row.frequency,
        start_month=row.start_month,
        end_month=row.end_month,
        occurrence_month=row.occurrence_month,
        origin=row.origin,
        source_range=row.source_range,
        source_row=row.source_row,
        policy_version=row.policy_version,
        completeness_codes=json.loads(row.completeness_codes_json or "[]"),
        contributor_transaction_ids=json.loads(row.contributor_transaction_ids_json or "[]"),
        provenance=json.loads(row.provenance_json or "{}"),
        notes=json.loads(row.notes_json or "[]"),
    )


def _summary_model(row: PlanningScenarioRow) -> PlanningScenarioSummary:
    return PlanningScenarioSummary(
        scenario_id=row.id,
        name=row.name,
        currency=row.currency,
        start_month=row.start_month,
        end_month=row.end_month,
        current_revision_number=row.current_revision_number,
        archived=bool(row.archived),
        clone_of_scenario_id=row.clone_of_scenario_id,
        created_at=_iso_datetime(row.created_at),
        updated_at=_iso_datetime(row.updated_at),
    )


class PlanningCSVParser:
    """Strict structural parser for the supplied multi-block planning CSV."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_environment()

    def _read(self, file_bytes: bytes) -> list[list[str]]:
        if len(file_bytes) > self.settings.planning_csv_max_bytes:
            raise PlanningValidationError("Planning CSV exceeds the file-size limit")
        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise PlanningValidationError("Planning CSV must be valid UTF-8") from exc
        rows: list[list[str]] = []
        reader = csv.reader(io.StringIO(text), strict=True)
        try:
            for row_number, row in enumerate(reader, 1):
                if row_number > self.settings.planning_csv_max_rows:
                    raise PlanningValidationError("Planning CSV exceeds the row limit")
                if len(row) > self.settings.planning_csv_max_columns:
                    raise PlanningValidationError("Planning CSV exceeds the column limit")
                if any(len(field) > self.settings.planning_csv_max_field_length for field in row):
                    raise PlanningValidationError("Planning CSV contains an oversized field")
                rows.append(row)
        except csv.Error as exc:
            raise PlanningValidationError("Planning CSV has malformed quoting or delimiters") from exc
        if not rows:
            raise PlanningValidationError("Planning CSV is empty")
        return rows

    @staticmethod
    def _header_row(rows: list[list[str]]) -> int:
        for index, row in enumerate(rows):
            normalized = {_normalize_text(value) for value in row}
            if "קטגוריה" in normalized and "הכנסות" in normalized:
                return index
        raise PlanningValidationError("Planning CSV has no recognizable planning header")

    @staticmethod
    def _target_block(header: list[str]) -> tuple[int, int, int]:
        candidates: list[tuple[int, int, int]] = []
        for index in range(max(0, len(header) - 2)):
            if (
                _normalize_text(header[index]) == "קטגוריה"
                and _normalize_text(header[index + 1]) == "מיני קטגוריה"
                and _normalize_text(header[index + 2]) in {"יעד", "ממוצע"}
            ):
                candidates.append((index, index + 1, index + 2))
        if not candidates:
            raise PlanningValidationError("Planning CSV has no category target block")
        return max(candidates, key=lambda block: block[0])

    def parse(self, file_bytes: bytes, *, filename: str | None = None) -> dict[str, Any]:
        rows = self._read(file_bytes)
        header_index = self._header_row(rows)
        header = rows[header_index]
        category_col, mini_col, target_col = self._target_block(header)
        notes_col = next(
            (index for index in range(target_col + 1, len(header)) if _normalize_text(header[index]) == "הערות"),
            None,
        )
        income_col = next(
            (index for index, value in enumerate(header) if _normalize_text(value) == "הכנסות"),
            None,
        )
        monthly_expense_col = next(
            (index for index, value in enumerate(header) if _normalize_text(value) == "הוצאות חודשי"),
            None,
        )
        savings_col = next(
            (index for index, value in enumerate(header) if _normalize_text(value) == "חסכון"),
            None,
        )
        if income_col is None:
            raise PlanningValidationError("Planning CSV has no recurring income block")

        expenses: list[dict[str, Any]] = []
        notes: list[dict[str, Any]] = []
        expense_control_total: Decimal | None = None
        for row_number, row in enumerate(rows[header_index + 1 :], header_index + 2):
            cells = row + [""] * max(0, len(header) - len(row))
            label = str(cells[category_col] or "").strip()
            sublabel = str(cells[mini_col] or "").strip()
            target = _parse_number(cells[target_col])
            if _normalize_text(label).startswith("סהכ"):
                expense_control_total = target
                continue
            if not label and not sublabel:
                continue
            category = sublabel or label
            if target is not None:
                expenses.append(
                    {
                        "category": category,
                        "label": category,
                        "amount": target,
                        "source_row": row_number,
                        "source_range": f"R{row_number}C{category_col + 1}:C{target_col + 1}",
                    }
                )
                if notes_col is not None and notes_col < len(cells) and str(cells[notes_col]).strip():
                    notes.append(
                        {
                            "category": category,
                            "note": str(cells[notes_col]).strip(),
                            "source_row": row_number,
                            "source_range": f"R{row_number}C{notes_col + 1}",
                        }
                    )
            # A narrative amount (for example rent in the notes column) is
            # intentionally not inferred as a target.

        incomes: list[dict[str, Any]] = []
        income_control_total: Decimal | None = None
        income_amount_col = income_col + 1
        for row_number, row in enumerate(rows[header_index + 1 :], header_index + 2):
            cells = row + [""] * max(0, len(header) - len(row))
            label = str(cells[income_col] or "").strip() if income_col < len(cells) else ""
            amount = _parse_number(cells[income_amount_col]) if income_amount_col < len(cells) else None
            if not label or amount is None:
                continue
            if _normalize_text(label).startswith("סהכ"):
                income_control_total = amount
            elif _normalize_text(label).startswith(("משכורת", "salary")):
                incomes.append(
                    {
                        "label": label,
                        "category": label,
                        "amount": amount,
                        "source_row": row_number,
                        "source_range": f"R{row_number}C{income_col + 1}:C{income_amount_col + 1}",
                    }
                )

        summary: dict[str, Any] | None = None
        if monthly_expense_col is not None and savings_col is not None:
            for row_number, row in enumerate(rows[header_index + 1 :], header_index + 2):
                cells = row + [""] * max(0, len(header) - len(row))
                label = str(cells[income_col] or "").strip() if income_col < len(cells) else ""
                if _normalize_text(label).startswith("סהכ"):
                    monthly_expenses = _parse_number(cells[monthly_expense_col])
                    savings = _parse_number(cells[savings_col])
                    income_total = _parse_number(cells[income_amount_col])
                    if monthly_expenses is not None and savings is not None:
                        summary = {
                            "income": income_total,
                            "expenses": monthly_expenses,
                            "savings": savings,
                            "source_row": row_number,
                        }
                        break

        observed_headers = [str(value).strip() for value in header[target_col + 1 : (notes_col or target_col + 1)]]
        ignored_sections = ["observed-month columns", "differences", "historical savings balances", "unexpected-income history"]
        return {
            "rows": rows,
            "header_index": header_index,
            "target_block": (category_col, mini_col, target_col),
            "expenses": expenses,
            "expense_notes": notes,
            "expense_control_total": expense_control_total,
            "monthly_expense_control_total": summary.get("expenses") if summary else None,
            "incomes": incomes,
            "income_control_total": income_control_total,
            "savings_summary": summary,
            "observed_headers": observed_headers,
            "ignored_sections": ignored_sections,
            "sha256": hashlib.sha256(file_bytes).hexdigest(),
            "filename": filename,
        }


class PlanningService:
    """Typed service for immutable scenario revisions and projections."""

    def __init__(
        self,
        database: Database,
        *,
        settings: Settings | None = None,
        metrics: MetricsService | None = None,
        classifier: ClassificationService | None = None,
    ) -> None:
        self.database = database
        self.settings = settings or Settings.from_environment()
        self.metrics = metrics or MetricsService(database, classifier=classifier)
        self.classifier = classifier or self.metrics.classifier
        self.csv_parser = PlanningCSVParser(self.settings)

    # -- scenario lifecycle -------------------------------------------------

    def list_scenarios(self, *, include_archived: bool = False) -> list[PlanningScenarioSummary]:
        statement = select(PlanningScenarioRow).order_by(desc(PlanningScenarioRow.updated_at), PlanningScenarioRow.name)
        if not include_archived:
            statement = statement.where(PlanningScenarioRow.archived.is_(False))
        with self.database.session() as session:
            rows = session.execute(statement).scalars().all()
        return [_summary_model(row) for row in rows]

    def get_scenario(self, scenario_id: str) -> PlanningScenarioSummary:
        with self.database.session() as session:
            row = session.get(PlanningScenarioRow, str(scenario_id))
        if row is None:
            raise PlanningValidationError(f"Scenario {scenario_id} not found")
        return _summary_model(row)

    scenario = get_scenario

    def get_revision(self, scenario_id: str, revision_number: int | None = None) -> PlanningRevision:
        with self.database.session() as session:
            scenario = session.get(PlanningScenarioRow, str(scenario_id))
            if scenario is None:
                raise PlanningValidationError(f"Scenario {scenario_id} not found")
            number = revision_number or scenario.current_revision_number
            revision = session.execute(
                select(PlanningScenarioRevisionRow).where(
                    PlanningScenarioRevisionRow.scenario_id == str(scenario_id),
                    PlanningScenarioRevisionRow.revision_number == number,
                )
            ).scalar_one_or_none()
            if revision is None:
                raise PlanningValidationError(f"Revision {number} not found for scenario {scenario_id}")
            items = session.execute(
                select(PlanningItemRow).where(PlanningItemRow.revision_id == revision.id).order_by(PlanningItemRow.id)
            ).scalars().all()
        return PlanningRevision(
            revision_id=revision.id,
            scenario_id=revision.scenario_id,
            revision_number=revision.revision_number,
            items=[_item_model(item) for item in items],
            notes=revision.notes,
            created_at=_iso_datetime(revision.created_at),
            provisional=bool(revision.provisional),
            issue_codes=json.loads(revision.issue_codes_json or "[]"),
            completeness_snapshot=json.loads(revision.completeness_snapshot_json or "[]"),
            expense_notes=json.loads(revision.expense_notes_json or "[]"),
        )

    revision = get_revision

    def list_revisions(self, scenario_id: str) -> list[PlanningRevision]:
        with self.database.session() as session:
            revisions = session.execute(
                select(PlanningScenarioRevisionRow)
                .where(PlanningScenarioRevisionRow.scenario_id == scenario_id)
                .order_by(PlanningScenarioRevisionRow.revision_number)
            ).scalars().all()
            items_by_revision: dict[str, list[PlanningItem]] = defaultdict(list)
            items = session.execute(
                select(PlanningItemRow)
                .join(PlanningScenarioRevisionRow, PlanningItemRow.revision_id == PlanningScenarioRevisionRow.id)
                .where(PlanningScenarioRevisionRow.scenario_id == scenario_id)
                .order_by(PlanningItemRow.id)
            ).scalars().all()
            for item in items:
                items_by_revision[item.revision_id].append(_item_model(item))
        return [
            PlanningRevision(
                revision_id=row.id,
                scenario_id=row.scenario_id,
                revision_number=row.revision_number,
                items=items_by_revision[row.id],
                notes=row.notes,
                created_at=_iso_datetime(row.created_at),
                provisional=bool(row.provisional),
                issue_codes=json.loads(row.issue_codes_json or "[]"),
                completeness_snapshot=json.loads(row.completeness_snapshot_json or "[]"),
                expense_notes=json.loads(row.expense_notes_json or "[]"),
            )
            for row in revisions
        ]

    def create_manual_scenario(
        self,
        name: str,
        start_month: date | str,
        items: Sequence[PlanningItemInput | dict[str, Any]] | None = None,
        *,
        currency: str = "ILS",
        notes: str = "",
    ) -> PlanningScenarioSummary:
        return self._create_scenario(
            name=name,
            start_month=_month(start_month),
            currency=currency,
            items=items or [],
            notes=notes,
            origin=PlanningSeedOrigin.MANUAL.value,
        )

    create_scenario = create_manual_scenario
    create_manual = create_manual_scenario

    def _create_scenario(
        self,
        *,
        name: str,
        start_month: date,
        currency: str,
        items: Sequence[PlanningItemInput | PlanningItem | dict[str, Any]],
        notes: str = "",
        origin: str = PlanningSeedOrigin.MANUAL.value,
        clone_of_scenario_id: str | None = None,
        provenance_defaults: dict[str, Any] | None = None,
        source_file: dict[str, Any] | None = None,
        provisional: bool = False,
        issue_codes: Sequence[str] | None = None,
        completeness_snapshot: Sequence[dict[str, Any]] | None = None,
        expense_notes: Sequence[dict[str, Any]] | None = None,
    ) -> PlanningScenarioSummary:
        name = str(name).strip()
        if not name or len(name) > 200:
            raise PlanningValidationError("Scenario name must be non-empty and at most 200 characters")
        currency = str(currency).strip().upper()
        if not currency or len(currency) > 12:
            raise PlanningValidationError("Scenario currency must be a non-empty short code")
        start = _month(start_month)
        end = _horizon_end(start)
        parsed = [self._coerce_item(item, default_origin=origin, provenance_defaults=provenance_defaults) for item in items]
        for item in parsed:
            item.id = str(uuid.uuid4())
        self._validate_items(parsed, start, end, currency)
        now = utc_now()
        scenario_id = str(uuid.uuid4())
        revision_id = str(uuid.uuid4())
        with self.database.write_session() as session:
            session.add(
                PlanningScenarioRow(
                    id=scenario_id,
                    name=name,
                    currency=currency,
                    start_month=start.isoformat(),
                    end_month=end.isoformat(),
                    current_revision_number=1,
                    clone_of_scenario_id=clone_of_scenario_id,
                    archived=False,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                PlanningScenarioRevisionRow(
                    id=revision_id,
                    scenario_id=scenario_id,
                    revision_number=1,
                    notes=notes or "",
                    provisional=bool(provisional),
                    issue_codes_json=json_dumps(list(issue_codes or [])),
                    completeness_snapshot_json=json_dumps(_json_ready(list(completeness_snapshot or []))),
                    expense_notes_json=json_dumps(_json_ready(list(expense_notes or []))),
                    created_at=now,
                )
            )
            session.flush()
            self._insert_items(session, revision_id, parsed)
            if source_file is not None:
                source = PlanningSourceFileRow(
                    sha256=source_file["sha256"],
                    original_filename=source_file.get("original_filename"),
                    archived_path=source_file["archived_path"],
                    compressed_bytes=int(source_file["compressed_bytes"]),
                    uncompressed_bytes=int(source_file["uncompressed_bytes"]),
                    parser_version=source_file["parser_version"],
                    created_at=now,
                )
                session.add(source)
                session.flush()
                session.add(
                    PlanningSeedImportRow(
                        id=str(uuid.uuid4()),
                        source_file_id=source.id,
                        scenario_id=scenario_id,
                        revision_id=revision_id,
                        origin=origin,
                        parser_version=source_file["parser_version"],
                        imported_at=now,
                    )
                )
        return self.get_scenario(scenario_id)

    def save_revision(
        self,
        scenario_id: str,
        expected_revision_number: int,
        items: Sequence[PlanningItemInput | PlanningItem | dict[str, Any]],
        *,
        notes: str = "",
        provisional: bool | None = None,
        issue_codes: Sequence[str] | None = None,
        completeness_snapshot: Sequence[dict[str, Any]] | None = None,
        expense_notes: Sequence[dict[str, Any]] | None = None,
    ) -> PlanningRevision:
        parsed = [self._coerce_item(item) for item in items]
        # Item rows belong to one immutable revision.  A new revision always
        # receives fresh row identities, including a restore of an older one.
        for item in parsed:
            item.id = str(uuid.uuid4())
        now = utc_now()
        with self.database.write_session() as session:
            scenario = session.get(PlanningScenarioRow, str(scenario_id))
            if scenario is None:
                raise PlanningValidationError(f"Scenario {scenario_id} not found")
            if scenario.current_revision_number != expected_revision_number:
                raise StaleRevisionError(
                    f"Scenario {scenario_id} is at revision {scenario.current_revision_number}; expected {expected_revision_number}"
                )
            self._validate_items(parsed, _month(scenario.start_month), _month(scenario.end_month), scenario.currency)
            current_revision = session.execute(
                select(PlanningScenarioRevisionRow).where(
                    PlanningScenarioRevisionRow.scenario_id == scenario.id,
                    PlanningScenarioRevisionRow.revision_number == scenario.current_revision_number,
                )
            ).scalar_one()
            revision_number = scenario.current_revision_number + 1
            revision_id = str(uuid.uuid4())
            session.add(
                PlanningScenarioRevisionRow(
                    id=revision_id,
                    scenario_id=scenario.id,
                    revision_number=revision_number,
                    notes=notes or "",
                    provisional=bool(current_revision.provisional if provisional is None else provisional),
                    issue_codes_json=json_dumps(
                        json.loads(current_revision.issue_codes_json or "[]")
                        if issue_codes is None
                        else list(issue_codes)
                    ),
                    completeness_snapshot_json=json_dumps(
                        json.loads(current_revision.completeness_snapshot_json or "[]")
                        if completeness_snapshot is None
                        else _json_ready(list(completeness_snapshot))
                    ),
                    expense_notes_json=json_dumps(
                        json.loads(current_revision.expense_notes_json or "[]")
                        if expense_notes is None
                        else _json_ready(list(expense_notes))
                    ),
                    created_at=now,
                )
            )
            session.flush()
            self._insert_items(session, revision_id, parsed)
            scenario.current_revision_number = revision_number
            scenario.updated_at = now
        return self.get_revision(scenario_id, revision_number)

    def restore_revision(
        self,
        scenario_id: str,
        revision_number: int,
        *,
        expected_revision_number: int | None = None,
        notes: str = "Restored older revision",
    ) -> PlanningRevision:
        old = self.get_revision(scenario_id, revision_number)
        current = self.get_scenario(scenario_id)
        expected = current.current_revision_number if expected_revision_number is None else expected_revision_number
        return self.save_revision(
            scenario_id,
            expected,
            old.items,
            notes=notes,
            provisional=old.provisional,
            issue_codes=old.issue_codes,
            completeness_snapshot=old.completeness_snapshot,
            expense_notes=old.expense_notes,
        )

    def clone_scenario(self, scenario_id: str, *, name: str | None = None) -> PlanningScenarioSummary:
        source = self.get_scenario(scenario_id)
        revision = self.get_revision(scenario_id)
        return self._create_scenario(
            name=name or f"{source.name} (copy)",
            start_month=source.start_month,
            currency=source.currency,
            items=revision.items,
            notes=revision.notes,
            origin="manual" if all(item.origin == "manual" for item in revision.items) else "clone",
            clone_of_scenario_id=source.scenario_id,
            provisional=revision.provisional,
            issue_codes=revision.issue_codes,
            completeness_snapshot=revision.completeness_snapshot,
            expense_notes=revision.expense_notes,
        )

    duplicate_scenario = clone_scenario
    clone = clone_scenario

    def archive_scenario(self, scenario_id: str, archived: bool = True) -> PlanningScenarioSummary:
        with self.database.write_session() as session:
            row = session.get(PlanningScenarioRow, str(scenario_id))
            if row is None:
                raise PlanningValidationError(f"Scenario {scenario_id} not found")
            row.archived = bool(archived)
            row.updated_at = utc_now()
        return self.get_scenario(scenario_id)

    def unarchive_scenario(self, scenario_id: str) -> PlanningScenarioSummary:
        return self.archive_scenario(scenario_id, False)

    set_archived = archive_scenario
    archive = archive_scenario

    # -- projections and comparisons ---------------------------------------

    def project_draft(
        self,
        scenario_id: str,
        items: Sequence[PlanningItemInput | PlanningItem | dict[str, Any]] | None = None,
        *,
        revision_number: int | None = None,
    ) -> PlanningProjection:
        scenario = self.get_scenario(scenario_id)
        projection_quality = (False, [])
        if items is None:
            revision = self.get_revision(scenario_id, revision_number)
            parsed = revision.items
            revision_number = revision.revision_number
            projection_quality = (revision.provisional, revision.issue_codes)
        else:
            # Draft edits are evaluated against an existing revision.  Carry
            # that revision's seed-quality state through the unsaved draft so
            # the editor never presents a cleaner projection than a save would.
            revision_number = revision_number or scenario.current_revision_number
            revision = self.get_revision(scenario_id, revision_number)
            parsed = [self._coerce_item(item) for item in items]
            self._validate_items(parsed, scenario.start_month, scenario.end_month, scenario.currency)
            projection_quality = (revision.provisional, revision.issue_codes)
        return self._project_items(
            scenario,
            parsed,
            revision_number,
            provisional=projection_quality[0],
            issue_codes=projection_quality[1],
        )

    project = project_draft
    calculate_projection = project_draft

    def _project_items(
        self,
        scenario: PlanningScenarioSummary,
        items: Sequence[PlanningItem],
        revision_number: int,
        *,
        provisional: bool = False,
        issue_codes: Sequence[str] | None = None,
    ) -> PlanningProjection:
        months: list[MonthlyPlan] = []
        for month in _month_range(scenario.start_month, scenario.end_month):
            income = ZERO
            expenses = ZERO
            contributions = ZERO
            withdrawals = ZERO
            by_category: dict[str, Decimal] = defaultdict(lambda: ZERO)
            income_by_category: dict[str, Decimal] = defaultdict(lambda: ZERO)
            unmapped_categories: list[str] = []
            contributors: dict[str, list[str]] = defaultdict(list)
            for item in items:
                if not self._occurs(item, month):
                    continue
                amount = item.amount
                if item.kind == PlanningItemKind.INCOME:
                    income += amount
                    income_by_category[item.category or item.label] += amount
                    contributors["income"].append(item.id)
                elif item.kind == PlanningItemKind.EXPENSE:
                    expenses += amount
                    category = item.category or item.label
                    by_category[category] += amount
                    if item.category is None:
                        unmapped_categories.append(category)
                    contributors["expenses"].append(item.id)
                    contributors[f"expense:{category}"].append(item.id)
                elif item.kind == PlanningItemKind.SAVINGS_CONTRIBUTION:
                    contributions += amount
                    contributors["savings_contributions"].append(item.id)
                elif item.kind == PlanningItemKind.SAVINGS_WITHDRAWAL:
                    withdrawals += amount
                    contributors["savings_withdrawals"].append(item.id)
            surplus = income - expenses
            net_savings = contributions - withdrawals
            months.append(
                MonthlyPlan(
                    month=month,
                    currency=scenario.currency,
                    income=income,
                    expenses=expenses,
                    savings_contributions=contributions,
                    savings_withdrawals=withdrawals,
                    operating_surplus=surplus,
                    net_planned_savings=net_savings,
                    cash_remaining_after_savings=surplus - contributions + withdrawals,
                    expenses_by_category=dict(sorted(by_category.items())),
                    income_by_category=dict(sorted(income_by_category.items())),
                    contributor_item_ids=dict(sorted(contributors.items())),
                    unmapped_expense_categories=sorted(set(unmapped_categories)),
                )
            )
        return PlanningProjection(
            scenario_id=scenario.scenario_id,
            revision_number=revision_number,
            currency=scenario.currency,
            months=months,
            provisional=provisional,
            issue_codes=list(issue_codes or []),
        )

    def compare_scenarios(self, scenario_ids: Sequence[str]) -> ScenarioComparison:
        ids = list(dict.fromkeys(str(value) for value in scenario_ids))
        if not 2 <= len(ids) <= 4:
            raise PlanningValidationError("Compare between two and four scenarios")
        scenarios = [self.get_scenario(value) for value in ids]
        currencies = {scenario.currency for scenario in scenarios}
        if len(currencies) != 1:
            raise PlanningValidationError("Scenario comparison requires one currency")
        start = min(scenario.start_month for scenario in scenarios)
        end = max(scenario.end_month for scenario in scenarios)
        union = _month_range(start, end)
        series: list[ScenarioComparisonSeries] = []
        for scenario in scenarios:
            projection = self.project_draft(scenario.scenario_id)
            by_month = {item.month: item for item in projection.months}
            series.append(
                ScenarioComparisonSeries(
                    scenario_id=scenario.scenario_id,
                    name=scenario.name,
                    months=[by_month.get(month) for month in union],
                )
            )
        return ScenarioComparison(currency=next(iter(currencies)), months=union, scenarios=series)

    scenario_comparison = compare_scenarios

    def compare_actual(
        self,
        scenario_id: str,
        *,
        revision_number: int | None = None,
    ) -> ActualPlanComparison:
        scenario = self.get_scenario(scenario_id)
        projection = self.project_draft(scenario_id, revision_number=revision_number)
        result: list[ActualPlanMonth] = []
        for planned in projection.months:
            actual = self.metrics.calculate_monthly_metrics(planned.month, scenario.currency)
            complete = actual.completeness.complete
            issue_codes = list(actual.completeness.issues)
            actual_categories = dict(actual.spending_by_category)
            mapped_planned_categories = set(planned.expenses_by_category) - set(planned.unmapped_expense_categories)
            unmapped_categories = set(planned.unmapped_expense_categories)
            union_categories = sorted((mapped_planned_categories | set(actual_categories)) - unmapped_categories)
            observed_rows = self.metrics.repository.accepted_transactions(
                currency=scenario.currency,
                start=planned.month,
                end=_next_month(planned.month),
            )
            actual_available = complete or bool(observed_rows)
            actual_income = actual.gross_income if actual_available else None
            actual_expenses = actual.gross_consumption if actual_available else None
            actual_surplus = actual.operating_surplus_or_deficit if actual_available else None
            actual_net_savings = actual.net_observed_savings_transfers if actual_available else None
            transaction_ids: dict[str, list[int]] = {}
            for category in union_categories:
                breakdown = actual.breakdowns.get(f"spending_by_category:{category}")
                if breakdown:
                    transaction_ids[category] = list(breakdown.contributor_transaction_ids)
            result.append(
                ActualPlanMonth(
                    month=planned.month,
                    complete=complete,
                    issue_codes=issue_codes,
                    planned=planned,
                    actual_income=actual_income,
                    actual_expenses=actual_expenses,
                    actual_surplus=actual_surplus,
                    actual_net_savings=actual_net_savings,
                    expense_variances=(
                        {category: actual_categories.get(category, ZERO) - planned.expenses_by_category.get(category, ZERO) for category in union_categories}
                        if complete
                        else None
                    ),
                    category_variance_unavailable=list(planned.unmapped_expense_categories),
                    income_variance=actual.gross_income - planned.income if complete else None,
                    surplus_variance=actual.operating_surplus_or_deficit - planned.operating_surplus if complete else None,
                    savings_variance=actual.net_observed_savings_transfers - planned.net_planned_savings if complete else None,
                    transaction_ids_by_category=transaction_ids,
                )
            )
        return ActualPlanComparison(
            scenario_id=scenario_id,
            revision_number=projection.revision_number,
            currency=scenario.currency,
            months=result,
        )

    actual_comparison = compare_actual
    compare_plan_to_actual = compare_actual
    compare_actuals = compare_actual

    # -- seed previews and commits -----------------------------------------

    def preview_history_seed(
        self,
        *,
        name: str = "Historical baseline",
        currency: str = "ILS",
        start_month: date | str | None = None,
        history_start: date | str | None = None,
        history_end: date | str | None = None,
        history_months: int = 6,
    ) -> PlanningSeedPreview:
        if history_months < 1 or history_months > 120:
            raise PlanningValidationError("history_months must be between 1 and 120")
        currency = str(currency).strip().upper()
        start = _month(start_month) if start_month is not None else self._suggest_start(currency)
        if history_start is None and history_end is None:
            # The range immediately preceding the proposed scenario, including
            # the six calendar months before its start.
            selected_end = _previous_month(start)
            selected_start = selected_end
            for _ in range(max(0, history_months - 1)):
                selected_start = _previous_month(selected_start)
        else:
            selected_start = _month(history_start or history_end or start)
            selected_end = _month(history_end or history_start or start)
        if selected_start > selected_end:
            raise PlanningValidationError("History start cannot be after history end")
        months = _month_range(selected_start, selected_end)
        if not months:
            raise PlanningValidationError("History range is empty")
        items, snapshot = self._historical_items(months, start, currency)
        snapshot_contract = _json_ready(snapshot)
        provisional = any(not item["complete"] for item in snapshot)
        issue_codes = sorted({code for item in snapshot for code in item["issue_codes"]})
        payload = {
            "origin": PlanningSeedOrigin.HISTORICAL.value,
            "name": name,
            "currency": currency,
            "start_month": start.isoformat(),
            "items": [item.model_dump(mode="json") for item in items],
            "history_start": selected_start.isoformat(),
            "history_end": selected_end.isoformat(),
            "baseline_batch_id": self.database.latest_committed_batch_id(),
            "provisional": provisional,
            "issue_codes": issue_codes,
            "completeness_snapshot": snapshot_contract,
        }
        return PlanningSeedPreview(
            preview_token=self._token(payload),
            origin=PlanningSeedOrigin.HISTORICAL,
            scenario_name=name,
            currency=currency,
            start_month=start,
            end_month=_horizon_end(start),
            items=items,
            control_checks={
                "history_range": {"start": selected_start, "end": selected_end, "months": len(months)},
                "averages_include_zero_months": True,
            },
            warnings=["Historical seed is provisional because one or more selected months are incomplete"] if provisional else [],
            issue_codes=issue_codes,
            provisional=provisional,
            completeness_snapshot=snapshot_contract,
        )

    preview_historical_seed = preview_history_seed

    def commit_history_seed(self, preview_token: str) -> PlanningScenarioSummary:
        payload = self._decode_token(preview_token)
        if payload.get("origin") != PlanningSeedOrigin.HISTORICAL.value:
            raise PlanningPreviewStaleError("Preview origin does not match historical seed commit")
        if payload.get("baseline_batch_id") != self.database.latest_committed_batch_id():
            raise PlanningPreviewStaleError("Imported history changed after preview; preview again")
        items = [PlanningItem.model_validate(item) for item in payload["items"]]
        return self._create_scenario(
            name=payload["name"],
            start_month=payload["start_month"],
            currency=payload["currency"],
            items=items,
            origin=PlanningSeedOrigin.HISTORICAL.value,
            provisional=bool(payload.get("provisional", False)),
            issue_codes=payload.get("issue_codes", []),
            completeness_snapshot=payload.get("completeness_snapshot", []),
        )

    commit_historical_seed = commit_history_seed
    preview_history = preview_history_seed
    preview_historical = preview_history_seed
    commit_history = commit_history_seed
    commit_historical = commit_history_seed

    def preview_csv_seed(
        self,
        file_bytes: bytes,
        filename: str | None = None,
        *,
        name: str | None = None,
        currency: str = "ILS",
        start_month: date | str | None = None,
    ) -> PlanningSeedPreview:
        parsed = self.csv_parser.parse(file_bytes, filename=filename)
        start = _month(start_month) if start_month is not None else self._suggest_start(currency)
        end = _horizon_end(start)
        items: list[PlanningItem] = []
        exact_categories = self._analysis_categories(currency)
        mappings: list[dict[str, Any]] = []
        notes_by_row: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for note in parsed["expense_notes"]:
            notes_by_row[int(note["source_row"])].append(note)
        for entry in parsed["expenses"]:
            suggestions = [category for category in exact_categories if _normalize_text(category) == _normalize_text(entry["category"])]
            mappings.append({
                "csv_category": entry["category"],
                "suggested_analysis_categories": suggestions,
                "exact_match": bool(suggestions),
                "requires_confirmation": True,
                "status": "suggestion" if suggestions else "unmapped",
            })
            items.append(
                PlanningItem(
                    kind=PlanningItemKind.EXPENSE,
                    category=None,
                    label=entry["label"],
                    amount=entry["amount"],
                    frequency=PlanningFrequency.MONTHLY,
                    start_month=start,
                    end_month=end,
                    origin=PlanningSeedOrigin.CSV.value,
                    source_range=entry["source_range"],
                    source_row=entry["source_row"],
                    provenance={"csv_category": entry["category"]},
                    notes=notes_by_row.get(int(entry["source_row"]), []),
                )
            )
        for entry in parsed["incomes"]:
            items.append(
                PlanningItem(
                    kind=PlanningItemKind.INCOME,
                    category=None,
                    label=entry["label"],
                    amount=entry["amount"],
                    frequency=PlanningFrequency.MONTHLY,
                    start_month=start,
                    end_month=end,
                    origin=PlanningSeedOrigin.CSV.value,
                    source_range=entry["source_range"],
                    source_row=entry["source_row"],
                    provenance={"csv_section": "recurring_income"},
                )
            )
        summary = parsed["savings_summary"]
        if summary and summary.get("savings") is not None:
            items.append(
                PlanningItem(
                    kind=PlanningItemKind.SAVINGS_CONTRIBUTION,
                    label="Monthly savings summary",
                    amount=summary["savings"],
                    frequency=PlanningFrequency.MONTHLY,
                    start_month=start,
                    end_month=end,
                    origin=PlanningSeedOrigin.CSV.value,
                    source_row=summary["source_row"],
                    provenance={"csv_section": "monthly_savings_summary"},
                )
            )
        control_checks = self._csv_controls(parsed)
        warnings: list[str] = []
        issue_codes: list[str] = []
        if not control_checks["expenses"]["passed"]:
            warnings.append("Expense targets do not reconcile to the CSV control total; no amount was inferred from notes")
            issue_codes.append("CSV_EXPENSE_CONTROL_GAP")
        if any(not mapping["exact_match"] for mapping in mappings):
            warnings.append("Unmapped CSV categories remain visible; category variance is unavailable until explicitly mapped")
            issue_codes.append("CSV_CATEGORY_UNMAPPED")
        existing = self._planning_source_by_hash(parsed["sha256"])
        duplicate_scenario_id = self._scenario_for_source(existing.id) if existing else None
        payload = {
            "origin": PlanningSeedOrigin.CSV.value,
            "name": name or (Path(filename).stem if filename else "CSV budget seed"),
            "currency": str(currency).strip().upper(),
            "start_month": start.isoformat(),
            "items": [item.model_dump(mode="json") for item in items],
            "sha256": parsed["sha256"],
            "filename": filename,
            "parser_version": self.settings.planning_parser_version,
            "parsed": parsed,
            "provisional": not all(check["passed"] for check in control_checks.values()),
            "issue_codes": issue_codes,
            "warnings": warnings,
        }
        return PlanningSeedPreview(
            preview_token=self._token(payload),
            origin=PlanningSeedOrigin.CSV,
            scenario_name=payload["name"],
            currency=payload["currency"],
            start_month=start,
            end_month=end,
            items=items,
            control_checks=control_checks,
            ignored_sections=parsed["ignored_sections"],
            mappings=mappings,
            warnings=warnings,
            issue_codes=issue_codes,
            provisional=not all(check["passed"] for check in control_checks.values()),
            file_sha256=parsed["sha256"],
            filename=filename,
            duplicate_scenario_id=duplicate_scenario_id,
            expense_notes=parsed["expense_notes"],
            expense_target_count=len(parsed["expenses"]),
            recurring_income_count=len(parsed["incomes"]),
            savings_summary_count=1 if summary and summary.get("savings") is not None else 0,
        )

    preview_csv = preview_csv_seed

    def commit_csv_seed(
        self,
        file_bytes: bytes,
        preview_token: str,
        *,
        mappings: dict[str, str] | None = None,
    ) -> PlanningScenarioSummary:
        payload = self._decode_token(preview_token)
        parsed = self.csv_parser.parse(file_bytes, filename=payload.get("filename"))
        if (
            payload.get("origin") != PlanningSeedOrigin.CSV.value
            or payload.get("sha256") != parsed["sha256"]
            or payload.get("parser_version") != self.settings.planning_parser_version
        ):
            raise PlanningPreviewStaleError("CSV contents changed after preview")
        existing = self._planning_source_by_hash(parsed["sha256"])
        if existing:
            scenario_id = self._scenario_for_source(existing.id)
            raise DuplicateSeedError(
                "This CSV was already seeded; open or duplicate the existing scenario explicitly",
                scenario_id=scenario_id,
            )
        items = [PlanningItem.model_validate(item) for item in payload["items"]]
        if mappings:
            valid_categories = self._analysis_categories(payload["currency"])
            normalized_valid = {_normalize_text(value): value for value in valid_categories}
            for item in items:
                source_label = str(item.provenance.get("csv_category", item.label))
                match = (
                    mappings.get(source_label)
                    or mappings.get(_normalize_text(source_label))
                    or mappings.get(item.label)
                    or mappings.get(_normalize_text(item.label))
                )
                if match is not None:
                    if _normalize_text(match) not in normalized_valid:
                        raise PlanningValidationError(f"Unknown explicit analysis category mapping: {match}")
                    item.category = normalized_valid[_normalize_text(match)]
                    item.provenance["explicit_analysis_category_mapping"] = item.category
        unmapped_expenses = [
            item
            for item in items
            if item.kind == PlanningItemKind.EXPENSE and item.category is None
        ]
        final_issue_codes = sorted(
            {
                code
                for code in payload.get("issue_codes", [])
                if code != "CSV_CATEGORY_UNMAPPED"
            }
        )
        if unmapped_expenses:
            final_issue_codes.append("CSV_CATEGORY_UNMAPPED")
        filename = payload.get("filename")
        archive_path = self._archive_planning_source(parsed["sha256"], file_bytes, filename)
        summary = self._create_scenario(
            name=payload["name"],
            start_month=payload["start_month"],
            currency=payload["currency"],
            items=items,
            origin=PlanningSeedOrigin.CSV.value,
            provenance_defaults={"file_sha256": parsed["sha256"], "filename": filename},
            source_file={
                "sha256": parsed["sha256"],
                "original_filename": filename,
                "archived_path": str(archive_path),
                "compressed_bytes": len(file_bytes),
                "uncompressed_bytes": len(file_bytes),
                "parser_version": self.settings.planning_parser_version,
            },
            provisional=bool(payload.get("provisional", False) or unmapped_expenses),
            issue_codes=final_issue_codes,
            expense_notes=parsed.get("expense_notes", []),
        )
        return summary

    commit_csv = commit_csv_seed

    def open_seeded_scenario(self, file_sha256: str) -> PlanningScenarioSummary:
        source = self._planning_source_by_hash(file_sha256)
        if source is None:
            raise PlanningValidationError("No planning seed exists for this file hash")
        scenario_id = self._scenario_for_source(source.id)
        if scenario_id is None:
            raise PlanningValidationError("Planning source has no linked scenario")
        return self.get_scenario(scenario_id)

    # -- private validation/persistence helpers ----------------------------

    @staticmethod
    def _coerce_item(
        item: PlanningItemInput | PlanningItem | dict[str, Any],
        *,
        default_origin: str | None = None,
        provenance_defaults: dict[str, Any] | None = None,
    ) -> PlanningItem:
        if isinstance(item, PlanningItem):
            result = item.model_copy(deep=True)
        elif isinstance(item, PlanningItemInput):
            result = PlanningItem.model_validate(item.model_dump())
        else:
            result = PlanningItem.model_validate(item)
        if default_origin:
            result.origin = default_origin
        if provenance_defaults:
            result.provenance = {**provenance_defaults, **result.provenance}
        if not result.id:
            result.id = str(uuid.uuid4())
        return result

    @staticmethod
    def _validate_items(items: Sequence[PlanningItem], start: date, end: date, currency: str) -> None:
        if _month_count(_month(start), _month(end)) != 12:
            raise PlanningValidationError("Every planning scenario must cover exactly 12 months")
        for item in items:
            if item.amount < ZERO:
                raise PlanningValidationError("Planning item amounts must be positive magnitudes")
            if item.frequency == PlanningFrequency.MONTHLY:
                if item.start_month is None or item.end_month is None or item.start_month < start or item.end_month > end:
                    raise PlanningValidationError("Monthly planning item must be inside the scenario horizon")
            elif item.occurrence_month is None or not start <= item.occurrence_month <= end:
                raise PlanningValidationError("One-time planning item must be inside the scenario horizon")

    @staticmethod
    def _occurs(item: PlanningItem, month: date) -> bool:
        if item.frequency == PlanningFrequency.MONTHLY:
            return bool(item.start_month and item.end_month and item.start_month <= month <= item.end_month)
        return item.occurrence_month == month

    @staticmethod
    def _insert_items(session, revision_id: str, items: Sequence[PlanningItem]) -> None:
        for item in items:
            session.add(
                PlanningItemRow(
                    id=item.id or str(uuid.uuid4()),
                    revision_id=revision_id,
                    kind=item.kind.value,
                    category=item.category,
                    label=item.label,
                    amount=_decimal_text(item.amount),
                    frequency=item.frequency.value,
                    start_month=item.start_month.isoformat() if item.start_month else None,
                    end_month=item.end_month.isoformat() if item.end_month else None,
                    occurrence_month=item.occurrence_month.isoformat() if item.occurrence_month else None,
                    origin=item.origin,
                    source_range=item.source_range,
                    source_row=item.source_row,
                    policy_version=item.policy_version,
                    completeness_codes_json=json_dumps(item.completeness_codes),
                    contributor_transaction_ids_json=json_dumps(item.contributor_transaction_ids),
                    provenance_json=json_dumps(item.provenance),
                    notes_json=json_dumps(_json_ready(item.notes)),
                )
            )

    def suggested_start_month(self, currency: str = "ILS") -> date:
        """Return the month after the latest accepted transaction."""

        return self._suggest_start(currency)

    def analysis_categories(self, currency: str = "ILS") -> list[str]:
        """Return current classifier analysis categories for mapping controls."""

        return self._analysis_categories(currency)

    def _suggest_start(self, currency: str) -> date:
        rows = self.metrics.repository.accepted_transactions(currency=str(currency).upper())
        if not rows:
            return datetime.now(UTC).date().replace(day=1)
        latest = max(date.fromisoformat(str(row["booking_date"])) for row in rows)
        return _next_month(latest.replace(day=1))

    def _analysis_categories(self, currency: str) -> list[str]:
        categories = {
            result.analysis_category
            for result in self.classifier.classify_many(currency=str(currency).upper())
            if result.analysis_category
        }
        return sorted(categories)

    def _historical_items(
        self,
        months: Sequence[date],
        scenario_start: date,
        currency: str,
    ) -> tuple[list[PlanningItem], list[dict[str, Any]]]:
        expense_by_category: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO for _ in months])
        income_by_category: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO for _ in months])
        expense_ids: dict[str, list[int]] = defaultdict(list)
        income_ids: dict[str, list[int]] = defaultdict(list)
        snapshot: list[dict[str, Any]] = []
        for index, month in enumerate(months):
            metrics = self.metrics.calculate_monthly_metrics(month, currency)
            classifications = self.classifier.classify_many(currency=currency, start=month, end=_next_month(month))
            for result in classifications:
                if result.economic_class.value == "income" and result.amount > 0:
                    category = result.analysis_category or result.source_category
                    income_by_category[category][index] += result.amount
                    income_ids[category].append(result.transaction_id)
                elif result.economic_class.value == "consumption" and result.amount < 0:
                    category = result.analysis_category or result.source_category
                    expense_by_category[category][index] += abs(result.amount)
                    expense_ids[category].append(result.transaction_id)
            snapshot.append({
                "month": month,
                "complete": metrics.completeness.complete,
                "issue_codes": list(metrics.completeness.issues),
                "source_coverage": metrics.completeness.source_coverage,
                "unclassified_transaction_count": metrics.unclassified_transaction_count,
            })
        end = _horizon_end(scenario_start)
        issue_codes = sorted({code for item in snapshot for code in item["issue_codes"]})
        items: list[PlanningItem] = []
        for category, values in sorted(income_by_category.items()):
            average = sum(values, ZERO) / Decimal(len(months))
            if average:
                items.append(PlanningItem(
                    kind=PlanningItemKind.INCOME,
                    category=category,
                    label=category,
                    amount=average,
                    frequency=PlanningFrequency.MONTHLY,
                    start_month=scenario_start,
                    end_month=end,
                    origin=PlanningSeedOrigin.HISTORICAL.value,
                    completeness_codes=issue_codes,
                    contributor_transaction_ids=sorted(set(income_ids[category])),
                    provenance={"history_start": months[0].isoformat(), "history_end": months[-1].isoformat()},
                ))
        for category, values in sorted(expense_by_category.items()):
            average = sum(values, ZERO) / Decimal(len(months))
            if average:
                items.append(PlanningItem(
                    kind=PlanningItemKind.EXPENSE,
                    category=category,
                    label=category,
                    amount=average,
                    frequency=PlanningFrequency.MONTHLY,
                    start_month=scenario_start,
                    end_month=end,
                    origin=PlanningSeedOrigin.HISTORICAL.value,
                    completeness_codes=issue_codes,
                    contributor_transaction_ids=sorted(set(expense_ids[category])),
                    provenance={"history_start": months[0].isoformat(), "history_end": months[-1].isoformat()},
                ))
        return items, snapshot

    @staticmethod
    def _csv_controls(parsed: dict[str, Any]) -> dict[str, dict[str, Any]]:
        explicit_expenses = sum((entry["amount"] for entry in parsed["expenses"]), ZERO)
        # The block total reconciles the explicit target rows.  The separate
        # monthly-expense control is the household total and exposes the
        # deliberately unresolved blank target/narrative gap.
        target_block_total = parsed["expense_control_total"]
        control_expenses = parsed.get("monthly_expense_control_total") or target_block_total
        explicit_income = sum((entry["amount"] for entry in parsed["incomes"]), ZERO)
        control_income = parsed["income_control_total"]
        summary = parsed["savings_summary"] or {}
        savings = summary.get("savings")
        monthly_expenses = summary.get("expenses")
        cash_identity = (
            summary.get("income") - monthly_expenses - savings
            if summary.get("income") is not None and monthly_expenses is not None and savings is not None
            else None
        )
        return {
            "expenses": {
                "expected": control_expenses,
                "actual": explicit_expenses,
                "gap": (control_expenses - explicit_expenses) if control_expenses is not None else None,
                "passed": control_expenses is not None and control_expenses == explicit_expenses,
                "explicit_target_count": len(parsed["expenses"]),
                "target_block_total": target_block_total,
            },
            "income": {
                "expected": control_income,
                "actual": explicit_income,
                "gap": (control_income - explicit_income) if control_income is not None else None,
                "passed": control_income is not None and control_income == explicit_income,
                "recurring_row_count": len(parsed["incomes"]),
            },
            "savings": {
                "amount": savings,
                "passed": savings is not None,
                "summary_count": 1 if savings is not None else 0,
            },
            "cash_identity": {
                "value": cash_identity,
                "passed": cash_identity == ZERO if cash_identity is not None else False,
            },
        }

    def _planning_source_by_hash(self, sha256: str) -> PlanningSourceFileRow | None:
        with self.database.session() as session:
            return session.execute(
                select(PlanningSourceFileRow).where(PlanningSourceFileRow.sha256 == sha256)
            ).scalar_one_or_none()

    def _scenario_for_source(self, source_id: int) -> str | None:
        with self.database.session() as session:
            return session.execute(
                select(PlanningSeedImportRow.scenario_id)
                .where(PlanningSeedImportRow.source_file_id == source_id)
                .order_by(PlanningSeedImportRow.imported_at)
                .limit(1)
            ).scalar_one_or_none()

    def _archive_planning_source(self, sha256: str, file_bytes: bytes, filename: str | None) -> Path:
        self.settings.ensure_directories()
        suffix = Path(filename or "planning.csv").suffix.lower() or ".csv"
        target = self.settings.planning_archive_root / f"{sha256}{suffix}"
        if target.exists():
            existing_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            if existing_hash == sha256:
                return target
        temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
        try:
            with temporary.open("wb") as handle:
                handle.write(file_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != sha256:
                raise PlanningValidationError("Planning archive hash verification failed")
            os.replace(temporary, target)
            return target
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _token(payload: dict[str, Any]) -> str:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode()
        signature = hashlib.sha256(body).hexdigest().encode()
        return base64.urlsafe_b64encode(body + b"." + signature).decode()

    @staticmethod
    def _decode_token(token: str) -> dict[str, Any]:
        try:
            raw = base64.urlsafe_b64decode(token.encode())
            body, signature = raw.rsplit(b".", 1)
            if hashlib.sha256(body).hexdigest().encode() != signature:
                raise ValueError
            return json.loads(body)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise PlanningPreviewStaleError("Invalid or expired planning preview token") from exc


__all__ = [
    "PLANNING_POLICY_VERSION",
    "DuplicateSeedError",
    "PlanningCSVParser",
    "PlanningPreviewStaleError",
    "PlanningService",
    "PlanningStaleRevisionError",
    "PlanningValidationError",
    "PreviewStaleError",
    "StaleRevisionError",
]
