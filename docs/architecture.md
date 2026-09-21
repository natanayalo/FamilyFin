# Architecture

## Boundaries

The application has five layers:

1. importers validate the XLSX container, detect repeated sections, normalize source rows, and emit typed records and quality issues.
2. services.py owns inspection, preview, commit, reconciliation, freshness, and import statistics. It has no Streamlit dependency.
3. persistence owns SQLite schema access, transaction boundaries, archive references, and provenance links.
4. planning.py owns local-only twelve-month scenarios, strict planning CSV/history seeds, immutable revisions, projections, comparisons, and planning provenance.
5. ui is a thin Streamlit presentation layer. It renders sanitized preview samples and calls application services.

Financial calculations must remain outside Streamlit. Phase 2 classification and reporting can consume accepted normalized transactions while excluding unresolved and dismissed source records.

## Local storage and privacy

The SQLite database and content-addressed archived uploads live under data/local/. The directory, financial workbooks, CSV files, databases, and logs are excluded from Git. The parser stores account-reference fingerprints, not raw identifiers, in the database. Logs and UI previews contain counts, dates, currencies, and issue codes rather than descriptions or source identifiers.

Streamlit binds to 127.0.0.1 and telemetry is disabled. There are no cloud services, external APIs, or network calls in the import path.

Database startup runs Alembic upgrade to head. Runtime code does not create a second ad hoc schema, so a new database and a disposable migration test follow the same migration path.

Phase 4 completion status: delivered. Planning has a fifth Streamlit page,
`0004_budget_planning` and `0005_planning_quality`, content-addressed CSV archives, immutable revision
history, reversible archive state, backup/audit invariants, and explicit
provenance for manual, historical, and CSV assumptions. Planning never writes
transactions, source records, classifications, FamilyBiz categories, or
historical metrics.

## Database access decision

Phase 2 uses SQLAlchemy 2.0 engines, sessions, declarative mappings, and
repositories for runtime persistence. SQLite remains local-only. Connections
enable foreign keys and WAL mode, and all mutating repository operations use an
explicit `BEGIN IMMEDIATE` transaction so import, reconciliation, overrides,
and reusable-rule revisions remain atomic. Monetary values continue to be
stored as canonical decimal text and are converted to `Decimal` at the domain
boundary.

## Atomic import flow

1. Validate the upload extension, compressed and uncompressed sizes, ZIP integrity, macros, formulas, worksheet count, repeated headers, account identity, dates, and numeric fields.
2. Hash the complete file and return an inspection/preview without database writes.
3. Include file hash, parser version, and latest committed batch in the preview token.
4. Re-parse on commit. Abort if the file, parser version, or database baseline changed.
5. Archive the content-addressed file and insert the source file reference, batch, accounts, categories, immutable source rows, normalized transactions, links, and reconciliation cases inside one SQLite transaction.
6. Mark a batch needs_review when unresolved reconciliation cases exist. No unresolved row is included in analytics.

The file archive is written before the database transaction so a failed database commit can leave only a harmless content-addressed orphan. The database never points to an archive until the corresponding transaction commits.

## Backup and restore

Stop the Streamlit process, copy data/local/family_finance.sqlite3 together with data/local/imports/, and retain them as one backup set. Restore by replacing the local directory while the application is stopped. SQLite WAL files should be included if present, or a SQLite backup/export should be taken after a clean stop. The source files are content-addressed, so an archive can be independently checked against its recorded SHA-256.
