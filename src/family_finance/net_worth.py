"""Account-level, ILS-only household net-worth ledger.

This module intentionally keeps observed balances separate from transactions,
planning assumptions, and forecast projections.  Every saved revision carries
the account metadata that was true when it was captured, so registry edits do
not rewrite history.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import desc, select

from family_finance.config import Settings
from family_finance.models import (
    ForecastActualComparison,
    ForecastPoolSeed,
    ForecastPoolType,
    NetWorthAccount,
    NetWorthAccountInput,
    NetWorthBalance,
    NetWorthBalanceInput,
    NetWorthCategory,
    NetWorthLiquidity,
    NetWorthOrigin,
    NetWorthSide,
    NetWorthSnapshotRevision,
    NetWorthSnapshotSummary,
    NetWorthSummary,
    NetWorthTrendPoint,
)
from family_finance.persistence.db import Database, json_dumps, utc_now
from family_finance.persistence.models import (
    NetWorthAccountRow,
    NetWorthBalanceRow,
    NetWorthImportRow,
    NetWorthSnapshotRevisionRow,
    NetWorthSnapshotRow,
    NetWorthSourceFileRow,
)

CSV_HEADERS = (
    "snapshot_date",
    "account_key",
    "account_name",
    "side",
    "category",
    "liquidity",
    "owner",
    "amount_ils",
    "valuation_date",
    "notes",
)


class NetWorthValidationError(ValueError):
    """A balance, registry, or workflow invariant failed."""


class DuplicateNetWorthAccountError(NetWorthValidationError):
    """The requested account key is already in use."""


class NetWorthPreviewStaleError(NetWorthValidationError):
    """The registry or uploaded bytes changed after CSV preview."""


class StaleNetWorthRevisionError(NetWorthValidationError):
    """Optimistic concurrency rejected a revision write."""


class ExistingSnapshotRevisionError(NetWorthValidationError):
    """A different CSV was submitted for an existing snapshot date."""


class DuplicateNetWorthImportError(NetWorthValidationError):
    """A source file was already committed."""


class NetWorthCsvPreview:
    """Small typed preview object kept dependency-free for Streamlit callers."""

    def __init__(
        self,
        *,
        preview_token: str,
        file_sha256: str,
        snapshot_date: date | None,
        filename: str | None,
        row_count: int,
        rows: list[dict[str, Any]],
        issues: list[str],
        warnings: list[str],
        duplicate_file: bool,
        existing_snapshot_id: str | None,
        existing_revision_id: str | None,
        registry_hash: str,
    ) -> None:
        self.preview_token = preview_token
        self.file_sha256 = file_sha256
        self.snapshot_date = snapshot_date
        self.filename = filename
        self.row_count = row_count
        self.rows = rows
        self.issues = issues
        self.warnings = warnings
        self.duplicate_file = duplicate_file
        self.existing_snapshot_id = existing_snapshot_id
        self.existing_revision_id = existing_revision_id
        self.registry_hash = registry_hash

    @property
    def valid(self) -> bool:
        return not self.issues

    @property
    def can_commit(self) -> bool:
        return self.valid

    def model_dump(self, *, mode: str = "python") -> dict[str, Any]:
        serialized_rows = [
            {
                key: (
                    value.isoformat()
                    if isinstance(value, date)
                    else str(value)
                    if isinstance(value, Decimal)
                    else value
                )
                for key, value in row.items()
            }
            for row in self.rows
        ]
        return {
            "preview_token": self.preview_token,
            "file_sha256": self.file_sha256,
            "snapshot_date": self.snapshot_date.isoformat() if self.snapshot_date else None,
            "filename": self.filename,
            "row_count": self.row_count,
            "rows": serialized_rows,
            "issues": self.issues,
            "warnings": self.warnings,
            "duplicate_file": self.duplicate_file,
            "existing_snapshot_id": self.existing_snapshot_id,
            "existing_revision_id": self.existing_revision_id,
            "registry_hash": self.registry_hash,
            "valid": self.valid,
        }


class NetWorthService:
    """Persistence, validation, CSV, aggregation, and forecast bridge service."""

    def __init__(self, database: Database, settings: Settings | None = None) -> None:
        self.database = database
        self.settings = settings or Settings(data_root=database.path.parent)

    # -- registry ---------------------------------------------------------

    def create_account(self, account: NetWorthAccountInput | Mapping[str, Any]) -> NetWorthAccount:
        parsed = account if isinstance(account, NetWorthAccountInput) else NetWorthAccountInput.model_validate(account)
        key = parsed.account_key or str(uuid.uuid4())
        now = utc_now()
        with self.database.write_session() as session:
            if session.execute(
                select(NetWorthAccountRow).where(NetWorthAccountRow.account_key == key)
            ).scalar_one_or_none() is not None:
                raise DuplicateNetWorthAccountError(f"Net-worth account key {key!r} already exists")
            row = NetWorthAccountRow(
                id=str(uuid.uuid4()),
                account_key=key,
                display_name=parsed.display_name,
                side=parsed.side.value,
                category=parsed.category.value,
                liquidity=parsed.liquidity.value if parsed.liquidity else None,
                owner_label=parsed.owner_label,
                active_from=parsed.active_from.isoformat(),
                active_to=parsed.active_to.isoformat() if parsed.active_to else None,
                stale_after_days=int(parsed.stale_after_days or 45),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        return self.get_account(key)

    add_account = create_account
    create_net_worth_account = create_account

    def get_account(self, account_key: str) -> NetWorthAccount:
        with self.database.session() as session:
            row = session.execute(
                select(NetWorthAccountRow).where(NetWorthAccountRow.account_key == str(account_key))
            ).scalar_one_or_none()
        if row is None:
            raise NetWorthValidationError(f"Net-worth account {account_key!r} not found")
        return self._account_model(row)

    def list_accounts(self, *, include_closed: bool = True) -> list[NetWorthAccount]:
        statement = select(NetWorthAccountRow).order_by(NetWorthAccountRow.display_name, NetWorthAccountRow.account_key)
        if not include_closed:
            statement = statement.where(NetWorthAccountRow.active_to.is_(None))
        with self.database.session() as session:
            rows = session.execute(statement).scalars().all()
        return [self._account_model(row) for row in rows]

    def accounts_for_snapshot_date(self, snapshot_date: date | str) -> list[NetWorthAccount]:
        """Return registry accounts active on a historical snapshot date."""

        captured_on = self._date(snapshot_date)
        return [item for item in self.list_accounts() if self._active(item, captured_on)]

    list_accounts_for_date = accounts_for_snapshot_date

    accounts = list_accounts
    list_net_worth_accounts = list_accounts

    def update_account(self, account_key: str, **changes: Any) -> NetWorthAccount:
        with self.database.write_session() as session:
            row = session.execute(
                select(NetWorthAccountRow).where(NetWorthAccountRow.account_key == str(account_key))
            ).scalar_one_or_none()
            if row is None:
                raise NetWorthValidationError(f"Net-worth account {account_key!r} not found")
            payload = self._account_model(row).model_dump(mode="python")
            payload.pop("id", None)
            payload.pop("created_at", None)
            payload.pop("updated_at", None)
            payload.update(changes)
            parsed = NetWorthAccountInput.model_validate(payload)
            row.display_name = parsed.display_name
            row.side = parsed.side.value
            row.category = parsed.category.value
            row.liquidity = parsed.liquidity.value if parsed.liquidity else None
            row.owner_label = parsed.owner_label
            row.active_from = parsed.active_from.isoformat()
            row.active_to = parsed.active_to.isoformat() if parsed.active_to else None
            row.stale_after_days = int(parsed.stale_after_days or row.stale_after_days)
            row.updated_at = utc_now()
        return self.get_account(account_key)

    update_account_metadata = update_account
    update_net_worth_account = update_account

    def close_account(self, account_key: str, closed_on: date | str | None = None) -> NetWorthAccount:
        closed = self._date(closed_on) if closed_on is not None else datetime.now(UTC).date()
        account = self.get_account(account_key)
        if closed < account.active_from:
            raise NetWorthValidationError("Account closure date cannot precede account activation")
        return self.update_account(account_key, active_to=closed)

    def reactivate_account(self, account_key: str, active_from: date | str | None = None) -> NetWorthAccount:
        account = self.get_account(account_key)
        start = self._date(active_from) if active_from is not None else account.active_from
        return self.update_account(account_key, active_from=start, active_to=None)

    reopen_account = reactivate_account

    # -- snapshot lifecycle ----------------------------------------------

    def create_manual_snapshot(
        self,
        snapshot_date: date | str,
        *,
        clone_latest: bool = True,
        notes: str = "",
        quality_acknowledged: bool = False,
    ) -> NetWorthSnapshotRevision:
        captured_on = self._date(snapshot_date)
        accounts = {item.account_key: item for item in self.list_accounts() if self._active(item, captured_on)}
        if not accounts:
            raise NetWorthValidationError("Create at least one active net-worth account before a snapshot")
        baseline: dict[str, NetWorthBalanceInput] = {}
        if clone_latest:
            previous = self._latest_revision_before(captured_on)
            if previous:
                baseline = {
                    item.account_key: NetWorthBalanceInput(
                        account_key=item.account_key,
                        amount_ils=item.amount_ils,
                        valuation_date=item.valuation_date,
                        notes=item.notes,
                    )
                    for item in previous.balances
                    if item.account_key in accounts
                }
        balances = [
            baseline.get(
                key,
                NetWorthBalanceInput(account_key=key, amount_ils=Decimal(0), valuation_date=captured_on),
            )
            for key in sorted(accounts)
        ]
        return self.create_snapshot(
            captured_on,
            balances,
            origin=NetWorthOrigin.MANUAL,
            notes=notes,
            quality_acknowledged=quality_acknowledged,
        )

    def create_snapshot(
        self,
        snapshot_date: date | str,
        balances: Sequence[NetWorthBalanceInput | Mapping[str, Any]] | Mapping[str, Any],
        *,
        origin: NetWorthOrigin | str = NetWorthOrigin.MANUAL,
        notes: str = "",
        quality_acknowledged: bool = False,
        source_file_id: int | None = None,
        snapshot_id: str | None = None,
    ) -> NetWorthSnapshotRevision:
        captured_on = self._date(snapshot_date)
        parsed_balances, issues, active_account_keys = self._validated_balances(captured_on, balances)
        if issues and not quality_acknowledged:
            raise NetWorthValidationError("Snapshot quality acknowledgement is required: " + ", ".join(issues))
        snapshot_id = snapshot_id or str(uuid.uuid4())
        now = utc_now()
        with self.database.write_session() as session:
            existing = session.execute(
                select(NetWorthSnapshotRow).where(NetWorthSnapshotRow.snapshot_date == captured_on.isoformat())
            ).scalar_one_or_none()
            if existing is not None:
                raise NetWorthValidationError(
                    "A snapshot already exists for this date; save an explicit new revision instead"
                )
            session.add(
                NetWorthSnapshotRow(
                    id=snapshot_id,
                    snapshot_date=captured_on.isoformat(),
                    current_revision_number=1,
                    archived=False,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            self._insert_revision(
                session,
                snapshot_id,
                revision_number=1,
                snapshot_date=captured_on,
                balances=parsed_balances,
                origin=NetWorthOrigin(origin),
                notes=notes,
                quality_issues=issues,
                quality_acknowledged=quality_acknowledged,
                active_account_keys=active_account_keys,
                source_file_id=source_file_id,
                now=now,
            )
        return self.get_revision(snapshot_id)

    save_snapshot = create_snapshot
    create_net_worth_snapshot = create_snapshot

    def save_revision(
        self,
        snapshot_id: str,
        balances: Sequence[NetWorthBalanceInput | Mapping[str, Any]] | Mapping[str, Any],
        *,
        expected_revision_number: int | None = None,
        notes: str = "",
        quality_acknowledged: bool = False,
        origin: NetWorthOrigin | str = NetWorthOrigin.MANUAL,
        source_file_id: int | None = None,
    ) -> NetWorthSnapshotRevision:
        identity = self._snapshot_identity(snapshot_id)
        historical = self.get_revision(snapshot_id, identity.current_revision_number)
        parsed_balances, issues, active_account_keys = self._validated_balances(
            identity.snapshot_date,
            balances,
            expected_account_keys=historical.active_account_keys or [
                item.account_key for item in historical.balances
            ],
        )
        if issues and not quality_acknowledged:
            raise NetWorthValidationError("Snapshot quality acknowledgement is required: " + ", ".join(issues))
        expected = identity.current_revision_number if expected_revision_number is None else expected_revision_number
        now = utc_now()
        with self.database.write_session() as session:
            row = session.get(NetWorthSnapshotRow, str(snapshot_id))
            if row is None:
                raise NetWorthValidationError(f"Net-worth snapshot {snapshot_id} not found")
            if row.current_revision_number != expected:
                raise StaleNetWorthRevisionError(
                    f"Snapshot {snapshot_id} is at revision {row.current_revision_number}; expected {expected}"
                )
            number = expected + 1
            self._insert_revision(
                session,
                str(snapshot_id),
                revision_number=number,
                snapshot_date=identity.snapshot_date,
                balances=parsed_balances,
                origin=NetWorthOrigin(origin),
                notes=notes,
                quality_issues=issues,
                quality_acknowledged=quality_acknowledged,
                active_account_keys=active_account_keys,
                source_file_id=source_file_id,
                now=now,
            )
            row.current_revision_number = number
            row.updated_at = now
        return self.get_revision(snapshot_id, number)

    save_snapshot_revision = save_revision
    save_net_worth_revision = save_revision

    def restore_revision(
        self,
        snapshot_id: str,
        revision_number: int,
        *,
        expected_revision_number: int | None = None,
        notes: str = "Restored older net-worth revision",
        quality_acknowledged: bool = False,
    ) -> NetWorthSnapshotRevision:
        source = self.get_revision(snapshot_id, revision_number)
        expected = (
            self._snapshot_identity(snapshot_id).current_revision_number
            if expected_revision_number is None
            else expected_revision_number
        )
        now = utc_now()
        with self.database.write_session() as session:
            row = session.get(NetWorthSnapshotRow, str(snapshot_id))
            if row is None:
                raise NetWorthValidationError(f"Net-worth snapshot {snapshot_id} not found")
            if row.current_revision_number != expected:
                raise StaleNetWorthRevisionError(
                    f"Snapshot {snapshot_id} is at revision {row.current_revision_number}; expected {expected}"
                )
            number = expected + 1
            self._insert_revision(
                session,
                str(snapshot_id),
                revision_number=number,
                snapshot_date=source.snapshot_date,
                balances=source.balances,
                origin=NetWorthOrigin.RESTORED,
                notes=notes,
                quality_issues=source.quality_issues,
                quality_acknowledged=quality_acknowledged or source.quality_acknowledged,
                active_account_keys=source.active_account_keys or [item.account_key for item in source.balances],
                source_file_id=None,
                now=now,
            )
            row.current_revision_number = number
            row.updated_at = now
        return self.get_revision(snapshot_id, number)

    restore_snapshot_revision = restore_revision

    def archive_snapshot(self, snapshot_id: str, archived: bool = True):
        with self.database.write_session() as session:
            row = session.get(NetWorthSnapshotRow, str(snapshot_id))
            if row is None:
                raise NetWorthValidationError(f"Net-worth snapshot {snapshot_id} not found")
            row.archived = bool(archived)
            row.updated_at = utc_now()
        return self._snapshot_identity(snapshot_id)

    def unarchive_snapshot(self, snapshot_id: str):
        return self.archive_snapshot(snapshot_id, False)

    def get_snapshot(self, snapshot_id: str):
        return self._snapshot_identity(snapshot_id)

    snapshot = get_snapshot

    def list_snapshots(self, *, include_archived: bool = False):
        statement = select(NetWorthSnapshotRow).order_by(desc(NetWorthSnapshotRow.snapshot_date))
        if not include_archived:
            statement = statement.where(NetWorthSnapshotRow.archived.is_(False))
        with self.database.session() as session:
            rows = session.execute(statement).scalars().all()
        return [self._snapshot_identity_from_row(row) for row in rows]

    def list_revisions(self, snapshot_id: str) -> list[NetWorthSnapshotRevision]:
        with self.database.session() as session:
            rows = session.execute(
                select(NetWorthSnapshotRevisionRow)
                .where(NetWorthSnapshotRevisionRow.snapshot_id == str(snapshot_id))
                .order_by(NetWorthSnapshotRevisionRow.revision_number)
            ).scalars().all()
        return [self._revision_from_row(row) for row in rows]

    def get_revision(self, snapshot_id: str, revision_number: int | None = None) -> NetWorthSnapshotRevision:
        identity = self._snapshot_identity(snapshot_id)
        number = revision_number or identity.current_revision_number
        with self.database.session() as session:
            row = session.execute(
                select(NetWorthSnapshotRevisionRow).where(
                    NetWorthSnapshotRevisionRow.snapshot_id == str(snapshot_id),
                    NetWorthSnapshotRevisionRow.revision_number == int(number),
                )
            ).scalar_one_or_none()
        if row is None:
            raise NetWorthValidationError(f"Net-worth snapshot revision {number} not found")
        return self._revision_from_row(row)

    revision = get_revision
    get_snapshot_revision = get_revision

    def account_history(self, account_key: str) -> list[dict[str, Any]]:
        """Return immutable historical balances for one account."""

        key = str(account_key)
        with self.database.session() as session:
            rows = session.execute(
                select(NetWorthBalanceRow, NetWorthSnapshotRevisionRow)
                .join(
                    NetWorthSnapshotRevisionRow,
                    NetWorthSnapshotRevisionRow.id == NetWorthBalanceRow.revision_id,
                )
                .where(NetWorthBalanceRow.account_key == key)
                .order_by(
                    NetWorthSnapshotRevisionRow.snapshot_date,
                    NetWorthSnapshotRevisionRow.revision_number,
                )
            ).all()
        return [
            {
                "snapshot_date": self._date(revision.snapshot_date),
                "revision_number": revision.revision_number,
                "revision_id": revision.id,
                "account_key": balance.account_key,
                "account_name": balance.account_name,
                "side": balance.side,
                "category": balance.category,
                "amount_ils": Decimal(balance.amount_ils),
                "valuation_date": self._date(balance.valuation_date),
                "notes": balance.notes,
            }
            for balance, revision in rows
        ]

    get_account_history = account_history

    # -- CSV --------------------------------------------------------------

    def preview_csv(self, file_bytes: bytes, filename: str | None = None) -> NetWorthCsvPreview:
        raw = bytes(file_bytes)
        file_hash = hashlib.sha256(raw).hexdigest()
        issues: list[str] = []
        warnings: list[str] = []
        rows: list[dict[str, Any]] = []
        snapshot_dates: set[date] = set()
        registry_accounts = {item.account_key: item for item in self.list_accounts()}
        if len(raw) > self.settings.net_worth_csv_max_bytes:
            issues.append("CSV_TOO_LARGE")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = ""
            issues.append("CSV_NOT_UTF8")
        if text:
            try:
                reader = csv.DictReader(io.StringIO(text, newline=""))
                headers = tuple(reader.fieldnames or ())
                if headers != CSV_HEADERS:
                    issues.append("CSV_HEADERS_INVALID")
                for row_number, row in enumerate(reader, start=2):
                    if row_number - 1 > self.settings.net_worth_csv_max_rows:
                        issues.append("CSV_ROW_LIMIT_EXCEEDED")
                        break
                    if None in row or any(len(str(value or "")) > self.settings.net_worth_csv_max_field_length for value in row.values()):
                        issues.append(f"CSV_ROW_{row_number}_MALFORMED")
                        continue
                    required_headers = (
                        "snapshot_date",
                        "account_key",
                        "account_name",
                        "side",
                        "category",
                        "amount_ils",
                        "valuation_date",
                    )
                    if not all(str(row.get(header, "")).strip() for header in required_headers):
                        issues.append(f"CSV_ROW_{row_number}_MISSING_VALUE")
                        continue
                    parsed = dict(row)
                    try:
                        parsed["snapshot_date"] = self._strict_date(row["snapshot_date"])
                        parsed["valuation_date"] = self._strict_date(row["valuation_date"])
                        snapshot_dates.add(parsed["snapshot_date"])
                    except (TypeError, ValueError):
                        issues.append(f"CSV_ROW_{row_number}_DATE_INVALID")
                        continue
                    try:
                        amount_text = str(row["amount_ils"]).strip()
                        if any(char.isalpha() for char in amount_text) or any(symbol in amount_text for symbol in ("$", "€", "£")):
                            issues.append(f"CSV_ROW_{row_number}_FOREIGN_CURRENCY")
                            continue
                        amount = Decimal(amount_text)
                        if not amount.is_finite() or amount < 0:
                            raise InvalidOperation
                        parsed["amount_ils"] = amount
                    except (InvalidOperation, ValueError):
                        issues.append(f"CSV_ROW_{row_number}_AMOUNT_INVALID")
                        continue
                    parsed["owner"] = str(row.get("owner") or "").strip() or None
                    parsed["account_key"] = str(row["account_key"]).strip()
                    account = registry_accounts.get(parsed["account_key"])
                    if account is None:
                        issues.append(f"CSV_ROW_{row_number}_UNKNOWN_ACCOUNT")
                        continue
                    parsed["_csv_row_number"] = row_number
                    rows.append(parsed)
            except csv.Error:
                issues.append("CSV_PARSE_ERROR")
        snapshot_date = next(iter(snapshot_dates)) if len(snapshot_dates) == 1 else None
        if len(snapshot_dates) > 1:
            issues.append("CSV_MULTIPLE_SNAPSHOT_DATES")
        historical_revision = self._snapshot_revision_for_date(snapshot_date) if snapshot_date else None
        historical_balances = {
            item.account_key: item for item in historical_revision.balances
        } if historical_revision is not None else {}
        for parsed in rows:
            historical_metadata = historical_balances.get(parsed["account_key"])
            metadata_source = historical_metadata or registry_accounts[parsed["account_key"]]
            metadata = {
                "account_name": historical_metadata.account_name if historical_metadata else metadata_source.display_name,
                "side": metadata_source.side.value,
                "category": metadata_source.category.value,
                "liquidity": metadata_source.liquidity.value if metadata_source.liquidity else "",
                "owner": (metadata_source.owner_label or ""),
            }
            for field, expected in metadata.items():
                actual = "" if parsed.get(field) is None else str(parsed.get(field, "")).strip()
                if actual != expected:
                    issues.append(f"CSV_ROW_{parsed['_csv_row_number']}_{field.upper()}_MISMATCH")
            parsed.pop("_csv_row_number", None)
        if historical_revision is not None:
            captured_account_keys = set(historical_revision.active_account_keys) or set(historical_balances)
        else:
            captured_account_keys = None
        expected_account_keys = captured_account_keys or {
            item.account_key
            for item in registry_accounts.values()
            if snapshot_date and self._active(item, snapshot_date)
        }
        accounts = {
            key: registry_accounts[key]
            for key in expected_account_keys
            if key in registry_accounts
        }
        seen = [str(item["account_key"]) for item in rows]
        duplicates = {key for key in seen if seen.count(key) > 1}
        if duplicates:
            issues.append("CSV_DUPLICATE_ACCOUNT")
        missing = set(accounts) - set(seen)
        unknown = set(seen) - set(accounts)
        if missing:
            issues.append("CSV_MISSING_ACTIVE_ACCOUNT")
        if unknown:
            issues.append("CSV_FOREIGN_OR_INACTIVE_ACCOUNT")
        if snapshot_date:
            for row in rows:
                if row["valuation_date"] > snapshot_date:
                    issues.append(f"CSV_FUTURE_VALUATION_DATE:{row['account_key']}")
                account = historical_balances.get(row["account_key"]) if historical_revision else accounts.get(row["account_key"])
                if account and (snapshot_date - row["valuation_date"]).days > account.stale_after_days:
                    warnings.append(f"STALE_VALUATION:{row['account_key']}")
        registry_hash = self._registry_hash(snapshot_date)
        with self.database.session() as session:
            source = session.execute(
                select(NetWorthSourceFileRow).where(NetWorthSourceFileRow.sha256 == file_hash)
            ).scalar_one_or_none()
            existing_snapshot = session.execute(
                select(NetWorthSnapshotRow).where(NetWorthSnapshotRow.snapshot_date == snapshot_date.isoformat() if snapshot_date else "")
            ).scalar_one_or_none()
            existing_revision = None
            if source:
                existing_revision = session.execute(
                    select(NetWorthSnapshotRevisionRow)
                    .join(NetWorthImportRow, NetWorthImportRow.revision_id == NetWorthSnapshotRevisionRow.id)
                    .where(NetWorthImportRow.source_file_id == source.id)
                ).scalar_one_or_none()
            existing_revision_number = existing_snapshot.current_revision_number if existing_snapshot else None
        token = self._encode_token({
            "file_sha256": file_hash,
            "snapshot_date": snapshot_date.isoformat() if snapshot_date else None,
            "registry_hash": registry_hash,
            "parser_version": self.settings.net_worth_parser_version,
            "existing_revision_number": existing_revision_number,
        })
        return NetWorthCsvPreview(
            preview_token=token,
            file_sha256=file_hash,
            snapshot_date=snapshot_date,
            filename=filename,
            row_count=len(rows),
            rows=rows,
            issues=sorted(set(issues)),
            warnings=sorted(set(warnings)),
            duplicate_file=source is not None,
            existing_snapshot_id=existing_snapshot.id if existing_snapshot else None,
            existing_revision_id=existing_revision.id if existing_revision else None,
            registry_hash=registry_hash,
        )

    preview_csv_import = preview_csv

    def commit_csv(
        self,
        file_bytes: bytes,
        preview_token: str,
        filename: str | None = None,
        *,
        create_new_revision: bool = False,
        quality_acknowledged: bool = False,
        acknowledge_stale: bool | None = None,
    ) -> NetWorthSnapshotRevision:
        token = self._decode_token(preview_token)
        preview = self.preview_csv(file_bytes, filename)
        if token.get("file_sha256") != preview.file_sha256:
            raise NetWorthPreviewStaleError("The CSV or account registry changed after preview")
        if preview.duplicate_file:
            with self.database.session() as session:
                source = session.execute(
                    select(NetWorthSourceFileRow).where(NetWorthSourceFileRow.sha256 == preview.file_sha256)
                ).scalar_one_or_none()
                imported = session.execute(
                    select(NetWorthImportRow).where(NetWorthImportRow.source_file_id == source.id)
                ).scalar_one_or_none() if source else None
            if imported:
                return self.get_revision(imported.snapshot_id, self._revision_number(imported.revision_id))
        if (
            token.get("registry_hash") != preview.registry_hash
            or token.get("snapshot_date") != (preview.snapshot_date.isoformat() if preview.snapshot_date else None)
            or token.get("existing_revision_number")
            != self._current_revision_number(preview.existing_snapshot_id)
        ):
            raise NetWorthPreviewStaleError("The CSV or account registry changed after preview")
        if not preview.valid:
            raise NetWorthValidationError("CSV commit blocked: " + ", ".join(preview.issues))
        acknowledge = quality_acknowledged if acknowledge_stale is None else acknowledge_stale
        if preview.warnings and not acknowledge:
            raise NetWorthValidationError("Acknowledge stale source valuations before committing")
        snapshot_id = preview.existing_snapshot_id
        if snapshot_id and not create_new_revision:
            raise ExistingSnapshotRevisionError(
                "A different CSV already exists for this snapshot date; explicitly create a new revision"
            )
        target = self.settings.net_worth_archive_root / f"{preview.file_sha256}.csv"
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(bytes(file_bytes))
        archive_installed = False
        persisted = False
        historical_account_keys = None
        if snapshot_id:
            historical_revision = self.get_revision(snapshot_id)
            historical_account_keys = (
                historical_revision.active_account_keys
                or [item.account_key for item in historical_revision.balances]
            )
        try:
            # Install the immutable archive before the database transaction.
            # If either step fails, the exception path removes the archive so
            # no committed source row can point at a missing file.
            if target.exists():
                raise DuplicateNetWorthImportError("The CSV archive already exists")
            os.replace(temporary, target)
            archive_installed = True
            accounts = [
                NetWorthBalanceInput(
                    account_key=str(row["account_key"]),
                    amount_ils=row["amount_ils"],
                    valuation_date=row["valuation_date"],
                    notes=str(row.get("notes") or ""),
                )
                for row in preview.rows
            ]
            if snapshot_id:
                with self.database.write_session() as session:
                    identity = session.get(NetWorthSnapshotRow, snapshot_id)
                    if identity is None:
                        raise NetWorthValidationError("CSV snapshot identity disappeared after preview")
                    source_row = NetWorthSourceFileRow(
                        sha256=preview.file_sha256,
                        original_filename=filename,
                        archived_path=str(target.relative_to(self.settings.data_root)),
                        compressed_bytes=len(file_bytes),
                        uncompressed_bytes=len(file_bytes),
                        parser_version=self.settings.net_worth_parser_version,
                        created_at=utc_now(),
                    )
                    session.add(source_row)
                    session.flush()
                    parsed_balances, issues, active_account_keys = self._validated_balances(
                        preview.snapshot_date,
                        accounts,
                        expected_account_keys=historical_account_keys,
                    )
                    revision_number = identity.current_revision_number + 1
                    revision_id = self._insert_revision(
                        session, snapshot_id, revision_number, preview.snapshot_date, parsed_balances,
                        NetWorthOrigin.CSV, "", issues, bool(acknowledge), active_account_keys, source_row.id, utc_now()
                    )
                    identity.current_revision_number = revision_number
                    identity.updated_at = utc_now()
                    session.add(NetWorthImportRow(
                        id=str(uuid.uuid4()), source_file_id=source_row.id, snapshot_id=snapshot_id,
                        revision_id=revision_id, origin=NetWorthOrigin.CSV.value, imported_at=utc_now()
                    ))
                persisted = True
                result = self.get_revision(snapshot_id, revision_number)
            else:
                with self.database.write_session() as session:
                    source_row = NetWorthSourceFileRow(
                        sha256=preview.file_sha256,
                        original_filename=filename,
                        archived_path=str(target.relative_to(self.settings.data_root)),
                        compressed_bytes=len(file_bytes),
                        uncompressed_bytes=len(file_bytes),
                        parser_version=self.settings.net_worth_parser_version,
                        created_at=utc_now(),
                    )
                    session.add(source_row)
                    session.flush()
                    snapshot_id = str(uuid.uuid4())
                    session.add(NetWorthSnapshotRow(
                        id=snapshot_id, snapshot_date=preview.snapshot_date.isoformat(), current_revision_number=1,
                        archived=False, created_at=utc_now(), updated_at=utc_now()
                    ))
                    session.flush()
                    parsed_balances, issues, active_account_keys = self._validated_balances(preview.snapshot_date, accounts)
                    revision_id = self._insert_revision(
                        session, snapshot_id, 1, preview.snapshot_date, parsed_balances,
                        NetWorthOrigin.CSV, "", issues, bool(acknowledge), active_account_keys, source_row.id, utc_now()
                    )
                    session.add(NetWorthImportRow(
                        id=str(uuid.uuid4()), source_file_id=source_row.id, snapshot_id=snapshot_id,
                        revision_id=revision_id, origin=NetWorthOrigin.CSV.value, imported_at=utc_now()
                    ))
                persisted = True
                result = self.get_revision(snapshot_id, 1)
            return result
        except Exception:
            temporary.unlink(missing_ok=True)
            if archive_installed and not persisted:
                target.unlink(missing_ok=True)
            raise

    commit_csv_import = commit_csv

    def csv_template(self, snapshot_date: date | str | None = None) -> bytes:
        captured_on = self._date(snapshot_date) if snapshot_date is not None else datetime.now(UTC).date()
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=CSV_HEADERS, lineterminator="\n")
        writer.writeheader()
        historical = self._snapshot_revision_for_date(captured_on)
        if historical is not None:
            template_rows = [
                {
                    "account_key": balance.account_key,
                    "account_name": balance.account_name,
                    "side": balance.side.value,
                    "category": balance.category.value,
                    "liquidity": balance.liquidity.value if balance.liquidity else "",
                    "owner": balance.owner_label or "",
                }
                for balance in historical.balances
            ]
        else:
            template_rows = [
                {
                    "account_key": account.account_key,
                    "account_name": account.display_name,
                    "side": account.side.value,
                    "category": account.category.value,
                    "liquidity": account.liquidity.value if account.liquidity else "",
                    "owner": account.owner_label or "",
                }
                for account in self.accounts_for_snapshot_date(captured_on)
            ]
        for row in sorted(template_rows, key=lambda value: value["account_key"]):
            writer.writerow({
                "snapshot_date": captured_on.isoformat(),
                **row,
                "amount_ils": "0",
                "valuation_date": captured_on.isoformat(),
                "notes": "",
            })
        return output.getvalue().encode("utf-8")

    download_csv_template = csv_template

    # -- summaries and trends --------------------------------------------

    def summary(self, revision_id: str | None = None, *, snapshot_id: str | None = None, as_of_date: date | str | None = None) -> NetWorthSummary:
        if revision_id:
            revision = self._get_revision_by_id(revision_id)
        elif snapshot_id:
            revision = self.get_revision(snapshot_id)
        else:
            target = self._date(as_of_date) if as_of_date is not None else datetime.now(UTC).date()
            revision = self._latest_revision_before(target)
            if revision is None:
                raise NetWorthValidationError("No household net-worth snapshot is available")
        assets = Decimal(0)
        liabilities = Decimal(0)
        liquid = Decimal(0)
        restricted = Decimal(0)
        illiquid = Decimal(0)
        by_category: dict[str, Decimal] = {}
        by_liquidity: dict[str, Decimal] = {}
        by_owner: dict[str, Decimal] = {}
        by_account: dict[str, Decimal] = {}
        for item in revision.balances:
            amount = item.amount_ils
            if item.side == NetWorthSide.ASSET:
                assets += amount
                if item.liquidity == NetWorthLiquidity.LIQUID:
                    liquid += amount
                elif item.liquidity == NetWorthLiquidity.RESTRICTED:
                    restricted += amount
                elif item.liquidity == NetWorthLiquidity.ILLIQUID:
                    illiquid += amount
            else:
                liabilities += amount
            by_category[item.category.value] = by_category.get(item.category.value, Decimal(0)) + amount
            if item.liquidity:
                by_liquidity[item.liquidity.value] = by_liquidity.get(item.liquidity.value, Decimal(0)) + amount
            owner = item.owner_label or "Shared"
            by_owner[owner] = by_owner.get(owner, Decimal(0)) + amount
            by_account[item.account_key] = amount
        freshness = max(0, (datetime.now(UTC).date() - revision.snapshot_date).days)
        return NetWorthSummary(
            revision_id=revision.revision_id,
            snapshot_id=revision.snapshot_id,
            snapshot_date=revision.snapshot_date,
            revision_number=revision.revision_number,
            total_assets=assets,
            total_liabilities=liabilities,
            net_worth=assets - liabilities,
            liquid_assets=liquid,
            restricted_assets=restricted,
            illiquid_assets=illiquid,
            stale_account_keys=revision.stale_account_keys,
            snapshot_freshness_days=freshness,
            by_category=by_category,
            by_liquidity=by_liquidity,
            by_owner=by_owner,
            by_account=by_account,
        )

    current_summary = summary
    get_summary = summary
    get_current_summary = summary
    calculate_summary = summary
    current = summary

    def trend(self, start_date: date | str | None = None, end_date: date | str | None = None) -> list[NetWorthTrendPoint]:
        start = self._date(start_date) if start_date is not None else None
        end = self._date(end_date) if end_date is not None else None
        with self.database.session() as session:
            statement = select(NetWorthSnapshotRow).where(NetWorthSnapshotRow.archived.is_(False)).order_by(NetWorthSnapshotRow.snapshot_date)
            rows = session.execute(statement).scalars().all()
        points: list[NetWorthTrendPoint] = []
        for identity in rows:
            captured_on = self._date(identity.snapshot_date)
            if start and captured_on < start or end and captured_on > end:
                continue
            summary = self.summary(snapshot_id=identity.id)
            points.append(NetWorthTrendPoint(
                snapshot_date=summary.snapshot_date,
                revision_id=summary.revision_id,
                total_assets=summary.total_assets,
                total_liabilities=summary.total_liabilities,
                net_worth=summary.net_worth,
                liquid_assets=summary.liquid_assets,
                restricted_assets=summary.restricted_assets,
                illiquid_assets=summary.illiquid_assets,
            ))
        return points

    calculate_trend = trend
    get_trend = trend

    # -- forecast bridge --------------------------------------------------

    def create_forecast_pool_seeds(
        self,
        snapshot_revision_id: str,
        account_keys: Sequence[str] | Mapping[str, str],
        pool_types: Mapping[str, str] | None = None,
    ) -> list[ForecastPoolSeed]:
        revision = self._get_revision_by_id(snapshot_revision_id)
        selected = list(account_keys.keys()) if isinstance(account_keys, Mapping) else list(account_keys)
        if isinstance(account_keys, Mapping):
            pool_types = {**dict(account_keys), **(pool_types or {})}
        pool_types = pool_types or {}
        by_key = {item.account_key: item for item in revision.balances}
        seeds: list[ForecastPoolSeed] = []
        for key in selected:
            balance = by_key.get(str(key))
            if balance is None:
                raise NetWorthValidationError(f"Snapshot revision does not contain account {key!r}")
            if balance.side != NetWorthSide.ASSET or balance.liquidity != NetWorthLiquidity.LIQUID:
                raise NetWorthValidationError(f"Only liquid asset accounts can seed a forecast: {key}")
            pool_type = str(pool_types.get(str(key), ForecastPoolType.CASH.value))
            if pool_type not in {item.value for item in ForecastPoolType}:
                raise NetWorthValidationError(f"Unknown forecast pool type {pool_type!r}")
            seeds.append(ForecastPoolSeed(
                name=balance.account_name,
                pool_type=pool_type,
                opening_balance=balance.amount_ils,
                # Forecast projections begin in the selected snapshot's
                # month.  Keep the balance valuation date separately as
                # provenance so stale valuations remain visible.
                as_of_date=revision.snapshot_date,
                account_key=balance.account_key,
                snapshot_revision_id=revision.revision_id,
                valuation_date=balance.valuation_date,
                stale=balance.stale,
                source_quality_acknowledged=False,
            ))
        if len({seed.name.casefold() for seed in seeds}) != len(seeds):
            raise NetWorthValidationError("Selected net-worth accounts must have unique forecast pool names")
        return seeds

    forecast_pool_seeds = create_forecast_pool_seeds
    seed_forecast_pools = create_forecast_pool_seeds

    def compare_forecast_actual(
        self,
        forecast_id: str,
        observed_snapshot_revision_id: str | int,
        forecast_revision_number: int | str | None = None,
        *,
        role: str = "baseline",
    ) -> ForecastActualComparison:
        from family_finance.forecasting import (
            SavingsForecastService,
            forecast_start_month_for_snapshot,
        )

        # Also accept the natural positional form
        # ``(forecast_id, forecast_revision_number, observed_revision_id)``.
        if isinstance(observed_snapshot_revision_id, int) and isinstance(forecast_revision_number, str):
            observed_snapshot_revision_id, forecast_revision_number = (
                forecast_revision_number,
                observed_snapshot_revision_id,
            )
        if forecast_revision_number is not None:
            forecast_revision_number = int(forecast_revision_number)
        forecasting = SavingsForecastService(self.database)
        forecast = forecasting.get_forecast(forecast_id)
        forecast_revision = forecasting.get_revision(forecast_id, forecast_revision_number)
        observed = self._get_revision_by_id(observed_snapshot_revision_id)
        try:
            selected_role = next(case for case in forecast_revision.cases if case.role.value == role)
        except StopIteration as exc:
            raise NetWorthValidationError(f"Forecast role {role!r} not found") from exc
        source_snapshot_id = forecast_revision.net_worth_snapshot_revision_id
        linked = [
            pool for pool in forecast_revision.starting_pools
            if pool.net_worth_account_key and pool.net_worth_snapshot_revision_id
        ]
        if not linked:
            raise NetWorthValidationError("Forecast revision has no linked net-worth accounts")
        if source_snapshot_id and any(pool.net_worth_snapshot_revision_id != source_snapshot_id for pool in linked):
            raise NetWorthValidationError("Forecast pools do not share the forecast's exact source snapshot revision")
        scenario = forecasting.planning.get_scenario(forecast.scenario_id)
        if not source_snapshot_id:
            raise NetWorthValidationError("Forecast revision is missing its net-worth source snapshot revision")
        source = self._get_revision_by_id(source_snapshot_id)
        forecast_start_month = forecast_start_month_for_snapshot(source.snapshot_date)
        if scenario.start_month != forecast_start_month:
            raise NetWorthValidationError(
                "Forecast start month does not match its linked net-worth snapshot month"
            )
        if observed.snapshot_date < source.snapshot_date:
            raise NetWorthValidationError("Observed snapshot precedes the forecast's opening net-worth snapshot")
        if any(pool.as_of_date != source.snapshot_date for pool in linked):
            raise NetWorthValidationError("Forecast pool start dates do not match the linked net-worth snapshot")
        month_index = (observed.snapshot_date.year - scenario.start_month.year) * 12 + observed.snapshot_date.month - scenario.start_month.month
        if month_index < 0 or month_index >= 36:
            raise NetWorthValidationError("Observed snapshot month is outside the saved 36-month forecast")
        projection = forecasting.engine.project(
            forecasting.planning.get_revision(forecast.scenario_id, forecast_revision.source_revision_number),
            forecast_revision.starting_pools,
            selected_role,
            forecast_id=forecast_id,
            scenario_id=forecast.scenario_id,
            currency=forecast.currency,
            source_revision_id=forecast_revision.source_revision_id,
            source_revision_number=forecast_revision.source_revision_number,
            start_month=scenario.start_month,
        )
        month = projection.months[month_index]
        projected_by_account: dict[str, Decimal] = {}
        observed_by_account = {item.account_key: item.amount_ils for item in observed.balances}
        for pool in linked:
            projected_pool = next((item for item in month.pools if item.pool_name == pool.name), None)
            if projected_pool is None:
                continue
            projected_by_account[pool.net_worth_account_key] = projected_pool.closing_balance
        account_deltas = {
            key: observed_by_account.get(key, Decimal(0)) - value
            for key, value in projected_by_account.items()
        }
        valuation_dates = [item.valuation_date for item in observed.balances if item.account_key in projected_by_account]
        valuation_warning = None
        if any(item != observed.snapshot_date for item in valuation_dates):
            valuation_warning = "Observed balances use valuation dates that differ from the snapshot date."
        timing_warning = None
        if observed.snapshot_date.day != self._month_end(observed.snapshot_date).day:
            timing_warning = "Observed snapshot is not month-end; compare it with the corresponding projected month-end."
        projected_total = sum(projected_by_account.values(), Decimal(0))
        observed_total = sum((observed_by_account.get(key, Decimal(0)) for key in projected_by_account), Decimal(0))
        return ForecastActualComparison(
            forecast_id=forecast_id,
            forecast_revision_id=forecast_revision.revision_id or "",
            forecast_revision_number=forecast_revision.revision_number,
            role=role,
            observed_snapshot_revision_id=observed.revision_id,
            observed_snapshot_date=observed.snapshot_date,
            projected_month=month.month,
            account_deltas=account_deltas,
            projected_by_account=projected_by_account,
            observed_by_account={key: observed_by_account.get(key, Decimal(0)) for key in projected_by_account},
            projected_total=projected_total,
            observed_total=observed_total,
            aggregate_delta=observed_total - projected_total,
            timing_warning=timing_warning,
            valuation_date_warning=valuation_warning,
        )

    forecast_actual_comparison = compare_forecast_actual

    # -- internals --------------------------------------------------------

    def _validated_balances(
        self,
        snapshot_date: date,
        balances: Sequence[NetWorthBalanceInput | Mapping[str, Any]] | Mapping[str, Any],
        *,
        expected_account_keys: Sequence[str] | None = None,
    ):
        if isinstance(balances, Mapping):
            values = []
            for key, value in balances.items():
                if isinstance(value, Mapping):
                    payload = {"account_key": key, **dict(value)}
                    payload.setdefault("valuation_date", snapshot_date)
                else:
                    payload = {"account_key": key, "amount_ils": value, "valuation_date": snapshot_date}
                values.append(NetWorthBalanceInput.model_validate(payload))
        else:
            values = [value if isinstance(value, NetWorthBalanceInput) else NetWorthBalanceInput.model_validate(value) for value in balances]
        keys = [item.account_key for item in values]
        issues: list[str] = []
        if len(keys) != len(set(keys)):
            raise NetWorthValidationError("A snapshot may contain each account exactly once")
        registry_accounts = {item.account_key: item for item in self.list_accounts()}
        expected_keys = (
            {str(key) for key in expected_account_keys}
            if expected_account_keys is not None
            else {
                item.account_key
                for item in registry_accounts.values()
                if self._active(item, snapshot_date)
            }
        )
        accounts = {key: registry_accounts[key] for key in expected_keys if key in registry_accounts}
        if set(keys) != expected_keys or set(accounts) != expected_keys:
            raise NetWorthValidationError(
                "Snapshot must contain every historically captured account exactly once"
            )
        result: list[NetWorthBalance] = []
        for item in values:
            account = accounts[item.account_key]
            if item.valuation_date > snapshot_date:
                raise NetWorthValidationError(f"Valuation date for {item.account_key} is after the snapshot date")
            stale = (snapshot_date - item.valuation_date).days > account.stale_after_days
            if stale:
                issues.append(f"STALE_VALUATION:{item.account_key}")
            result.append(NetWorthBalance(
                account_key=item.account_key,
                amount_ils=item.amount_ils,
                valuation_date=item.valuation_date,
                notes=item.notes,
                account_name=account.display_name,
                side=account.side,
                category=account.category,
                liquidity=account.liquidity,
                owner_label=account.owner_label,
                stale_after_days=account.stale_after_days or 45,
                snapshot_date=snapshot_date,
                stale=stale,
            ))
        return result, sorted(set(issues)), sorted(accounts)

    def _insert_revision(
        self,
        session,
        snapshot_id: str,
        revision_number: int,
        snapshot_date: date,
        balances: Sequence[NetWorthBalance],
        origin: NetWorthOrigin,
        notes: str,
        quality_issues: Sequence[str],
        quality_acknowledged: bool,
        active_account_keys: Sequence[str],
        source_file_id: int | None,
        now: str,
    ) -> str:
        revision_id = str(uuid.uuid4())
        digest = self._content_hash(snapshot_date, balances)
        session.add(NetWorthSnapshotRevisionRow(
            id=revision_id, snapshot_id=snapshot_id, revision_number=revision_number,
            snapshot_date=snapshot_date.isoformat(), origin=origin.value, notes=notes,
            quality_issues_json=json_dumps(list(quality_issues)), quality_acknowledged=quality_acknowledged,
            content_hash=digest, active_account_keys_json=json_dumps(sorted(set(active_account_keys))),
            source_file_id=source_file_id, created_at=now,
        ))
        session.flush()
        for balance in balances:
            session.add(NetWorthBalanceRow(
                id=str(uuid.uuid4()), revision_id=revision_id, account_key=balance.account_key,
                account_name=balance.account_name, side=balance.side.value, category=balance.category.value,
                liquidity=balance.liquidity.value if balance.liquidity else None,
                owner_label=balance.owner_label, stale_after_days=balance.stale_after_days,
                snapshot_date=balance.snapshot_date.isoformat(), amount_ils=self._decimal_text(balance.amount_ils),
                valuation_date=balance.valuation_date.isoformat(), notes=balance.notes,
            ))
        return revision_id

    def _revision_from_row(self, row: NetWorthSnapshotRevisionRow) -> NetWorthSnapshotRevision:
        with self.database.session() as session:
            balances = session.execute(
                select(NetWorthBalanceRow).where(NetWorthBalanceRow.revision_id == row.id).order_by(NetWorthBalanceRow.account_key)
            ).scalars().all()
        revision_date = self._date(row.snapshot_date)
        for balance in balances:
            balance_snapshot_date = self._date(balance.snapshot_date)
            balance_valuation_date = self._date(balance.valuation_date)
            if balance_snapshot_date != revision_date:
                raise NetWorthValidationError("Saved balance snapshot date is invalid")
            if balance_valuation_date > revision_date:
                raise NetWorthValidationError("Saved balance valuation date is invalid")
        parsed_balances = [NetWorthBalance(
            account_key=item.account_key, amount_ils=Decimal(item.amount_ils), valuation_date=self._date(item.valuation_date),
            notes=item.notes, account_name=item.account_name, side=NetWorthSide(item.side), category=self._category(item.category, item.side),
            liquidity=NetWorthLiquidity(item.liquidity) if item.liquidity else None, owner_label=item.owner_label,
            stale_after_days=item.stale_after_days, snapshot_date=revision_date,
            stale=(self._date(item.snapshot_date) - self._date(item.valuation_date)).days > item.stale_after_days,
        ) for item in balances]
        try:
            issues = list(json.loads(row.quality_issues_json))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise NetWorthValidationError("Saved net-worth quality issues are invalid") from exc
        try:
            active_account_keys = list(json.loads(row.active_account_keys_json or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise NetWorthValidationError("Saved net-worth account coverage is invalid") from exc
        if not active_account_keys:
            active_account_keys = [item.account_key for item in parsed_balances]
        snapshot = NetWorthSnapshotRevision(
            snapshot_id=row.snapshot_id, revision_id=row.id, revision_number=row.revision_number,
            snapshot_date=revision_date, origin=NetWorthOrigin(row.origin), notes=row.notes,
            quality_issues=issues, quality_acknowledged=bool(row.quality_acknowledged), content_hash=row.content_hash,
            active_account_keys=sorted({str(key) for key in active_account_keys}),
            source_file_id=row.source_file_id, balances=parsed_balances, created_at=self._datetime(row.created_at),
        )
        if self._content_hash(snapshot.snapshot_date, snapshot.balances) != row.content_hash:
            raise NetWorthValidationError("Saved net-worth content hash is invalid")
        return snapshot

    def _get_revision_by_id(self, revision_id: str) -> NetWorthSnapshotRevision:
        with self.database.session() as session:
            row = session.get(NetWorthSnapshotRevisionRow, str(revision_id))
        if row is None:
            raise NetWorthValidationError(f"Net-worth snapshot revision {revision_id} not found")
        return self._revision_from_row(row)

    def _snapshot_identity(self, snapshot_id: str):
        with self.database.session() as session:
            row = session.get(NetWorthSnapshotRow, str(snapshot_id))
        if row is None:
            raise NetWorthValidationError(f"Net-worth snapshot {snapshot_id} not found")
        return self._snapshot_identity_from_row(row)

    @staticmethod
    def _snapshot_identity_from_row(row) -> NetWorthSnapshotSummary:
        return NetWorthSnapshotSummary(
            snapshot_id=row.id,
            snapshot_date=date.fromisoformat(row.snapshot_date),
            current_revision_number=row.current_revision_number,
            archived=bool(row.archived),
            created_at=datetime.fromisoformat(row.created_at),
            updated_at=datetime.fromisoformat(row.updated_at),
        )

    def _latest_revision_before(self, captured_on: date) -> NetWorthSnapshotRevision | None:
        with self.database.session() as session:
            row = session.execute(
                select(NetWorthSnapshotRevisionRow)
                .join(NetWorthSnapshotRow, NetWorthSnapshotRow.id == NetWorthSnapshotRevisionRow.snapshot_id)
                .where(NetWorthSnapshotRow.snapshot_date <= captured_on.isoformat(), NetWorthSnapshotRow.archived.is_(False))
                .order_by(desc(NetWorthSnapshotRow.snapshot_date), desc(NetWorthSnapshotRevisionRow.revision_number))
                .limit(1)
            ).scalar_one_or_none()
        return self._revision_from_row(row) if row else None

    def _revision_number(self, revision_id: str) -> int:
        with self.database.session() as session:
            row = session.get(NetWorthSnapshotRevisionRow, revision_id)
        if row is None:
            raise NetWorthValidationError("Saved CSV provenance points to a missing revision")
        return row.revision_number

    def _current_revision_number(self, snapshot_id: str | None) -> int | None:
        if not snapshot_id:
            return None
        with self.database.session() as session:
            row = session.get(NetWorthSnapshotRow, snapshot_id)
        return row.current_revision_number if row else None

    def _captured_account_keys_for_date(self, snapshot_date: date | None) -> set[str] | None:
        if snapshot_date is None:
            return None
        revision = self._snapshot_revision_for_date(snapshot_date)
        if revision is None:
            return None
        return set(revision.active_account_keys) or {
            item.account_key for item in revision.balances
        }

    def _snapshot_revision_for_date(self, snapshot_date: date) -> NetWorthSnapshotRevision | None:
        with self.database.session() as session:
            identity = session.execute(
                select(NetWorthSnapshotRow).where(
                    NetWorthSnapshotRow.snapshot_date == snapshot_date.isoformat()
                )
            ).scalar_one_or_none()
            if identity is None:
                return None
            revision = session.execute(
                select(NetWorthSnapshotRevisionRow).where(
                    NetWorthSnapshotRevisionRow.snapshot_id == identity.id,
                    NetWorthSnapshotRevisionRow.revision_number == identity.current_revision_number,
                )
                ).scalar_one_or_none()
        if revision is None:
            return None
        return self._revision_from_row(revision)

    def _registry_hash(self, snapshot_date: date | None) -> str:
        values = []
        for item in self.list_accounts():
            if snapshot_date is not None and not self._active(item, snapshot_date):
                continue
            values.append({
                "account_key": item.account_key, "display_name": item.display_name, "side": item.side.value,
                "category": item.category.value, "liquidity": item.liquidity.value if item.liquidity else None,
                "owner_label": item.owner_label, "active_from": item.active_from.isoformat(),
                "active_to": item.active_to.isoformat() if item.active_to else None,
                "stale_after_days": item.stale_after_days,
            })
        return hashlib.sha256(json_dumps(sorted(values, key=lambda value: value["account_key"])).encode()).hexdigest()

    @staticmethod
    def _content_hash(snapshot_date: date, balances: Sequence[NetWorthBalance]) -> str:
        payload = [{
            "account_key": item.account_key, "account_name": item.account_name, "side": item.side.value,
            "category": item.category.value, "liquidity": item.liquidity.value if item.liquidity else None,
            "owner_label": item.owner_label, "stale_after_days": item.stale_after_days,
            "snapshot_date": item.snapshot_date.isoformat(), "amount_ils": str(item.amount_ils),
            "valuation_date": item.valuation_date.isoformat(), "notes": item.notes,
        } for item in sorted(balances, key=lambda value: value.account_key)]
        return hashlib.sha256(json_dumps(payload).encode()).hexdigest()

    @staticmethod
    def _account_model(row: NetWorthAccountRow) -> NetWorthAccount:
        return NetWorthAccount(
            id=row.id, account_key=row.account_key, display_name=row.display_name,
            side=NetWorthSide(row.side), category=NetWorthService._category(row.category, row.side),
            liquidity=NetWorthLiquidity(row.liquidity) if row.liquidity else None,
            owner_label=row.owner_label, active_from=date.fromisoformat(row.active_from),
            active_to=date.fromisoformat(row.active_to) if row.active_to else None,
            stale_after_days=row.stale_after_days, created_at=NetWorthService._datetime(row.created_at),
            updated_at=NetWorthService._datetime(row.updated_at),
        )

    @staticmethod
    def _category(value: str, side: str) -> NetWorthCategory:
        if value == "other" and side == NetWorthSide.LIABILITY.value:
            return NetWorthCategory.OTHER_LIABILITY
        if value == "other":
            return NetWorthCategory.OTHER_ASSET
        return NetWorthCategory(value)

    @staticmethod
    def _active(account: NetWorthAccount, captured_on: date) -> bool:
        return account.active_from <= captured_on and (account.active_to is None or captured_on <= account.active_to)

    @staticmethod
    def _date(value: date | str | None) -> date:
        if value is None:
            raise ValueError("A date is required")
        if isinstance(value, datetime):
            return value.date()
        return value if isinstance(value, date) else date.fromisoformat(str(value))

    @staticmethod
    def _strict_date(value: str) -> date:
        parsed = date.fromisoformat(str(value).strip())
        if parsed.isoformat() != str(value).strip():
            raise ValueError("Dates must use YYYY-MM-DD")
        return parsed

    @staticmethod
    def _datetime(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        return format(Decimal(value), "f")

    @staticmethod
    def _month_end(value: date) -> date:
        next_month = date(value.year + 1, 1, 1) if value.month == 12 else date(value.year, value.month + 1, 1)
        return date.fromordinal(next_month.toordinal() - 1)

    @staticmethod
    def _encode_token(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode_token(token: str) -> dict[str, Any]:
        try:
            raw = base64.urlsafe_b64decode(str(token) + "=" * (-len(str(token)) % 4))
            payload = json.loads(raw.decode())
            if not isinstance(payload, dict):
                raise TypeError
            return payload
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise NetWorthPreviewStaleError("The CSV preview token is invalid") from exc


__all__ = [
    "CSV_HEADERS",
    "DuplicateNetWorthImportError",
    "ExistingSnapshotRevisionError",
    "NetWorthCsvPreview",
    "NetWorthPreviewStaleError",
    "NetWorthService",
    "NetWorthValidationError",
    "StaleNetWorthRevisionError",
]
