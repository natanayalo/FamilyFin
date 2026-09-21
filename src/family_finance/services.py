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
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO import_batches
                    (id, parser_version, baseline_batch_id, status,
                     statistics_json, error_code, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        self.settings.parser_version,
                        token.get("baseline_batch_id"),
                        ImportStatus.REJECTED.value,
                        statistics.model_dump_json(),
                        "SCHEMA_ERROR",
                        utc_now(),
                    ),
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
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO import_batches
                    (id, source_file_id, parser_version, baseline_batch_id, report_start,
                     report_end, max_transaction_date, freshness_days, status,
                     statistics_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        existing_file["id"],
                        parsed.inspection.parser_version,
                        current_baseline,
                        _iso(parsed.inspection.report_start),
                        _iso(parsed.inspection.report_end),
                        _iso(parsed.inspection.max_booking_date),
                        _freshness_days(parsed.inspection.max_booking_date),
                        ImportStatus.DUPLICATE.value,
                        stats.model_dump_json(),
                        created_at,
                    ),
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

        with self.database.transaction() as connection:
            source_file_id = self._insert_source_file(
                connection,
                parsed.inspection,
                archive_path,
                created_at,
            )
            connection.execute(
                """
                INSERT INTO import_batches
                (id, source_file_id, parser_version, baseline_batch_id, report_start,
                 report_end, max_transaction_date, freshness_days, status,
                 statistics_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    source_file_id,
                    parsed.inspection.parser_version,
                    current_baseline,
                    _iso(parsed.inspection.report_start),
                    _iso(parsed.inspection.report_end),
                    _iso(parsed.inspection.max_booking_date),
                    _freshness_days(parsed.inspection.max_booking_date),
                    ImportStatus.COMMITTED.value,
                    statistics.model_dump_json(),
                    created_at,
                ),
            )
            account_ids: dict[str, int] = {}
            for record in parsed.records:
                account_ids[record.account.source_reference_fingerprint] = self._account_id(
                    connection, record
                )
            for record in parsed.records:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO categories (movement_type, category)
                    VALUES (?, ?)
                    """,
                    (record.movement_type or "", record.category),
                )
            planned_existing_matches, claimed_existing_transaction_ids = (
                self._plan_existing_matches(
                    connection, parsed.records, account_ids
                )
            )

            for record in parsed.records:
                account_id = account_ids[record.account.source_reference_fingerprint]
                exact_key = _exact_key(record)
                core_key = _core_key(record)
                exact_rows = [
                    row
                    for row in self._find_exact(connection, record, account_id)
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
                        self._update_transaction(connection, transaction_id, record)
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
                        for row in self._find_core(connection, record, account_id)
                        if int(row["id"]) not in created_transaction_ids
                    ]
                    core_index = core_seen[core_key]
                    if len(core_rows) == 1 and core_index == 0:
                        transaction_id = int(core_rows[0]["id"])
                        core_seen[core_key] += 1
                        exact_seen[exact_key] += 1
                        self._update_transaction(connection, transaction_id, record)
                        statistics.updated += 1
                        match_method = "unique_update"
                    elif not core_rows:
                        fuzzy_rows = [
                            row
                            for row in self._find_fuzzy(connection, record, account_id)
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
                            transaction_id = self._insert_transaction(
                                connection, account_id, record, created_at
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

                source_record_id = self._insert_source_record(
                    connection,
                    batch_id=batch_id,
                    account_id=account_id,
                    record=record,
                    state=source_state,
                )
                if transaction_id is not None:
                    connection.execute(
                        """
                        INSERT INTO transaction_sources
                        (transaction_id, source_record_id, match_method, linked_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (transaction_id, source_record_id, match_method, created_at),
                    )
                else:
                    case_id = str(uuid.uuid4())
                    connection.execute(
                        """
                        INSERT INTO reconciliation_cases
                        (id, import_batch_id, source_record_id, status, reason,
                         candidate_transaction_ids_json, created_at)
                        VALUES (?, ?, ?, 'open', ?, ?, ?)
                        """,
                        (
                            case_id,
                            batch_id,
                            source_record_id,
                            "Multiple or changed candidate transactions",
                            json_dumps(candidates),
                            created_at,
                        ),
                    )

            status = (
                ImportStatus.NEEDS_REVIEW
                if statistics.unresolved
                else ImportStatus.COMMITTED
            )
            connection.execute(
                "UPDATE import_batches SET status = ?, statistics_json = ? WHERE id = ?",
                (status.value, statistics.model_dump_json(), batch_id),
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
        with self.database.transaction() as connection:
            case = connection.execute(
                "SELECT * FROM reconciliation_cases WHERE id = ? AND status = 'open'",
                (case_id,),
            ).fetchone()
            if not case:
                raise ValueError("Open reconciliation case not found")
            source = connection.execute(
                "SELECT * FROM source_records WHERE id = ?", (case["source_record_id"],)
            ).fetchone()
            if decision.resolution == "link_existing":
                if decision.transaction_id is None:
                    raise ValueError("link_existing requires transaction_id")
                candidate_ids = set(json.loads(case["candidate_transaction_ids_json"]))
                if decision.transaction_id not in candidate_ids:
                    raise ValueError("Selected transaction is not a case candidate")
                transaction_id = decision.transaction_id
                method = "reconciliation"
                self._update_transaction_from_source(connection, transaction_id, source, now)
            elif decision.resolution == "accept_as_new":
                transaction_id = self._insert_transaction_from_source(
                    connection, source, now
                )
                method = "inserted"
            elif decision.resolution == "dismiss":
                connection.execute(
                    """
                    UPDATE reconciliation_cases
                    SET status = 'dismissed', resolution_json = ?, resolved_at = ?
                    WHERE id = ?
                    """,
                    (json_dumps(decision.model_dump()), now, case_id),
                )
                connection.execute(
                    "UPDATE source_records SET validation_state = 'dismissed' WHERE id = ?",
                    (source["id"],),
                )
                status, statistics = self._refresh_batch_status(
                    connection, case["import_batch_id"]
                )
                return ImportResult(
                    batch_id=case["import_batch_id"],
                    status=status,
                    statistics=statistics,
                )
            else:
                raise ValueError("resolution must be link_existing, accept_as_new, or dismiss")

            connection.execute(
                """
                INSERT INTO transaction_sources
                (transaction_id, source_record_id, match_method, linked_at)
                VALUES (?, ?, ?, ?)
                """,
                (transaction_id, source["id"], method, now),
            )
            connection.execute(
                "UPDATE source_records SET validation_state = 'accepted' WHERE id = ?",
                (source["id"],),
            )
            connection.execute(
                """
                UPDATE reconciliation_cases
                SET status = 'resolved', resolution_json = ?, resolved_at = ?
                WHERE id = ?
                """,
                (json_dumps(decision.model_dump()), now, case_id),
            )
            status, statistics = self._refresh_batch_status(
                connection, case["import_batch_id"]
            )
        return ImportResult(
            batch_id=case["import_batch_id"],
            status=status,
            statistics=statistics,
        )

    def history(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, parser_version, report_start, report_end, max_transaction_date,
                       freshness_days, status, statistics_json, created_at
                FROM import_batches ORDER BY created_at DESC
                """
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["statistics"] = json.loads(item.pop("statistics_json"))
            result.append(item)
        return result

    def reconciliation_cases(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            case_rows = connection.execute(
                """
                SELECT id, import_batch_id, source_record_id, reason,
                       candidate_transaction_ids_json, created_at
                FROM reconciliation_cases
                WHERE status = 'open'
                ORDER BY created_at
                """
            ).fetchall()
            result: list[dict[str, Any]] = []
            for case in case_rows:
                source_row = connection.execute(
                    "SELECT normalized_json FROM source_records WHERE id = ?",
                    (case["source_record_id"],),
                ).fetchone()
                candidate_ids = json.loads(case["candidate_transaction_ids_json"])
                candidates: list[dict[str, Any]] = []
                if candidate_ids:
                    placeholders = ",".join("?" for _ in candidate_ids)
                    candidates = [
                        dict(row)
                        for row in connection.execute(
                            f"""
                            SELECT t.id, t.booking_date, t.allocation_date, t.amount,
                                   t.currency, t.original_currency, t.original_amount,
                                   t.description, t.movement_type, t.category,
                                   a.display_label AS account
                            FROM transactions AS t
                            JOIN accounts AS a ON a.id = t.account_id
                            WHERE t.id IN ({placeholders})
                            ORDER BY t.id
                            """,
                            candidate_ids,
                        ).fetchall()
                    ]
                result.append(
                    {
                        "id": case["id"],
                        "import_batch_id": case["import_batch_id"],
                        "source_record_id": case["source_record_id"],
                        "reason": case["reason"],
                        "created_at": case["created_at"],
                        "source": (
                            json.loads(source_row["normalized_json"]) if source_row else {}
                        ),
                        "candidates": candidates,
                    }
                )
        return result

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
                for row in ImportService._find_exact(connection, record, account_id)
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
                for row in ImportService._find_core(connection, record, account_id)
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
                all_core_rows = ImportService._find_core(connection, record, account_id)
                if all_core_rows:
                    planned[source_key] = (
                        "ambiguous",
                        [int(row["id"]) for row in all_core_rows],
                    )
        return planned, claimed

    @staticmethod
    def _insert_source_file(
        connection,
        inspection,
        archive_path: Path,
        created_at: str,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO source_files
            (sha256, original_filename, archived_path, compressed_bytes,
             uncompressed_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                inspection.file_sha256,
                inspection.filename,
                str(archive_path),
                inspection.compressed_bytes,
                inspection.uncompressed_bytes,
                created_at,
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _account_id(connection, record) -> int:
        fingerprint = record.account.source_reference_fingerprint
        row = connection.execute(
            "SELECT id FROM accounts WHERE source_reference_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row:
            return int(row["id"])
        cursor = connection.execute(
            """
            INSERT INTO accounts
            (provider, account_kind, source_reference_fingerprint, display_label, currency)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                record.account.provider,
                record.account.kind,
                fingerprint,
                record.account.display_label,
                record.account.currency,
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _insert_source_record(connection, *, batch_id, account_id, record, state) -> int:
        normalized = {
            "booking_date": record.booking_date.isoformat(),
            "allocation_date": record.allocation_date.isoformat(),
            "amount": str(record.amount),
            "currency": record.currency,
            "original_currency": record.original_currency,
            "original_amount": (
                str(record.original_amount) if record.original_amount is not None else None
            ),
            "description": record.description,
            "movement_type": record.movement_type,
            "category": record.category,
        }
        cursor = connection.execute(
            """
            INSERT INTO source_records
            (import_batch_id, account_id, sheet_name, section_index, source_row_number,
             raw_payload_json, normalized_json, row_fingerprint, validation_state,
             issues_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                account_id,
                record.sheet_name,
                record.section_index,
                record.source_row_number,
                json_dumps(record.raw_payload),
                json_dumps(normalized),
                record.row_fingerprint,
                state,
                json_dumps([issue.model_dump() for issue in record.issues]),
                utc_now(),
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _insert_transaction(connection, account_id, record, now: str) -> int:
        cursor = connection.execute(
            """
            INSERT INTO transactions
            (account_id, booking_date, allocation_date, amount, currency,
             original_currency, original_amount, description, movement_type,
             category, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                record.booking_date.isoformat(),
                record.allocation_date.isoformat(),
                str(record.amount),
                record.currency,
                record.original_currency,
                str(record.original_amount) if record.original_amount is not None else None,
                record.description,
                record.movement_type,
                record.category,
                now,
                now,
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _update_transaction(connection, transaction_id: int, record) -> None:
        connection.execute(
            """
            UPDATE transactions
            SET booking_date = ?, allocation_date = ?, amount = ?, currency = ?,
                original_currency = ?, original_amount = ?, description = ?,
                movement_type = ?, category = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                record.booking_date.isoformat(),
                record.allocation_date.isoformat(),
                str(record.amount),
                record.currency,
                record.original_currency,
                str(record.original_amount) if record.original_amount is not None else None,
                record.description,
                record.movement_type,
                record.category,
                utc_now(),
                transaction_id,
            ),
        )

    @staticmethod
    def _insert_transaction_from_source(connection, source, now: str) -> int:
        normalized = json.loads(source["normalized_json"])
        cursor = connection.execute(
            """
            INSERT INTO transactions
            (account_id, booking_date, allocation_date, amount, currency,
             original_currency, original_amount, description, movement_type,
             category, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source["account_id"],
                normalized["booking_date"],
                normalized["allocation_date"],
                normalized["amount"],
                normalized["currency"],
                normalized["original_currency"],
                normalized["original_amount"],
                normalized["description"],
                normalized["movement_type"],
                normalized["category"],
                now,
                now,
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _update_transaction_from_source(connection, transaction_id: int, source, now: str) -> None:
        normalized = json.loads(source["normalized_json"])
        connection.execute(
            """
            UPDATE transactions
            SET booking_date = ?, allocation_date = ?, amount = ?, currency = ?,
                original_currency = ?, original_amount = ?, description = ?,
                movement_type = ?, category = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                normalized["booking_date"],
                normalized["allocation_date"],
                normalized["amount"],
                normalized["currency"],
                normalized["original_currency"],
                normalized["original_amount"],
                normalized["description"],
                normalized["movement_type"],
                normalized["category"],
                now,
                transaction_id,
            ),
        )

    @staticmethod
    def _refresh_batch_status(
        connection, batch_id: str
    ) -> tuple[ImportStatus, ImportStatistics]:
        open_cases = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM reconciliation_cases
            WHERE import_batch_id = ? AND status = 'open'
            """,
            (batch_id,),
        ).fetchone()["count"]
        case_count = connection.execute(
            "SELECT COUNT(*) AS count FROM reconciliation_cases WHERE import_batch_id = ?",
            (batch_id,),
        ).fetchone()["count"]
        source_rows = connection.execute(
            """
            SELECT ts.match_method, sr.validation_state
            FROM source_records AS sr
            LEFT JOIN transaction_sources AS ts ON ts.source_record_id = sr.id
            WHERE sr.import_batch_id = ?
            """,
            (batch_id,),
        ).fetchall()
        prior = connection.execute(
            "SELECT statistics_json FROM import_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        prior_statistics = json.loads(prior["statistics_json"]) if prior else {}
        statistics = ImportStatistics(
            total_records=len(source_rows),
            inserted=sum(row["match_method"] == "inserted" for row in source_rows),
            unchanged=sum(
                row["match_method"] == "exact_unchanged" for row in source_rows
            ),
            updated=sum(
                row["match_method"] in {"unique_update", "reconciliation"}
                for row in source_rows
            ),
            rejected=sum(
                row["validation_state"] in {"dismissed", "rejected"} for row in source_rows
            ),
            ambiguous=int(case_count),
            unresolved=int(open_cases),
            duplicate_file=bool(prior_statistics.get("duplicate_file", False)),
            non_ils_records=int(prior_statistics.get("non_ils_records", 0)),
        )
        status = ImportStatus.NEEDS_REVIEW if open_cases else ImportStatus.COMMITTED
        connection.execute(
            "UPDATE import_batches SET status = ?, statistics_json = ? WHERE id = ?",
            (status.value, statistics.model_dump_json(), batch_id),
        )
        return status, statistics

    @staticmethod
    def _find_exact(connection, record, account_id):
        return connection.execute(
            """
            SELECT * FROM transactions
            WHERE account_id = ? AND booking_date = ? AND amount = ? AND currency = ?
              AND description = ? AND (original_currency IS ? OR original_currency = ?)
              AND (original_amount IS ? OR original_amount = ?)
            ORDER BY id
            """,
            (
                account_id,
                record.booking_date.isoformat(),
                str(record.amount),
                record.currency,
                record.description,
                record.original_currency,
                record.original_currency,
                str(record.original_amount) if record.original_amount is not None else None,
                str(record.original_amount) if record.original_amount is not None else None,
            ),
        ).fetchall()

    @staticmethod
    def _find_core(connection, record, account_id):
        return connection.execute(
            """
            SELECT * FROM transactions
            WHERE account_id = ? AND booking_date = ? AND amount = ? AND currency = ?
              AND (original_currency IS ? OR original_currency = ?)
              AND (original_amount IS ? OR original_amount = ?)
            ORDER BY id
            """,
            (
                account_id,
                record.booking_date.isoformat(),
                str(record.amount),
                record.currency,
                record.original_currency,
                record.original_currency,
                str(record.original_amount) if record.original_amount is not None else None,
                str(record.original_amount) if record.original_amount is not None else None,
            ),
        ).fetchall()

    @staticmethod
    def _find_fuzzy(connection, record, account_id):
        """Find a likely changed row without guessing its replacement."""
        return connection.execute(
            """
            SELECT * FROM transactions
            WHERE account_id = ? AND description = ? AND currency = ?
              AND (original_currency IS ? OR original_currency = ?)
            ORDER BY id
            """,
            (
                account_id,
                record.description,
                record.currency,
                record.original_currency,
                record.original_currency,
            ),
        ).fetchall()


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
