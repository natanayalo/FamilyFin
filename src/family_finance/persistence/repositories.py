"""SQLAlchemy repository read models and append-only analysis writes."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, desc, select
from sqlalchemy.orm import Session

from family_finance.models import ClassificationRule
from family_finance.persistence.db import Database, utc_now
from family_finance.persistence.models import (
    AccountRow,
    AnalysisOverrideRow,
    CategoryRow,
    ClassificationRuleRow,
    ImportBatchRow,
    ReconciliationCaseRow,
    SourceFileRow,
    SourceRecordRow,
    TransactionRow,
    TransactionSourceRow,
)


def _model_dict(model: Any) -> dict[str, Any]:
    return {column.key: getattr(model, column.key) for column in model.__table__.columns}


def _transaction_dict(transaction: TransactionRow, account: AccountRow) -> dict[str, Any]:
    result = _model_dict(transaction)
    result.update(
        {
            "account_kind": account.account_kind,
            "account_label": account.display_label,
            "provider": account.provider,
            "source_reference_fingerprint": account.source_reference_fingerprint,
        }
    )
    return _decimalize(result)


def _decimalize(row: dict[str, Any]) -> dict[str, Any]:
    for field in ("amount", "original_amount"):
        if row.get(field) is not None:
            row[field] = Decimal(str(row[field]))
    return row


class FinancialRepository:
    """Repository backed by SQLAlchemy 2.0 sessions and declarative rows."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def transaction(self, transaction_id: int) -> dict[str, Any] | None:
        statement = (
            select(TransactionRow, AccountRow)
            .join(AccountRow, AccountRow.id == TransactionRow.account_id)
            .where(TransactionRow.id == transaction_id)
        )
        with self.database.session() as session:
            row = session.execute(statement).first()
        return _transaction_dict(*row) if row else None

    def accepted_transactions(
        self,
        *,
        currency: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[dict[str, Any]]:
        accepted_source_transactions = (
            select(TransactionSourceRow.transaction_id)
            .join(
                SourceRecordRow,
                SourceRecordRow.id == TransactionSourceRow.source_record_id,
            )
            .where(SourceRecordRow.validation_state == "accepted")
        )
        conditions = [TransactionRow.id.in_(accepted_source_transactions)]
        if currency is not None:
            conditions.append(TransactionRow.currency.ilike(currency))
        if start is not None:
            conditions.append(TransactionRow.booking_date >= start.isoformat())
        if end is not None:
            conditions.append(TransactionRow.booking_date < end.isoformat())
        statement = (
            select(TransactionRow, AccountRow)
            .join(AccountRow, AccountRow.id == TransactionRow.account_id)
            .where(and_(*conditions))
            .order_by(TransactionRow.booking_date, TransactionRow.id)
        )
        with self.database.session() as session:
            rows = session.execute(statement).all()
        return [_transaction_dict(transaction, account) for transaction, account in rows]

    def source_info(self, transaction_id: int) -> dict[str, Any]:
        statement = (
            select(SourceRecordRow)
            .join(
                TransactionSourceRow,
                TransactionSourceRow.source_record_id == SourceRecordRow.id,
            )
            .where(TransactionSourceRow.transaction_id == transaction_id)
            .order_by(desc(TransactionSourceRow.linked_at), desc(SourceRecordRow.id))
            .limit(1)
        )
        with self.database.session() as session:
            source = session.execute(statement).scalar_one_or_none()
        if not source:
            return {}
        result = {
            "sheet_name": source.sheet_name,
            "section_index": source.section_index,
            "source_row_number": source.source_row_number,
            "validation_state": source.validation_state,
            "normalized": json.loads(source.normalized_json),
            "raw_payload": json.loads(source.raw_payload_json),
            "issues": json.loads(source.issues_json),
        }
        return result

    def latest_overrides(self, transaction_id: int) -> list[dict[str, Any]]:
        statement = (
            select(AnalysisOverrideRow)
            .where(AnalysisOverrideRow.transaction_id == transaction_id)
            .order_by(desc(AnalysisOverrideRow.id))
        )
        with self.database.session() as session:
            rows = session.execute(statement).scalars().all()
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = _model_dict(row)
            latest.setdefault(item["field_name"], item)
        return list(latest.values())

    def append_overrides(
        self,
        transaction_id: int,
        values: dict[str, str | None],
        reason: str,
    ) -> list[int]:
        now = utc_now()
        ids: list[int] = []
        with self.database.write_session() as session:
            exists = session.get(TransactionRow, transaction_id)
            if not exists:
                raise ValueError(f"Transaction {transaction_id} not found")
            for field_name, value in values.items():
                row = AnalysisOverrideRow(
                    transaction_id=transaction_id,
                    field_name=field_name,
                    value=value,
                    reason=reason,
                    created_at=now,
                )
                session.add(row)
                session.flush()
                ids.append(int(row.id))
        return ids

    @staticmethod
    def _rule_statement(
        *,
        account_kind: str,
        direction: str,
        source_category: str,
        source_movement_type: str,
        currency: str,
    ) -> Select:
        return (
            select(ClassificationRuleRow)
            .where(
                and_(
                    ClassificationRuleRow.account_kind.ilike(account_kind),
                    ClassificationRuleRow.direction == direction,
                    ClassificationRuleRow.source_category == source_category,
                    ClassificationRuleRow.source_movement_type == source_movement_type,
                    ClassificationRuleRow.currency.ilike(currency),
                )
            )
            .order_by(desc(ClassificationRuleRow.revision), desc(ClassificationRuleRow.id))
            .limit(1)
        )

    def _latest_rule_row(
        self,
        *,
        account_kind: str,
        direction: str,
        source_category: str,
        source_movement_type: str,
        currency: str,
    ) -> dict[str, Any] | None:
        statement = self._rule_statement(
            account_kind=account_kind,
            direction=direction,
            source_category=source_category,
            source_movement_type=source_movement_type,
            currency=currency,
        )
        with self.database.session() as session:
            row = session.execute(statement).scalar_one_or_none()
        return _model_dict(row) if row else None

    def latest_rule(self, **key: str) -> dict[str, Any] | None:
        return self._latest_rule_row(**key)

    def save_rule(self, rule: ClassificationRule) -> ClassificationRule:
        now = utc_now()
        source_movement_type = rule.source_movement_type or ""
        with self.database.write_session() as session:
            previous = session.execute(
                self._rule_statement(
                    account_kind=rule.account_kind,
                    direction=rule.direction,
                    source_category=rule.source_category,
                    source_movement_type=source_movement_type,
                    currency=rule.currency,
                )
            ).scalar_one_or_none()
            revision = int(previous.revision) + 1 if previous else max(rule.revision, 1)
            row = ClassificationRuleRow(
                account_kind=rule.account_kind,
                direction=rule.direction,
                source_category=rule.source_category,
                source_movement_type=source_movement_type,
                currency=rule.currency,
                economic_class=rule.economic_class.value,
                analysis_category=rule.analysis_category,
                expense_behavior=rule.expense_behavior.value,
                is_active=bool(rule.active and not rule.tombstone),
                is_tombstone=bool(rule.tombstone),
                revision=revision,
                supersedes_rule_id=previous.id if previous else rule.supersedes_rule_id,
                reason=rule.reason,
                created_at=now,
            )
            session.add(row)
            session.flush()
            rule_id = int(row.id)
            supersedes = previous.id if previous else rule.supersedes_rule_id
        return rule.model_copy(
            update={
                "id": rule_id,
                "revision": revision,
                "supersedes_rule_id": supersedes,
                "created_at": now,
                "source_movement_type": source_movement_type,
                "active": rule.active and not rule.tombstone,
            }
        )

    def all_rules(self) -> list[dict[str, Any]]:
        with self.database.session() as session:
            rows = session.execute(
                select(ClassificationRuleRow).order_by(
                    ClassificationRuleRow.created_at, ClassificationRuleRow.id
                )
            ).scalars().all()
        result = [_model_dict(row) for row in rows]
        latest_by_key: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        for row in result:
            key = self._rule_key(row)
            current = latest_by_key.get(key)
            if current is None or (row["revision"], row["id"]) > (
                current["revision"],
                current["id"],
            ):
                latest_by_key[key] = row
        for row in result:
            row["is_current"] = latest_by_key[self._rule_key(row)]["id"] == row["id"]
            row["effective_active"] = bool(
                row["is_current"] and row["is_active"] and not row["is_tombstone"]
            )
        return result

    @staticmethod
    def _rule_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
        return (
            str(row["account_kind"]).casefold(),
            str(row["direction"]),
            str(row["source_category"]),
            str(row["source_movement_type"] or ""),
            str(row["currency"]).upper(),
        )

    def latest_batch(self) -> dict[str, Any] | None:
        statement = (
            select(ImportBatchRow)
            .where(ImportBatchRow.status.in_(("committed", "needs_review")))
            .order_by(desc(ImportBatchRow.created_at))
            .limit(1)
        )
        with self.database.session() as session:
            row = session.execute(statement).scalar_one_or_none()
        return _model_dict(row) if row else None

    def batches_covering(self, start: date, end: date) -> list[dict[str, Any]]:
        statement = (
            select(ImportBatchRow)
            .where(
                and_(
                    ImportBatchRow.status.in_(("committed", "needs_review")),
                    ImportBatchRow.report_start.is_not(None),
                    ImportBatchRow.report_end.is_not(None),
                    ImportBatchRow.report_start <= start.isoformat(),
                    ImportBatchRow.report_end >= end.isoformat(),
                )
            )
            .order_by(desc(ImportBatchRow.created_at))
        )
        with self.database.session() as session:
            rows = session.execute(statement).scalars().all()
        return [_model_dict(row) for row in rows]

    def open_cases_in_period(self, start: date, end: date) -> list[dict[str, Any]]:
        statement = (
            select(ReconciliationCaseRow, SourceRecordRow)
            .join(
                SourceRecordRow,
                SourceRecordRow.id == ReconciliationCaseRow.source_record_id,
            )
            .where(ReconciliationCaseRow.status == "open")
        )
        with self.database.session() as session:
            rows = session.execute(statement).all()
        result = []
        for case, source in rows:
            normalized = json.loads(source.normalized_json)
            booking = date.fromisoformat(normalized["booking_date"])
            if start <= booking < end:
                item = _model_dict(case)
                item["normalized"] = normalized
                result.append(item)
        return result

    def all_accepted_booking_dates(self) -> list[date]:
        rows = self.accepted_transactions()
        return [date.fromisoformat(row["booking_date"]) for row in rows]

    def contributor_rows(self, transaction_ids: Iterable[int]) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(int(item) for item in transaction_ids))
        if not ids:
            return []
        statement = (
            select(TransactionRow, AccountRow)
            .join(AccountRow, AccountRow.id == TransactionRow.account_id)
            .where(TransactionRow.id.in_(ids))
            .order_by(TransactionRow.booking_date, TransactionRow.id)
        )
        with self.database.session() as session:
            rows = session.execute(statement).all()
        result = []
        for transaction, account in rows:
            item = _model_dict(transaction)
            item.update(
                {
                    "account_kind": account.account_kind,
                    "account_label": account.display_label,
                    "provider": account.provider,
                }
            )
            result.append(_decimalize(item))
        return result


