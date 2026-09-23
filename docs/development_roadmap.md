# Development roadmap

## Phase 0 through Phase 2 delivered in this repository

1. Repository and privacy-safe local setup.
2. Evidence-based source analysis, architecture, data model, and roadmap.
3. Strict FamilyBiz workbook inspector and normalizer.
4. Pydantic contracts for inspection, parsed records, candidates, previews, decisions, statistics, and quality issues.
5. SQLite schema with an Alembic initial migration.
6. Content-addressed archives, atomic commits, duplicate-file idempotency, occurrence-aware matching, and unresolved cases.
7. Streamlit import flow with sanitized preview, freshness warning, history, and reconciliation visibility.
8. Synthetic tests for source variants, invalid files, idempotency, duplicate multiplicity, update/reconciliation behavior, rollback, and provenance.
9. SQLAlchemy runtime repositories, append-only classification rules and overrides, deterministic classification, monthly metrics, completeness, contributor drill-down, and validation UI.

## Next hardening work

- Add a database invariant audit command and property-based occurrence tests.
- Add a clean SQLite backup command and restore verification.
- Add an explicit account mapping workflow for new providers.
- Verify Alembic upgrade/downgrade on a disposable database in CI.
- Add structured local logging that emits counts and issue codes only.

## Later phases

Phase 3 adds polished household dashboards and trends using booking date and explicit currency scope. Phase 4 adds a local-only twelve-month Planning page, immutable scenario revisions, historical and strict multi-block CSV seeds, projections, scenario comparisons, actual-versus-plan comparisons, and planning backup/audit coverage. Phase 7 adds the ILS-only household Net Worth ledger with account lifecycle, complete immutable snapshots, strict CSV provenance, trends, liquidity/ownership breakdowns, and exact forecast seeding/comparison links. Phase 8 adds local recurring imports, deterministic persisted alerts, immutable monthly summaries, and mobile-friendly Automation & Insights workflows. AI-generated analysis remains out of scope.
