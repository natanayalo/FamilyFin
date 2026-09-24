"""Application services for inspection, preview, commit, and reconciliation."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import uuid
from collections import Counter
from datetime import UTC, date, datetime
from itertools import groupby
from pathlib import Path
from typing import Any

from sqlalchemy import select

from family_finance.config import Settings
from family_finance.importers.familybiz import (
    FamilyBizParser,
    FamilyBizSchemaError,
)
from family_finance.logging import JsonEventLogger
from family_finance.models import (
    DataQualityIssue,
    ImportPreflight,
    ImportPreview,
    ImportResult,
    ImportStatistics,
    ImportStatus,
    ReconciliationDecision,
)
from family_finance.persistence.db import Database, json_dumps, utc_now
from family_finance.persistence.models import (
    AccountRow,
    ImportBatchRow,
    SourceFileRow,
    TransactionRow,
)
from family_finance.persistence.repositories import ImportRepository


class PreviewStaleError(ValueError):
    """The uploaded file or database baseline changed after preview."""


class ImportAmbiguityError(ValueError):
    """Automation refused to commit a file requiring reconciliation."""


class ImportValidationError(ValueError):
    """The submitted workbook failed parser or schema validation."""


_MATCHER_VERSION = "familybiz-matcher-v2"
_DECISION_PLAN_VERSION = "familybiz-decision-plan-v1"


class _PlannedImport:
    def __init__(self, *, plan_json, plan_fingerprint, statistics, group_decisions, exact_ids):
        self.plan_json = plan_json
        self.plan_fingerprint = plan_fingerprint
        self.statistics = statistics
        self.group_decisions = group_decisions
        self.exact_ids = exact_ids


class ImportService:
    def __init__(
        self,
        settings: Settings | None = None,
        database: Database | None = None,
    ) -> None:
        self.settings = settings or Settings.from_environment()
        self.settings.ensure_directories()
        self.database = database or Database(self.settings.database_path)
        self.logger = JsonEventLogger(self.settings.log_path)
        self.parser = FamilyBizParser(self.settings)
        self.import_repository = ImportRepository()
        self.classification_service = ClassificationService(self.database)
        self.metrics_service = MetricsService(
            self.database, classifier=self.classification_service
        )
        from family_finance.planning import PlanningService

        self.planning_service = PlanningService(
            self.database,
            settings=self.settings,
            metrics=self.metrics_service,
            classifier=self.classification_service,
        )
        from family_finance.forecasting import SavingsForecastService

        self.savings_forecast_service = SavingsForecastService(
            self.database,
            planning_service=self.planning_service,
        )
        from family_finance.net_worth import NetWorthService

        self.net_worth_service = NetWorthService(self.database, self.settings)
        self.household_net_worth_service = self.net_worth_service
        # Short aliases keep the application surface convenient while the
        # explicit name documents that this is a savings-only forecast.
        self.forecasting_service = self.savings_forecast_service
        self.forecast_service = self.savings_forecast_service
        from family_finance.apartment import ApartmentPlanningService

        self.apartment_planning_service = ApartmentPlanningService(
            self.database,
            forecast_service=self.savings_forecast_service,
            planning_service=self.planning_service,
        )
        self.apartment_service = self.apartment_planning_service
        self.insights_service = InsightsService(
            self.database,
            classifier=self.classification_service,
            metrics=self.metrics_service,
            settings=self.settings,
        )
        self.insights = self.insights_service

    def inspect_familybiz(self, file_bytes: bytes):
        return self.parser.inspect(file_bytes)

    def preview_import(
        self,
        file_bytes: bytes,
        filename: str | None = None,
    ) -> ImportPreview:
        parsed = self.parser.parse(file_bytes, filename=filename)
        with self.database.session() as session:
            baseline = self._latest_committed_batch_in_session(session)
            baseline_fingerprint, matching_baseline_json = self._matching_state(
                session, parsed.records, parsed.inspection.file_sha256
            )
            duplicate = session.execute(
                select(SourceFileRow.id).where(
                    SourceFileRow.sha256 == parsed.inspection.file_sha256
                )
            ).scalar_one_or_none() is not None
            planned = self._build_import_plan(
                session, parsed.records, parsed.inspection.file_sha256,
                parsed.inspection.parser_version, duplicate=duplicate,
            )
        token_payload = self._preview_token_payload(
            parsed, baseline, baseline_fingerprint, planned
        )
        token = self._encode_token(token_payload)
        warning_count = len(parsed.issues) + planned.statistics.ambiguous
        preview = ImportPreview(
            preview_token=token,
            inspection=parsed.inspection,
            parser_version=parsed.inspection.parser_version,
            file_sha256=parsed.inspection.file_sha256,
            baseline_batch_id=baseline,
            baseline_fingerprint=baseline_fingerprint,
            matching_baseline_json=matching_baseline_json,
            matcher_version=_MATCHER_VERSION,
            decision_plan_version=_DECISION_PLAN_VERSION,
            decision_plan_fingerprint=planned.plan_fingerprint,
            decision_plan_json=planned.plan_json,
            candidate_count=len(parsed.records),
            warning_count=warning_count,
            rejected_count=0,
            issue_counts=self._issue_counts(parsed.issues, planned.statistics.ambiguous),
            preview_rows=parsed.inspection.preview_rows,
            predicted_statistics=planned.statistics,
        )
        self.logger.event(
            "import_preview",
            counts={"candidates": preview.candidate_count, "warnings": preview.warning_count},
            issue_codes=list(preview.issue_counts),
        )
        return preview

    def preflight_import(
        self,
        file_bytes: bytes,
        filename: str | None = None,
    ) -> ImportPreflight:
        """Predict a commit using the same occurrence-aware matcher as commit.

        This method intentionally performs no writes: it creates no account,
        category, source-file, batch, transaction, or archive rows.
        """
        parsed = self.parser.parse(file_bytes, filename=filename)
        with self.database.session() as session:
            baseline = self._latest_committed_batch_in_session(session)
            baseline_fingerprint, matching_baseline_json = self._matching_state(
                session, parsed.records, parsed.inspection.file_sha256
            )
            duplicate = session.execute(
                select(SourceFileRow.id).where(
                    SourceFileRow.sha256 == parsed.inspection.file_sha256
                )
            ).scalar_one_or_none() is not None
            planned = self._build_import_plan(
                session, parsed.records, parsed.inspection.file_sha256,
                parsed.inspection.parser_version, duplicate=duplicate,
            )
        statistics = planned.statistics
        issue_counts = self._issue_counts(parsed.issues, statistics.ambiguous)
        token_payload = {
            **self._preview_token_payload(parsed, baseline, baseline_fingerprint, planned),
        }
        preview = ImportPreflight(
            preview_token=self._encode_token(token_payload),
            inspection=parsed.inspection,
            parser_version=parsed.inspection.parser_version,
            file_sha256=parsed.inspection.file_sha256,
            baseline_batch_id=baseline,
            baseline_fingerprint=baseline_fingerprint,
            matching_baseline_json=matching_baseline_json,
            matcher_version=_MATCHER_VERSION,
            decision_plan_version=_DECISION_PLAN_VERSION,
            decision_plan_fingerprint=planned.plan_fingerprint,
            decision_plan_json=planned.plan_json,
            candidate_count=len(parsed.records),
            warning_count=sum(issue_counts.values()),
            rejected_count=0,
            issue_counts=issue_counts,
            preview_rows=parsed.inspection.preview_rows,
            predicted_statistics=statistics,
            duplicate_file=duplicate,
            ambiguous_count=statistics.ambiguous,
            reconciliation_count=statistics.unresolved,
            action="duplicate" if duplicate else ("needs_review" if statistics.ambiguous else "commit"),
        )
        self.logger.event(
            "import_preflight",
            counts={
                "candidates": statistics.total_records,
                "inserted": statistics.inserted,
                "updated": statistics.updated,
                "ambiguous": statistics.ambiguous,
            },
            issue_codes=list(preview.issue_counts),
        )
        return preview

    def commit_import(
        self,
        file_bytes: bytes,
        preview_token: str,
        filename: str | None = None,
        require_unambiguous: bool = False,
    ) -> ImportResult:
        token = self._decode_token(preview_token)
        self.classification_service.invalidate_cache()
        try:
            parsed = self.parser.parse(file_bytes, filename=filename)
        except FamilyBizSchemaError as exc:
            raise ImportValidationError(f"Workbook validation failed: {exc}") from exc
        if token.get("file_sha256") != parsed.inspection.file_sha256:
            raise PreviewStaleError("The uploaded file changed after preview")
        if token.get("parser_version") != parsed.inspection.parser_version:
            raise PreviewStaleError("The parser version changed after preview")
        if token.get("matcher_version") != _MATCHER_VERSION:
            raise PreviewStaleError("The matcher version changed after preview")
        if token.get("decision_plan_version") != _DECISION_PLAN_VERSION:
            raise PreviewStaleError("The import decision plan version changed after preview")

        batch_id = str(uuid.uuid4())
        created_at = utc_now()
        unresolved_issues: list[DataQualityIssue] = list(parsed.issues)

        with self.database.write_session() as session:
            locked_baseline = self._latest_committed_batch_in_session(session)
            locked_fingerprint, _baseline_json = self._matching_state(
                session, parsed.records, parsed.inspection.file_sha256
            )
            planned = self._build_import_plan(
                session,
                parsed.records,
                parsed.inspection.file_sha256,
                parsed.inspection.parser_version,
                duplicate=False,
            )
            if token.get("baseline_fingerprint") != locked_fingerprint:
                raise PreviewStaleError(
                    "The database matching state changed after preview; preview again"
                )
            if token.get("decision_plan_fingerprint") != planned.plan_fingerprint:
                raise PreviewStaleError(
                    "The import decisions changed after preview; preview again"
                )
            existing_after_lock = session.execute(
                select(SourceFileRow).where(SourceFileRow.sha256 == parsed.inspection.file_sha256)
            ).scalar_one_or_none()
            if existing_after_lock is not None:
                stats = ImportStatistics(
                    total_records=parsed.inspection.transaction_count,
                    duplicate_file=True,
                    non_ils_records=sum(record.non_ils for record in parsed.records),
                )
                self.import_repository.insert_batch(
                    session,
                    id=batch_id,
                    source_file_id=existing_after_lock.id,
                    parser_version=parsed.inspection.parser_version,
                    baseline_batch_id=locked_baseline,
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
            if require_unambiguous and (
                planned.statistics.ambiguous or planned.statistics.unresolved
            ):
                raise ImportAmbiguityError(
                    "Commit requires an unambiguous occurrence-aware match"
                )

            statistics = planned.statistics.model_copy(update={
                "inserted": 0,
                "unchanged": 0,
                "ambiguous": 0,
                "unresolved": 0,
            })
            current_baseline = locked_baseline
            archive_path = self._archive(parsed.inspection.file_sha256, file_bytes)
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
                reference = record.account.source_reference_fingerprint
                if reference not in account_ids:
                    account_ids[reference] = self.import_repository.account_id(session, record)
            category_examples = {}
            for record in parsed.records:
                category_examples.setdefault(
                    (record.movement_type or "", record.category), record
                )
            for record in category_examples.values():
                self.import_repository.ensure_category(session, record)

            for index, record in enumerate(parsed.records):
                account_id = account_ids[record.account.source_reference_fingerprint]
                source_state = "accepted"
                transaction_id: int | None = None
                match_method = "inserted"
                if planned.exact_ids[index] is not None:
                    transaction_id = planned.exact_ids[index]
                    match_method = "exact_unchanged"
                    statistics.unchanged += 1
                else:
                    group_key = _exact_signature(record)
                    group_decision = planned.group_decisions[group_key]
                    if group_decision["type"] == "ambiguous":
                        candidates = group_decision["candidates"]
                        source_state = "unresolved"
                        statistics.ambiguous += 1
                        statistics.unresolved += 1
                        unresolved_issues.append(DataQualityIssue(
                            code="RECONCILIATION_REQUIRED",
                            message="The source row has plausible non-exact candidate transactions",
                            source_row=record.source_row_number,
                            section_index=record.section_index,
                        ))
                    else:
                        transaction_id = self.import_repository.insert_transaction(
                            session, account_id=account_id, record=record, now=created_at
                        )
                        statistics.inserted += 1

                if source_state != "unresolved" and transaction_id is None:
                    raise RuntimeError("Import plan did not assign a transaction decision")

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
                        reason="Plausible non-exact candidate transactions",
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

        result = ImportResult(
            batch_id=batch_id,
            status=status,
            statistics=statistics,
            issues=unresolved_issues,
        )
        self.logger.event(
            "import_commit",
            counts={
                "records": statistics.total_records,
                "inserted": statistics.inserted,
                "updated": statistics.updated,
                "unresolved": statistics.unresolved,
            },
            issue_codes=[issue.code for issue in unresolved_issues],
        )
        return result

    def resolve_reconciliation(
        self,
        case_id: str,
        resolution: ReconciliationDecision | dict[str, Any],
    ) -> ImportResult:
        self.classification_service.invalidate_cache()
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
    def _latest_committed_batch_in_session(session) -> str | None:
        row = session.execute(
            select(ImportBatchRow.id)
            .where(ImportBatchRow.status.in_(("committed", "needs_review")))
            .order_by(ImportBatchRow.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return str(row) if row else None

    def _matching_state(self, session, records, workbook_hash: str) -> tuple[str, str]:
        """Fingerprint only persisted state consulted by import matching."""
        relevant_references = sorted({
            record.account.source_reference_fingerprint for record in records
        })
        account_digest = hashlib.sha256()
        account_count = 0
        relevant_account_ids: list[int] = []
        account_statement = select(
            AccountRow.id, AccountRow.source_reference_fingerprint
        ).where(AccountRow.source_reference_fingerprint.in_(relevant_references)).order_by(
            AccountRow.source_reference_fingerprint, AccountRow.id
        )
        for account_id, reference in session.execute(account_statement).yield_per(1000):
            account_count += 1
            relevant_account_ids.append(int(account_id))
            account_digest.update(_canonical_json([int(account_id), reference]).encode())
            account_digest.update(b"\n")

        transaction_digest = hashlib.sha256()
        transaction_count = 0
        transaction_statement = (
            select(
                TransactionRow.id,
                AccountRow.source_reference_fingerprint,
                TransactionRow.booking_date,
                TransactionRow.amount,
                TransactionRow.currency,
                TransactionRow.description,
                TransactionRow.original_currency,
                TransactionRow.original_amount,
            )
            .join(AccountRow, AccountRow.id == TransactionRow.account_id)
            .where(TransactionRow.account_id.in_(relevant_account_ids))
            .order_by(TransactionRow.id)
        )
        for row in session.execute(transaction_statement).yield_per(1000):
            transaction_count += 1
            transaction_digest.update(_canonical_json(list(row)).encode())
            transaction_digest.update(b"\n")

        file_already_imported = session.execute(
            select(SourceFileRow.id).where(SourceFileRow.sha256 == workbook_hash)
        ).scalar_one_or_none() is not None

        baseline = {
            "version": _MATCHER_VERSION,
            "account_registry": {
                "configured": False,
                "configuration_state": "not_configured",
                "requested_account_count": len(relevant_references),
                "known_account_count": account_count,
                "known_account_fingerprint": account_digest.hexdigest(),
            },
            "transactions": {
                "count": transaction_count,
                "fingerprint": transaction_digest.hexdigest(),
            },
            "source_file": {
                "workbook_sha256": workbook_hash,
                "already_imported": file_already_imported,
            },
        }
        baseline_json = _canonical_json(baseline)
        return hashlib.sha256(baseline_json.encode("utf-8")).hexdigest(), baseline_json

    def _build_import_plan(
        self,
        session,
        records,
        workbook_hash: str,
        parser_version: str,
        *,
        duplicate: bool,
    ) -> _PlannedImport:
        """Build a canonical occurrence plan after reserving exact matches."""
        groups: dict[str, dict[str, Any]] = {}
        record_group_keys: list[str] = []
        for index, record in enumerate(records):
            group_key = _exact_signature(record)
            group = groups.get(group_key)
            if group is None:
                group = {
                    "representative": index,
                    "multiplicity": 0,
                    "exact_candidates": [],
                    "nonexact_candidates": set(),
                }
                groups[group_key] = group
            group["multiplicity"] += 1
            record_group_keys.append(group_key)

        core_groups: dict[str, list[str]] = {}
        fuzzy_groups: dict[str, list[str]] = {}
        for group_key, group in groups.items():
            record = records[group["representative"]]
            core_groups.setdefault(_core_signature(record), []).append(group_key)
            fuzzy_groups.setdefault(_fuzzy_signature(record), []).append(group_key)

        record_references = sorted({
            record.account.source_reference_fingerprint for record in records
        })
        accounts = session.execute(
            select(AccountRow.id, AccountRow.source_reference_fingerprint).where(
                AccountRow.source_reference_fingerprint.in_(record_references)
            )
        ).all()
        account_ids = {reference: int(account_id) for account_id, reference in accounts}
        account_references = {int(account_id): reference for account_id, reference in accounts}
        if account_ids:
            statement = (
                select(
                    TransactionRow.id,
                    TransactionRow.account_id,
                    TransactionRow.booking_date,
                    TransactionRow.amount,
                    TransactionRow.currency,
                    TransactionRow.description,
                    TransactionRow.original_currency,
                    TransactionRow.original_amount,
                )
                .where(TransactionRow.account_id.in_(list(account_ids.values())))
                .order_by(TransactionRow.id)
            )
            for row in session.execute(statement).yield_per(1000):
                (
                    transaction_id,
                    account_id,
                    booking_date,
                    amount,
                    currency,
                    description,
                    original_currency,
                    original_amount,
                ) = row
                account_reference = account_references[int(account_id)]
                exact_key = _transaction_exact_signature(
                    account_reference, booking_date, amount, currency, description,
                    original_currency, original_amount,
                )
                exact_group = groups.get(exact_key)
                if exact_group is not None:
                    exact_group["exact_candidates"].append(int(transaction_id))

                core_key = _transaction_core_signature(
                    account_reference, booking_date, amount, currency,
                    original_currency, original_amount,
                )
                for group_key in core_groups.get(core_key, ()):
                    if group_key != exact_key:
                        groups[group_key]["nonexact_candidates"].add(int(transaction_id))

                fuzzy_key = _transaction_fuzzy_signature(
                    account_reference, booking_date, currency, description,
                    original_currency, original_amount,
                )
                for group_key in fuzzy_groups.get(fuzzy_key, ()):
                    if group_key != exact_key:
                        groups[group_key]["nonexact_candidates"].add(int(transaction_id))

        exact_ids: list[int | None] = [None] * len(records)
        exact_cursors: Counter[str] = Counter()
        reserved: set[int] = set()
        for group in groups.values():
            group["exact_candidates"].sort()
        for index, group_key in enumerate(record_group_keys):
            group = groups[group_key]
            cursor = exact_cursors[group_key]
            candidates = group["exact_candidates"]
            if cursor < len(candidates):
                transaction_id = candidates[cursor]
                exact_ids[index] = transaction_id
                reserved.add(transaction_id)
                exact_cursors[group_key] += 1

        group_decisions: dict[str, dict[str, Any]] = {}
        ambiguous_keys: list[str] = []
        for group_key, group in groups.items():
            remaining_multiplicity = group["multiplicity"] - exact_cursors[group_key]
            candidates = sorted(group["nonexact_candidates"] - reserved)
            if candidates and remaining_multiplicity:
                group_decisions[group_key] = {
                    "type": "ambiguous",
                    "candidates": candidates,
                    "ambiguity_group": None,
                    "multiplicity": remaining_multiplicity,
                }
                ambiguous_keys.append(group_key)
            else:
                group_decisions[group_key] = {
                    "type": "new",
                    "candidates": [],
                    "ambiguity_group": None,
                    "multiplicity": remaining_multiplicity,
                }

        # Connected groups sharing a candidate get a common stable ambiguity ID.
        parent = {key: key for key in ambiguous_keys}

        def find(key: str) -> str:
            root = key
            while parent[root] != root:
                root = parent[root]
            while parent[key] != key:
                next_key = parent[key]
                parent[key] = root
                key = next_key
            return root

        owners: dict[int, str] = {}
        for group_key in ambiguous_keys:
            for transaction_id in group_decisions[group_key]["candidates"]:
                previous = owners.setdefault(transaction_id, group_key)
                left = find(group_key)
                right = find(previous)
                if left != right:
                    parent[max(left, right)] = min(left, right)
        components: dict[str, list[str]] = {}
        for group_key in ambiguous_keys:
            components.setdefault(find(group_key), []).append(group_key)
        for member_keys in components.values():
            member_keys.sort()
            candidate_ids = sorted({
                transaction_id
                for group_key in member_keys
                for transaction_id in group_decisions[group_key]["candidates"]
            })
            ambiguity_id = "amb-" + hashlib.sha256(
                _canonical_json([member_keys, candidate_ids]).encode("utf-8")
            ).hexdigest()[:20]
            for group_key in member_keys:
                group_decisions[group_key]["ambiguity_group"] = ambiguity_id

        ambiguous_count = sum(
            group_decisions[key]["multiplicity"] for key in ambiguous_keys
        )
        unchanged_count = sum(value is not None for value in exact_ids)
        inserted_count = len(records) - unchanged_count - ambiguous_count
        statistics = ImportStatistics(
            total_records=len(records),
            inserted=inserted_count,
            unchanged=unchanged_count,
            ambiguous=ambiguous_count,
            unresolved=ambiguous_count,
            duplicate_file=duplicate,
            non_ils_records=sum(record.non_ils for record in records),
        )
        if duplicate:
            statistics.inserted = 0
            statistics.unchanged = 0
            statistics.ambiguous = 0
            statistics.unresolved = 0

        def decision_key(index: int):
            group_key = record_group_keys[index]
            exact_id = exact_ids[index]
            if exact_id is not None:
                return group_key, "exact_match", (exact_id,), None
            decision = group_decisions[group_key]
            return (
                group_key,
                decision["type"],
                tuple(decision["candidates"]),
                decision["ambiguity_group"],
            )

        def identity_key(index: int):
            record = records[index]
            return (
                record.sheet_name,
                _section_identity(record),
                record.source_row_number,
            )

        sorted_indices = sorted(
            range(len(records)),
            key=lambda index: (decision_key(index), identity_key(index)),
        )
        output = io.StringIO()
        plan_header = {
            "version": _DECISION_PLAN_VERSION,
            "workbook_sha256": workbook_hash,
            "parser_version": parser_version,
            "matcher_version": _MATCHER_VERSION,
        }
        output.write("{")
        output.write(",".join(
            f"{json.dumps(key)}:{_canonical_json(value)}"
            for key, value in sorted(plan_header.items())
        ))
        output.write(',"groups":[')
        first_group = True
        for key, members_iter in groupby(sorted_indices, key=decision_key):
            members = list(members_iter)
            group_key, decision_type, candidates, ambiguity_group = key
            plan_group = {
                "ambiguity_group": ambiguity_group,
                "candidate_references": list(candidates),
                "decision_type": decision_type,
                "equivalence_key": group_key,
                "multiplicity": len(members),
            }
            if not first_group:
                output.write(",")
            first_group = False
            output.write("{")
            output.write(",".join(
                f"{json.dumps(name)}:{_canonical_json(value)}"
                for name, value in sorted(plan_group.items())
            ))
            output.write(',"occurrences":[')
            for member_index, record_index in enumerate(members):
                if member_index:
                    output.write(",")
                record = records[record_index]
                output.write(_canonical_json([
                    record.sheet_name,
                    _section_identity(record),
                    record.source_row_number,
                ]))
            output.write("]}")
        output.write("]}")
        plan_json = output.getvalue()
        return _PlannedImport(
            plan_json=plan_json,
            plan_fingerprint=hashlib.sha256(plan_json.encode("utf-8")).hexdigest(),
            statistics=statistics,
            group_decisions=group_decisions,
            exact_ids=exact_ids,
        )

    @staticmethod
    def _preview_token_payload(parsed, baseline_batch_id, baseline_fingerprint, planned):
        return {
            "file_sha256": parsed.inspection.file_sha256,
            "parser_version": parsed.inspection.parser_version,
            "matcher_version": _MATCHER_VERSION,
            "decision_plan_version": _DECISION_PLAN_VERSION,
            "baseline_batch_id": baseline_batch_id,
            "baseline_fingerprint": baseline_fingerprint,
            "decision_plan_fingerprint": planned.plan_fingerprint,
        }

    @staticmethod
    def _issue_counts(issues, ambiguous_count: int) -> dict[str, int]:
        counts = Counter(issue.code for issue in issues)
        if ambiguous_count:
            counts["RECONCILIATION_REQUIRED"] += ambiguous_count
        return dict(counts)

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


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _amount_signature(value: Any) -> str | None:
    if value is None:
        return None
    from decimal import Decimal

    amount = Decimal(str(value))
    normalized = amount.normalize()
    return format(normalized, "f") if normalized else "0"


def _signature(values: list[Any]) -> str:
    return hashlib.sha256(_canonical_json(values).encode("utf-8")).hexdigest()


def _exact_signature(record) -> str:
    return _transaction_exact_signature(
        record.account.source_reference_fingerprint,
        record.booking_date.isoformat(),
        record.amount,
        record.currency,
        record.description,
        record.original_currency,
        record.original_amount,
    )


def _transaction_exact_signature(
    account_reference,
    booking_date,
    amount,
    currency,
    description,
    original_currency,
    original_amount,
) -> str:
    return _signature([
        account_reference,
        str(booking_date),
        _amount_signature(amount),
        currency,
        description,
        original_currency,
        _amount_signature(original_amount),
    ])


def _core_signature(record) -> str:
    return _transaction_core_signature(
        record.account.source_reference_fingerprint,
        record.booking_date.isoformat(),
        record.amount,
        record.currency,
        record.original_currency,
        record.original_amount,
    )


def _transaction_core_signature(
    account_reference, booking_date, amount, currency, original_currency, original_amount
) -> str:
    return _signature([
        account_reference,
        str(booking_date),
        _amount_signature(amount),
        currency,
        original_currency,
        _amount_signature(original_amount),
    ])


def _fuzzy_signature(record) -> str:
    return _transaction_fuzzy_signature(
        record.account.source_reference_fingerprint,
        record.booking_date.isoformat(),
        record.currency,
        record.description,
        record.original_currency,
        record.original_amount,
    )


def _transaction_fuzzy_signature(
    account_reference, booking_date, currency, description, original_currency, original_amount
) -> str:
    return _signature([
        account_reference,
        str(booking_date),
        currency,
        description,
        original_currency,
        _amount_signature(original_amount),
    ])


def _section_identity(record) -> str:
    return (
        f"{record.sheet_name}:{record.section_index}:"
        f"{record.account.source_reference_fingerprint}"
    )


# Phase 2 services remain importable from the original application-services
# module for callers that use the Phase 1 public entry point.
from family_finance.audit import AuditService
from family_finance.backup import BackupService
from family_finance.classification import (
    ClassificationEngine,
    ClassificationService,
    FinancialClassificationService,
)
from family_finance.dashboard import DashboardService
from family_finance.insights import InsightsService
from family_finance.metrics import FinancialMetricsService, MetricsEngine, MetricsService
from family_finance.net_worth import NetWorthService
from family_finance.planning import (
    DuplicateSeedError,
    PlanningPreviewStaleError,
    PlanningService,
    PlanningStaleRevisionError,
    PlanningValidationError,
    StaleRevisionError,
)

__all__ = [
    "AuditService",
    "BackupService",
    "ClassificationEngine",
    "ClassificationService",
    "DashboardService",
    "DuplicateSeedError",
    "FinancialClassificationService",
    "FinancialMetricsService",
    "ImportAmbiguityError",
    "ImportService",
    "ImportValidationError",
    "InsightsService",
    "MetricsEngine",
    "MetricsService",
    "NetWorthService",
    "PlanningPreviewStaleError",
    "PlanningService",
    "PlanningStaleRevisionError",
    "PlanningValidationError",
    "PreviewStaleError",
    "StaleRevisionError",
]


def __getattr__(name: str):
    """Lazily expose Phase 8 automation without introducing an import cycle."""
    if name in {"AutomationService", "AutomationBusyError"}:
        from family_finance.automation import AutomationBusyError, AutomationService

        return {"AutomationService": AutomationService, "AutomationBusyError": AutomationBusyError}[name]
    raise AttributeError(name)
