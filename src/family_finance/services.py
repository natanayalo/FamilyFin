"""Application services for inspection, preview, commit, and reconciliation."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from family_finance.config import Settings
from family_finance.importers.familybiz import (
    FamilyBizParser,
    FamilyBizSchemaError,
)
from family_finance.models import (
    DataQualityIssue,
    ImportPreview,
    ImportResult,
    ImportStatistics,
    ImportStatus,
    ReconciliationDecision,
)
from family_finance.persistence.db import Database, json_dumps, utc_now
from family_finance.persistence.repositories import ImportRepository


class PreviewStaleError(ValueError):
    """The uploaded file or database baseline changed after preview."""


class ImportService:
    def __init__(
        self,
        settings: Settings | None = None,
        database: Database | None = None,
    ) -> None:
        self.settings = settings or Settings.from_environment()
        self.settings.ensure_directories()
        self.database = database or Database(self.settings.database_path)
        self.parser = FamilyBizParser(self.settings)
        self.import_repository = ImportRepository()
        self.classification_service = ClassificationService(self.database)
        self.metrics_service = MetricsService(
            self.database, classifier=self.classification_service
        )

    def inspect_familybiz(self, file_bytes: bytes):
        return self.parser.inspect(file_bytes)

    def preview_import(
        self,
        file_bytes: bytes,
        filename: str | None = None,
    ) -> ImportPreview:
        parsed = self.parser.parse(file_bytes, filename=filename)
        baseline = self.database.latest_committed_batch_id()
        token_payload = {
            "file_sha256": parsed.inspection.file_sha256,
            "parser_version": parsed.inspection.parser_version,
            "baseline_batch_id": baseline,
        }
        token = self._encode_token(token_payload)
        warning_count = len(parsed.issues)
        return ImportPreview(
            preview_token=token,
            inspection=parsed.inspection,
            parser_version=parsed.inspection.parser_version,
            file_sha256=parsed.inspection.file_sha256,
            baseline_batch_id=baseline,
            candidate_count=len(parsed.records),
            warning_count=warning_count,
            rejected_count=0,
            issue_counts=dict(Counter(issue.code for issue in parsed.issues)),
            preview_rows=parsed.inspection.preview_rows,
        )

    def commit_import(
        self,
        file_bytes: bytes,
        preview_token: str,
        filename: str | None = None,
    ) -> ImportResult:
        token = self._decode_token(preview_token)
        try:
            parsed = self.parser.parse(file_bytes, filename=filename)
        except FamilyBizSchemaError:
            batch_id = str(uuid.uuid4())
            statistics = ImportStatistics(total_records=0, rejected=1)
            with self.database.write_session() as session:
                self.import_repository.insert_batch(
                    session,
                    id=batch_id,
                    parser_version=self.settings.parser_version,
                    baseline_batch_id=token.get("baseline_batch_id"),
                    status=ImportStatus.REJECTED.value,
                    statistics_json=statistics.model_dump_json(),
                    error_code="SCHEMA_ERROR",
                    created_at=utc_now(),
                )
            return ImportResult(
                batch_id=batch_id,
                status=ImportStatus.REJECTED,
                statistics=statistics,
                issues=[
                    DataQualityIssue(
                        code="SCHEMA_ERROR",
                        message="File rejected by FamilyBiz schema validation",
                        severity="error",
                    )
                ],
            )
        current_baseline = self.database.latest_committed_batch_id()
        if token.get("file_sha256") != parsed.inspection.file_sha256:
            raise PreviewStaleError("The uploaded file changed after preview")
        if token.get("parser_version") != parsed.inspection.parser_version:
            raise PreviewStaleError("The parser version changed after preview")
        if token.get("baseline_batch_id") != current_baseline:
            raise PreviewStaleError("The database changed after preview; preview again")

        archive_path = self._archive(parsed.inspection.file_sha256, file_bytes)
        batch_id = str(uuid.uuid4())
        created_at = utc_now()
        existing_file = self.database.source_file_by_hash(parsed.inspection.file_sha256)
        if existing_file:
            stats = ImportStatistics(
                total_records=parsed.inspection.transaction_count,
                duplicate_file=True,
                non_ils_records=parsed.inspection.currencies.get("USD", 0),
            )
            with self.database.write_session() as session:
                self.import_repository.insert_batch(
                    session,
                    id=batch_id,
                    source_file_id=existing_file["id"],
                    parser_version=parsed.inspection.parser_version,
                    baseline_batch_id=current_baseline,
                    report_start=_iso(parsed.inspection.report_start),
                    report_end=_iso(parsed.inspection.report_end),
                    max_transaction_date=_iso(parsed.inspection.max_booking_date),
                    freshness_days=_freshness_days(parsed.inspection.max_booking_date),
                    status=ImportStatus.DUPLICATE.value,
                    statistics_json=stats.model_dump_json(),
                    created_at=created_at,
                )
            return ImportResult(
                batch_id=batch_id,
                status=ImportStatus.DUPLICATE,
                statistics=stats,
                issues=parsed.issues,
            )

        statistics = ImportStatistics(
            total_records=len(parsed.records),
            non_ils_records=sum(record.non_ils for record in parsed.records),
        )
        unresolved_issues: list[DataQualityIssue] = list(parsed.issues)
        exact_seen: Counter[tuple[Any, ...]] = Counter()
        core_seen: Counter[tuple[Any, ...]] = Counter()
        created_transaction_ids: set[int] = set()
        reserved_reconciliation_transaction_ids: set[int] = set()

        with self.database.write_session() as session:
            source_file = self.import_repository.insert_source_file(
                session,
                sha256=parsed.inspection.file_sha256,
                original_filename=parsed.inspection.filename,
                archived_path=str(archive_path),
                compressed_bytes=parsed.inspection.compressed_bytes,
                uncompressed_bytes=parsed.inspection.uncompressed_bytes,
                created_at=created_at,
            )
            source_file_id = int(source_file.id)
            self.import_repository.insert_batch(
                session,
                id=batch_id,
                source_file_id=source_file_id,
                parser_version=parsed.inspection.parser_version,
                baseline_batch_id=current_baseline,
                report_start=_iso(parsed.inspection.report_start),
                report_end=_iso(parsed.inspection.report_end),
                max_transaction_date=_iso(parsed.inspection.max_booking_date),
                freshness_days=_freshness_days(parsed.inspection.max_booking_date),
                status=ImportStatus.COMMITTED.value,
                statistics_json=statistics.model_dump_json(),
                created_at=created_at,
            )
            account_ids: dict[str, int] = {}
            for record in parsed.records:
                account_ids[record.account.source_reference_fingerprint] = (
                    self.import_repository.account_id(session, record)
                )
            for record in parsed.records:
                self.import_repository.ensure_category(session, record)
            planned_existing_matches, claimed_existing_transaction_ids = (
                self._plan_existing_matches(
                    session, parsed.records, account_ids
                )
            )

            for record in parsed.records:
                account_id = account_ids[record.account.source_reference_fingerprint]
                exact_key = _exact_key(record)
                core_key = _core_key(record)
                exact_rows = [
                    row
                    for row in self.import_repository.find_exact(session, record, account_id)
                    if int(row["id"]) not in created_transaction_ids
                ]
                exact_index = exact_seen[exact_key]
                source_state = "accepted"
                match_method = "inserted"
                transaction_id: int | None = None
                planned_match = planned_existing_matches.get(_source_key(record))
                if planned_match and planned_match[0] != "ambiguous":
                    match_method, transaction_id = planned_match
                    if match_method == "exact_unchanged":
                        statistics.unchanged += 1
                    else:
                        self.import_repository.update_transaction(
                            session, transaction_id, record, created_at
                        )
                        statistics.updated += 1
                elif planned_match:
                    source_state = "unresolved"
                    statistics.ambiguous += 1
                    statistics.unresolved += 1
                    issue = DataQualityIssue(
                        code="RECONCILIATION_REQUIRED",
                        message="The source row has multiple or conflicting candidates",
                        source_row=record.source_row_number,
                        section_index=record.section_index,
                    )
                    unresolved_issues.append(issue)
                    candidates = planned_match[1]
                elif len(exact_rows) > exact_index:
                    transaction_id = int(exact_rows[exact_index]["id"])
                    exact_seen[exact_key] += 1
                    core_seen[core_key] += 1
                    statistics.unchanged += 1
                    match_method = "exact_unchanged"
                else:
                    core_rows = [
                        row
                        for row in self.import_repository.find_core(session, record, account_id)
                        if int(row["id"]) not in created_transaction_ids
                    ]
                    core_index = core_seen[core_key]
                    if len(core_rows) == 1 and core_index == 0:
                        transaction_id = int(core_rows[0]["id"])
                        core_seen[core_key] += 1
                        exact_seen[exact_key] += 1
                        self.import_repository.update_transaction(
                            session, transaction_id, record, created_at
                        )
                        statistics.updated += 1
                        match_method = "unique_update"
                    elif not core_rows:
                        fuzzy_rows = [
                            row
                            for row in self.import_repository.find_fuzzy(session, record, account_id)
                            if int(row["id"]) not in created_transaction_ids
                            and int(row["id"]) not in claimed_existing_transaction_ids
                            and int(row["id"]) not in reserved_reconciliation_transaction_ids
                        ]
                        if _is_likely_fuzzy_revision(fuzzy_rows):
                            source_state = "unresolved"
                            statistics.ambiguous += 1
                            statistics.unresolved += 1
                            issue = DataQualityIssue(
                                code="RECONCILIATION_REQUIRED",
                                message="A likely transaction has a monetary or booking-date change",
                                source_row=record.source_row_number,
                                section_index=record.section_index,
                            )
                            unresolved_issues.append(issue)
                            candidates = [int(row["id"]) for row in fuzzy_rows]
                            if len(candidates) == 1:
                                reserved_reconciliation_transaction_ids.update(candidates)
                        else:
                            transaction_id = self.import_repository.insert_transaction(
                                session, account_id=account_id, record=record, now=created_at
                            )
                            created_transaction_ids.add(transaction_id)
                            exact_seen[exact_key] += 1
                            core_seen[core_key] += 1
                            statistics.inserted += 1
                    else:
                        source_state = "unresolved"
                        statistics.ambiguous += 1
                        statistics.unresolved += 1
                        issue = DataQualityIssue(
                            code="RECONCILIATION_REQUIRED",
                            message="The source row has multiple or changed monetary candidates",
                            source_row=record.source_row_number,
                            section_index=record.section_index,
                        )
                        unresolved_issues.append(issue)
                        candidates = [int(row["id"]) for row in core_rows]

                source_record_id = self.import_repository.insert_source_record(
                    session,
                    batch_id=batch_id,
                    account_id=account_id,
                    record=record,
                    state=source_state,
                )
                if transaction_id is not None:
                    self.import_repository.link_transaction(
                        session,
                        transaction_id=transaction_id,
                        source_record_id=source_record_id,
                        match_method=match_method,
                        linked_at=created_at,
                    )
                else:
                    case_id = str(uuid.uuid4())
                    self.import_repository.insert_reconciliation_case(
                        session,
                        case_id=case_id,
                        batch_id=batch_id,
                        source_record_id=source_record_id,
                        reason="Multiple or changed candidate transactions",
                        candidate_transaction_ids_json=json_dumps(candidates),
                        created_at=created_at,
                    )

            status = (
                ImportStatus.NEEDS_REVIEW
                if statistics.unresolved
                else ImportStatus.COMMITTED
            )
            self.import_repository.update_batch(
                session, batch_id, status.value, statistics.model_dump_json()
            )

        return ImportResult(
            batch_id=batch_id,
            status=status,
            statistics=statistics,
            issues=unresolved_issues,
        )

    def resolve_reconciliation(
        self,
        case_id: str,
        resolution: ReconciliationDecision | dict[str, Any],
    ) -> ImportResult:
        decision = (
            resolution
            if isinstance(resolution, ReconciliationDecision)
            else ReconciliationDecision(case_id=case_id, **resolution)
        )
        if decision.case_id != case_id:
            raise ValueError("Resolution case ID does not match")
        now = utc_now()
        with self.database.write_session() as session:
            case = self.import_repository.open_case(session, case_id)
            if not case:
                raise ValueError("Open reconciliation case not found")
            source = self.import_repository.source_record(session, case["source_record_id"])
            if not source:
                raise ValueError("Source record not found")
            if decision.resolution == "link_existing":
                if decision.transaction_id is None:
                    raise ValueError("link_existing requires transaction_id")
                candidate_ids = set(json.loads(case["candidate_transaction_ids_json"]))
                if decision.transaction_id not in candidate_ids:
                    raise ValueError("Selected transaction is not a case candidate")
                transaction_id = decision.transaction_id
                method = "reconciliation"
                self.import_repository.update_transaction_from_source(
                    session, transaction_id, source, now
                )
            elif decision.resolution == "accept_as_new":
                transaction_id = self.import_repository.transaction_from_source(
                    session, source, now
                )
                method = "inserted"
            elif decision.resolution == "dismiss":
                self.import_repository.update_case(
                    session,
                    case_id,
                    status="dismissed",
                    resolution_json=json_dumps(decision.model_dump()),
                    resolved_at=now,
                )
                self.import_repository.mark_source_state(session, source["id"], "dismissed")
                status, statistics = self._refresh_batch_status(
                    session, case["import_batch_id"]
                )
                return ImportResult(
                    batch_id=case["import_batch_id"],
                    status=status,
                    statistics=statistics,
                )
            else:
                raise ValueError("resolution must be link_existing, accept_as_new, or dismiss")

            self.import_repository.link_transaction(
                session,
                transaction_id=transaction_id,
                source_record_id=source["id"],
                match_method=method,
                linked_at=now,
            )
            self.import_repository.mark_source_state(session, source["id"], "accepted")
            self.import_repository.update_case(
                session,
                case_id,
                status="resolved",
                resolution_json=json_dumps(decision.model_dump()),
                resolved_at=now,
            )
            status, statistics = self._refresh_batch_status(
                session, case["import_batch_id"]
            )
        return ImportResult(
            batch_id=case["import_batch_id"],
            status=status,
            statistics=statistics,
        )

    def history(self) -> list[dict[str, Any]]:
        with self.database.session() as session:
            rows = self.import_repository.history(session)
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["statistics"] = json.loads(item.pop("statistics_json"))
            result.append(item)
        return result

    def reconciliation_cases(self) -> list[dict[str, Any]]:
        with self.database.session() as session:
            return self.import_repository.open_reconciliation_cases(session)

    def _archive(self, file_hash: str, file_bytes: bytes) -> Path:
        target = self.settings.archive_root / f"{file_hash}.xlsx"
        if not target.exists():
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(file_bytes)
            temporary.replace(target)
        return target

    @staticmethod
    def _encode_token(payload: dict[str, Any]) -> str:
        body = json_dumps(payload).encode("utf-8")
        signature = hashlib.sha256(body).hexdigest()
        encoded = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
        return f"{encoded}.{signature}"

    @staticmethod
    def _decode_token(token: str) -> dict[str, Any]:
        try:
            encoded, signature = token.split(".", 1)
            body = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            if hashlib.sha256(body).hexdigest() != signature:
                raise ValueError
            return json.loads(body)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PreviewStaleError("Invalid or expired preview token") from exc

    @staticmethod
    def _plan_existing_matches(connection, records, account_ids):
        """Reserve one existing transaction per source occurrence before import.

        Matching each row while mutating the database makes recurring rows
        order-dependent: an exact match can consume the candidate that a
        later revised occurrence needs for reconciliation. Planning exact and
        core matches first gives every source occurrence a stable reservation.
        """
        planned: dict[tuple[str, int, int], tuple[str, Any]] = {}
        claimed: set[int] = set()

        for record in records:
            source_key = _source_key(record)
            account_id = account_ids[record.account.source_reference_fingerprint]
            exact_rows = [
                row
                for row in ImportRepository.find_exact(connection, record, account_id)
                if int(row["id"]) not in claimed
            ]
            if exact_rows:
                transaction_id = int(exact_rows[0]["id"])
                planned[source_key] = ("exact_unchanged", transaction_id)
                claimed.add(transaction_id)

        for record in records:
            source_key = _source_key(record)
            if source_key in planned:
                continue
            account_id = account_ids[record.account.source_reference_fingerprint]
            core_rows = [
                row
                for row in ImportRepository.find_core(connection, record, account_id)
                if int(row["id"]) not in claimed
            ]
            if len(core_rows) == 1:
                transaction_id = int(core_rows[0]["id"])
                planned[source_key] = ("unique_update", transaction_id)
                claimed.add(transaction_id)
            elif len(core_rows) > 1:
                planned[source_key] = (
                    "ambiguous",
                    [int(row["id"]) for row in core_rows],
                )
            else:
                all_core_rows = ImportRepository.find_core(connection, record, account_id)
                if all_core_rows:
                    planned[source_key] = (
                        "ambiguous",
                        [int(row["id"]) for row in all_core_rows],
                    )
        return planned, claimed

    @staticmethod
    def _refresh_batch_status(
        connection, batch_id: str
    ) -> tuple[ImportStatus, ImportStatistics]:
        status, values = ImportRepository.refresh_batch_status(connection, batch_id)
        return ImportStatus(status), ImportStatistics.model_validate(values)

def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _freshness_days(max_date: date | None) -> int | None:
    if not max_date:
        return None
    return (datetime.now(UTC).date() - max_date).days


def _exact_key(record) -> tuple[Any, ...]:
    return (
        record.account.source_reference_fingerprint,
        record.booking_date,
        record.amount,
        record.currency,
        record.description,
        record.original_currency,
        record.original_amount,
    )


def _core_key(record) -> tuple[Any, ...]:
    return (
        record.account.source_reference_fingerprint,
        record.booking_date,
        record.amount,
        record.currency,
        record.original_currency,
        record.original_amount,
    )


def _source_key(record) -> tuple[str, int, int]:
    return (record.sheet_name, record.section_index, record.source_row_number)


def _is_likely_fuzzy_revision(fuzzy_rows) -> bool:
    """Reconcile whenever an unclaimed fuzzy candidate remains.

    Exact/core matches are reserved in a prepass. That makes an extra recurring
    occurrence have no unclaimed candidate, while revisions inside an existing
    series remain available for review even when multiple candidates exist.
    """
    return bool(fuzzy_rows)


# Phase 2 services remain importable from the original application-services
# module for callers that use the Phase 1 public entry point.
from family_finance.classification import (
    ClassificationEngine,
    ClassificationService,
    FinancialClassificationService,
)
from family_finance.metrics import FinancialMetricsService, MetricsEngine, MetricsService

__all__ = [
    "ClassificationEngine",
    "ClassificationService",
    "FinancialClassificationService",
    "FinancialMetricsService",
    "ImportService",
    "MetricsEngine",
    "MetricsService",
    "PreviewStaleError",
]
