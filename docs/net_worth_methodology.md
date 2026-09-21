# Household net-worth methodology

## Observation boundary

Net Worth is an observed-balance ledger, not a transaction or projection
ledger. A user creates an account registry and records one complete balance
snapshot per date. FamilyBiz transactions, savings forecasts, and apartment
assumptions never create observed balances automatically. All consolidated
amounts are ILS; foreign-currency balances are rejected by the strict CSV
workflow.

## Signs and liquidity

Assets and liabilities are stored as non-negative magnitudes. Net worth is
`total assets - total liabilities`. Asset liquidity is reported independently
as liquid, restricted, and illiquid. Pension, training-fund, and property
accounts remain non-spendable unless the user explicitly registers them with a
liquid classification. Liabilities do not have a liquidity classification.

## Snapshot completeness and history

A snapshot revision must contain every account active on its snapshot date
exactly once. Valuation dates cannot be later than the snapshot date. The
account name, side, category, liquidity, owner label, and stale threshold are
copied into each normalized balance row, preserving historical meaning when
the registry is edited later. Saving, restoring, and CSV imports create new
immutable revisions; optimistic concurrency prevents lost edits.

Default stale thresholds are 45 days for liquid assets and liabilities, 120
days for restricted assets, and 365 days for illiquid assets. Thresholds are
editable per account. A stale balance remains visible and flagged, but saving
requires an explicit acknowledgement.

## CSV and provenance

One strict CSV file represents one snapshot date and must contain exactly the
columns in the downloadable template. Registry keys and metadata must match;
unknown, missing, duplicate, malformed, future-dated, or foreign-currency
rows block commit. SHA-256 content addressing makes an identical re-import a
no-op. A different file for an existing date requires an explicit new
revision. Preview tokens pin the uploaded bytes and registry state.

## Forecast bridge

“Seed from Net Worth” selects one exact saved snapshot revision and eligible
liquid asset accounts. Each selected account becomes a forecast pool with
pinned opening amount, valuation date, account key, and snapshot revision.
Stale source balances require a separate forecast acknowledgement. A later
snapshot never changes an existing forecast or apartment study. Forecast
versus actual compares only linked accounts and exact revisions, aligning the
observed snapshot calendar month with the corresponding projected month-end
and warning when timing or valuation dates differ.

The monthly forecast bridge accepts a first-of-month snapshot as the opening
balance for that month, or a month-end snapshot with the forecast beginning in
the following month. Mid-month snapshots are rejected because the monthly
engine cannot represent partial-month cash flows without risking double-counting.