ClassificationRepository = FinancialRepository


class ImportRepository:
    """SQLAlchemy repository for import and reconciliation persistence."""

    @staticmethod
    def insert_batch(session: Session, **values: Any) -> ImportBatchRow:
        row = ImportBatchRow(**values)
        session.add(row)
        session.flush()
        return row

    @staticmethod
    def update_batch(
        session: Session, batch_id: str, status: str, statistics_json: str
    ) -> None:
        row = session.get(ImportBatchRow, batch_id)
        if row is None:
            raise ValueError(f"Import batch {batch_id} not found")
        row.status = status
        row.statistics_json = statistics_json
        session.flush()

    @staticmethod
    def insert_source_file(session: Session, **values: Any) -> SourceFileRow:
        row = SourceFileRow(**values)
        session.add(row)
        session.flush()
        return row

    @staticmethod
    def account_id(session: Session, record: Any) -> int:
        fingerprint = record.account.source_reference_fingerprint
        account_id = session.execute(
            select(AccountRow.id).where(
                AccountRow.source_reference_fingerprint == fingerprint
            )
        ).scalar_one_or_none()
        if account_id is not None:
            return int(account_id)
        row = AccountRow(
            provider=record.account.provider,
            account_kind=record.account.kind,
            source_reference_fingerprint=fingerprint,
            display_label=record.account.display_label,
            currency=record.account.currency,
        )
        session.add(row)
        session.flush()
        return int(row.id)

    @staticmethod
    def ensure_category(session: Session, record: Any) -> None:
        movement_type = record.movement_type or ""
        existing = session.execute(
            select(CategoryRow.id).where(
                CategoryRow.movement_type == movement_type,
                CategoryRow.category == record.category,
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(CategoryRow(movement_type=movement_type, category=record.category))
            session.flush()

    @staticmethod
    def _nullable_match(column: Any, value: Any):
        return column.is_(value) if value is None else column == value

    @classmethod
    def _find_transactions(
        cls,
        session: Session,
        record: Any,
        account_id: int,
        *,
        include_description: bool,
        include_amount: bool,
    ) -> list[dict[str, Any]]:
        conditions = [
            TransactionRow.account_id == account_id,
            TransactionRow.currency == record.currency,
            cls._nullable_match(TransactionRow.original_currency, record.original_currency),
        ]
        if include_amount:
            conditions.extend(
                [
                    TransactionRow.booking_date == record.booking_date.isoformat(),
                    TransactionRow.amount == str(record.amount),
                    cls._nullable_match(
                        TransactionRow.original_amount,
                        (
                            str(record.original_amount)
                            if record.original_amount is not None
                            else None
                        ),
                    ),
                ]
            )
        if include_description:
            conditions.append(TransactionRow.description == record.description)
        rows = session.execute(
            select(TransactionRow).where(and_(*conditions)).order_by(TransactionRow.id)
        ).scalars()
        return [_model_dict(row) for row in rows]

    @classmethod
    def find_exact(cls, session: Session, record: Any, account_id: int):
        return cls._find_transactions(
            session,
            record,
            account_id,
            include_description=True,
            include_amount=True,
        )

    @classmethod
    def find_core(cls, session: Session, record: Any, account_id: int):
        return cls._find_transactions(
            session,
            record,
            account_id,
            include_description=False,
            include_amount=True,
        )

    @classmethod
    def find_fuzzy(cls, session: Session, record: Any, account_id: int):
        return cls._find_transactions(
            session,
            record,
            account_id,
            include_description=True,
            include_amount=False,
        )

    @staticmethod
    def insert_source_record(
        session: Session, *, batch_id: str, account_id: int, record: Any, state: str
    ) -> int:
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
        row = SourceRecordRow(
            import_batch_id=batch_id,
            account_id=account_id,
            sheet_name=record.sheet_name,
            section_index=record.section_index,
            source_row_number=record.source_row_number,
            raw_payload_json=json.dumps(
                record.raw_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            normalized_json=json.dumps(
                normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            row_fingerprint=record.row_fingerprint,
            validation_state=state,
            issues_json=json.dumps(
                [issue.model_dump() for issue in record.issues],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            created_at=utc_now(),
        )
        session.add(row)
        session.flush()
        return int(row.id)

    @staticmethod
    def insert_transaction(session: Session, *, account_id: int, record: Any, now: str) -> int:
        row = TransactionRow(
            account_id=account_id,
            booking_date=record.booking_date.isoformat(),
            allocation_date=record.allocation_date.isoformat(),
            amount=str(record.amount),
            currency=record.currency,
            original_currency=record.original_currency,
            original_amount=(
                str(record.original_amount) if record.original_amount is not None else None
            ),
            description=record.description,
            movement_type=record.movement_type,
            category=record.category,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return int(row.id)

    @staticmethod
    def update_transaction(session: Session, transaction_id: int, record: Any, now: str) -> None:
        row = session.get(TransactionRow, transaction_id)
        if row is None:
            raise ValueError(f"Transaction {transaction_id} not found")
        row.booking_date = record.booking_date.isoformat()
        row.allocation_date = record.allocation_date.isoformat()
        row.amount = str(record.amount)
        row.currency = record.currency
        row.original_currency = record.original_currency
        row.original_amount = (
            str(record.original_amount) if record.original_amount is not None else None
        )
        row.description = record.description
        row.movement_type = record.movement_type
        row.category = record.category
        row.updated_at = now
        session.flush()

    @staticmethod
    def link_transaction(
        session: Session,
        *,
        transaction_id: int,
        source_record_id: int,
        match_method: str,
        linked_at: str,
    ) -> None:
        session.add(
            TransactionSourceRow(
                transaction_id=transaction_id,
                source_record_id=source_record_id,
                match_method=match_method,
                linked_at=linked_at,
            )
        )
        session.flush()

    @staticmethod
    def insert_reconciliation_case(
        session: Session,
        *,
        case_id: str,
        batch_id: str,
        source_record_id: int,
        reason: str,
        candidate_transaction_ids_json: str,
        created_at: str,
    ) -> None:
        session.add(
            ReconciliationCaseRow(
                id=case_id,
                import_batch_id=batch_id,
                source_record_id=source_record_id,
                status="open",
                reason=reason,
                candidate_transaction_ids_json=candidate_transaction_ids_json,
                created_at=created_at,
            )
        )
        session.flush()

    @staticmethod
    def open_case(session: Session, case_id: str) -> dict[str, Any] | None:
        row = session.execute(
            select(ReconciliationCaseRow).where(
                ReconciliationCaseRow.id == case_id,
                ReconciliationCaseRow.status == "open",
            )
        ).scalar_one_or_none()
        return _model_dict(row) if row else None

    @staticmethod
    def source_record(session: Session, source_record_id: int) -> dict[str, Any] | None:
        row = session.get(SourceRecordRow, source_record_id)
        return _model_dict(row) if row else None

    @staticmethod
    def transaction_from_source(
        session: Session, source: dict[str, Any], now: str
    ) -> int:
        normalized = json.loads(source["normalized_json"])
        row = TransactionRow(
            account_id=source["account_id"],
            booking_date=normalized["booking_date"],
            allocation_date=normalized["allocation_date"],
            amount=normalized["amount"],
            currency=normalized["currency"],
            original_currency=normalized["original_currency"],
            original_amount=normalized["original_amount"],
            description=normalized["description"],
            movement_type=normalized["movement_type"],
            category=normalized["category"],
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return int(row.id)

    @staticmethod
    def update_transaction_from_source(
        session: Session, transaction_id: int, source: dict[str, Any], now: str
    ) -> None:
        normalized = json.loads(source["normalized_json"])
        row = session.get(TransactionRow, transaction_id)
        if row is None:
            raise ValueError(f"Transaction {transaction_id} not found")
        for field in (
            "booking_date",
            "allocation_date",
            "amount",
            "currency",
            "original_currency",
            "original_amount",
            "description",
            "movement_type",
            "category",
        ):
            setattr(row, field, normalized[field])
        row.updated_at = now
        session.flush()

    @staticmethod
    def mark_source_state(session: Session, source_record_id: int, state: str) -> None:
        row = session.get(SourceRecordRow, source_record_id)
        if row is None:
            raise ValueError(f"Source record {source_record_id} not found")
        row.validation_state = state
        session.flush()

    @staticmethod
    def update_case(
        session: Session,
        case_id: str,
        *,
        status: str,
        resolution_json: str,
        resolved_at: str,
    ) -> None:
        row = session.get(ReconciliationCaseRow, case_id)
        if row is None:
            raise ValueError(f"Reconciliation case {case_id} not found")
        row.status = status
        row.resolution_json = resolution_json
        row.resolved_at = resolved_at
        session.flush()

    @staticmethod
    def refresh_batch_status(
        session: Session, batch_id: str
    ) -> tuple[str, dict[str, Any]]:
        cases = session.execute(
            select(ReconciliationCaseRow).where(
                ReconciliationCaseRow.import_batch_id == batch_id
            )
        ).scalars().all()
        source_rows = session.execute(
            select(TransactionSourceRow.match_method, SourceRecordRow.validation_state)
            .select_from(SourceRecordRow)
            .join(
                TransactionSourceRow,
                TransactionSourceRow.source_record_id == SourceRecordRow.id,
                isouter=True,
            )
            .where(SourceRecordRow.import_batch_id == batch_id)
        ).all()
        prior = session.get(ImportBatchRow, batch_id)
        prior_statistics = json.loads(prior.statistics_json) if prior else {}
        open_cases = sum(case.status == "open" for case in cases)
        statistics = {
            "total_records": len(source_rows),
            "inserted": sum(item.match_method == "inserted" for item in source_rows),
            "unchanged": sum(
                item.match_method == "exact_unchanged" for item in source_rows
            ),
            "updated": sum(
                item.match_method in {"unique_update", "reconciliation"}
                for item in source_rows
            ),
            "rejected": sum(
                item.validation_state in {"dismissed", "rejected"}
                for item in source_rows
            ),
            "ambiguous": len(cases),
            "unresolved": open_cases,
            "duplicate_file": bool(prior_statistics.get("duplicate_file", False)),
            "non_ils_records": int(prior_statistics.get("non_ils_records", 0)),
        }
        if prior:
            prior.status = "needs_review" if open_cases else "committed"
            prior.statistics_json = json.dumps(
                statistics, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            session.flush()
        return ("needs_review" if open_cases else "committed"), statistics

    @staticmethod
    def history(session: Session) -> list[dict[str, Any]]:
        rows = session.execute(
            select(ImportBatchRow).order_by(desc(ImportBatchRow.created_at))
        ).scalars().all()
        return [_model_dict(row) for row in rows]

    @staticmethod
    def open_reconciliation_cases(session: Session) -> list[dict[str, Any]]:
        rows = session.execute(
            select(ReconciliationCaseRow)
            .where(ReconciliationCaseRow.status == "open")
            .order_by(ReconciliationCaseRow.created_at)
        ).scalars().all()
        result = []
        for case in rows:
            source = session.get(SourceRecordRow, case.source_record_id)
            candidate_ids = json.loads(case.candidate_transaction_ids_json)
            candidates = []
            if candidate_ids:
                candidate_rows = session.execute(
                    select(TransactionRow, AccountRow)
                    .join(AccountRow, AccountRow.id == TransactionRow.account_id)
                    .where(TransactionRow.id.in_(candidate_ids))
                    .order_by(TransactionRow.id)
                ).all()
                for transaction, account in candidate_rows:
                    item = _model_dict(transaction)
                    item["account"] = account.display_label
                    candidates.append(item)
            result.append(
                {
                    "id": case.id,
                    "import_batch_id": case.import_batch_id,
                    "source_record_id": case.source_record_id,
                    "reason": case.reason,
                    "created_at": case.created_at,
                    "source": json.loads(source.normalized_json) if source else {},
                    "candidates": candidates,
                }
            )
        return result


__all__ = ["ClassificationRepository", "FinancialRepository", "ImportRepository"]
