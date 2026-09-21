# Data model

## Tables

- source_files: one archived upload per SHA-256, with filename, sizes, and archive path.
- import_batches: every committed, duplicate, rejected, or review-required attempt, including parser version, report range, maximum booking date, freshness, and statistics.
- accounts: provider, card/bank kind, display label, currency, and a fingerprint of the source reference.
- categories: exact source movement-type/category pairs. No strict hierarchy is imposed.
- source_records: immutable raw row payload, sheet/section/row provenance, normalized row payload, fingerprint, validation state, and issue codes.
- transactions: current normalized logical state with decimal values stored as text to avoid floating-point loss.
- transaction_sources: auditable links between each normalized transaction and source occurrences, including match method.
- reconciliation_cases: open candidate links and later user decisions.
- analysis_overrides: append-only user classifications. They never overwrite source rows or normalized import history; a null value is a field tombstone used to clear the latest decision.
- classification_rules: append-only exact source-key rule revisions. A later revision supersedes the prior revision; a tombstone disables the key without deleting history.
- planning_scenarios: stable twelve-month, single-currency scenario identities with clone lineage and reversible archive state.
- planning_scenario_revisions: immutable, numbered full snapshots. Saving, restoring, and cloning never mutate an earlier revision.
- planning_items: revision-scoped positive-magnitude income, expense, savings-contribution, and savings-withdrawal schedules, including seed provenance and contributor transaction IDs.
- planning_source_files: SHA-256-addressed planning CSV archives.
- planning_seed_imports: links from a CSV archive to its created scenario and revision, including parser provenance.
- net_worth_accounts: stable account keys, asset/liability metadata, ownership labels, lifecycle dates, and editable stale thresholds.
- net_worth_snapshots: one identity per snapshot date with a current revision pointer and archive state.
- net_worth_snapshot_revisions: immutable complete observations with quality acknowledgement, content hash, origin, and optional CSV source.
- net_worth_balances: normalized ILS amounts with captured account metadata, valuation date, and notes.
- net_worth_source_files and net_worth_imports: content-addressed strict CSV archives and revision provenance.
- savings_forecast_revisions/savings_forecast_pools: nullable exact Net Worth snapshot and account provenance for explicit seeded forecasts.

## Constraints and lifecycle

Source files are content-addressed by unique SHA-256. A duplicate file creates a duplicate batch with no transaction changes. Source rows are immutable. Transactions are updated only for a unique non-monetary match and retain the old source row through transaction_sources.

Booking date and allocation date are separate. Amount, original amount, and all dates are normalized before matching. Currency is explicit. ILS analytics include only ILS transactions; non-ILS records remain visible with a quality warning.

Accepted rows link to exactly one transaction occurrence. An unresolved row links to one open reconciliation case and no transaction. A dismissed case remains outside analytics. A resolved case links its source row exactly once to an existing or newly accepted transaction.

## Reconciliation invariants

1. Every accepted source row has exactly one transaction_sources link.
2. Every unresolved source row has exactly one open reconciliation_cases row and no transaction link.
3. Every transaction has at least one source link.
4. Unresolved and dismissed rows never enter analytics.
5. Exact duplicate multiplicity is preserved. Re-importing the same file is a no-op for transactions.
6. Missing rows in later exports never delete an existing transaction.
7. Section counts and currency totals reconcile to accepted normalized records.

The initial schema is frozen in `alembic/versions/0001_initial.py`; later
constraints and indexes must be introduced through new revisions. The current
`0002_source_link_invariants` revision enforces one transaction link and one
reconciliation case per source row. `0003_financial_classification` adds the
classification rule log and deterministic latest-override index.

Planning is intentionally isolated from transaction and classification tables.
Money is stored as canonical decimal text. A planning scenario covers exactly
12 inclusive calendar months; monthly items use inclusive start/end months and
one-time items use one occurrence month. The latest CSV target block is parsed
structurally, and blank amounts are not inferred from notes. Migration
`0004_budget_planning` adds the planning lifecycle and provenance tables;
`0005_planning_quality` persists provisional status, issue codes, historical
completeness snapshots, CSV notes, and item-level notes across revisions.
Migration `0008_household_net_worth` adds the account registry, complete
snapshot revisions, normalized balances, CSV provenance, and nullable forecast
source links. Asset liquidity is required; liability liquidity is omitted.
Balances are stored as canonical Decimal text. A complete snapshot contains
every account active on its snapshot date exactly once, with valuation dates no
later than the snapshot date.
