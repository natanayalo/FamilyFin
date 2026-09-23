# Family Finance

Family Finance is a local-first household finance application. Phase 1 establishes a safe FamilyBiz XLSX import vertical slice with immutable source provenance, occurrence-aware reconciliation, and a Streamlit review flow.

## Local setup

The project uses Python 3.12 and uv. If `uv` is already on your `PATH`:

    uv sync --dev
    uv run family-finance inspect "data/familybiz report 21-09-26.xlsx"
    uv run streamlit run streamlit_app.py

If `zsh` reports `command not found: uv`, install it in the ignored local
bootstrap environment and use that executable explicitly. Installing a
command into a virtual environment does not automatically add it to `PATH`:

    python3 -m venv .uv-bootstrap
    .uv-bootstrap/bin/python -m pip install uv
    .uv-bootstrap/bin/uv sync --dev
    .uv-bootstrap/bin/uv run family-finance inspect "data/familybiz report 21-09-26.xlsx"
    .uv-bootstrap/bin/uv run streamlit run streamlit_app.py

`inspect` is read-only and does not populate the dashboard. To import the
workbook, open the Streamlit app, go to **Data Quality**, upload the same XLSX,
choose **Inspect and preview**, then choose **Commit import**. The dashboard
will populate after the commit.

Alternatively, add the bootstrap directory to the current shell session and
then use the shorter commands:

    export PATH="$PWD/.uv-bootstrap/bin:$PATH"
    uv sync --dev
    uv run family-finance inspect "data/familybiz report 21-09-26.xlsx"
    uv run streamlit run streamlit_app.py

The database and archived uploads live under data/local/, which is intentionally excluded from Git. Streamlit is configured for localhost and telemetry is disabled.

## Scope

The importer preserves source values and provenance, normalizes dates, text, and numbers for matching, keeps non-ILS rows visible but outside ILS totals, and never deletes a transaction because it disappears from a later export. Phase 3 adds a four-page Streamlit dashboard, deterministic non-persisted insights, database auditing, verified online backups, privacy-safe operational logging, and migration validation. Phase 4 adds a fifth Planning page with local-only twelve-month scenarios, immutable revisions, historical/CSV seed previews, exact-decimal projections, and actual-versus-plan comparisons. Phase 7 adds the account-level, ILS-only Net Worth ledger: user-maintained balance snapshots, immutable revisions, strict CSV provenance, liquidity/ownership/category breakdowns, and an explicit forecast seeding bridge. No balance is inferred from transactions, forecasts, or apartment assumptions.

See [`docs/financial_metrics.md`](docs/financial_metrics.md) for signs, formulas, completeness rules, exclusions, and source limitations.

See docs/ for the evidence-based data analysis, architecture, data model, and roadmap.

See [`docs/operations.md`](docs/operations.md) for audit, backup, and manual restore procedures.

See [`docs/net_worth_methodology.md`](docs/net_worth_methodology.md) for the observation, staleness, liquidity, and forecast-comparison rules.

Phase 8 adds local-only recurring automation, deterministic persisted alerts,
immutable previous-month summaries, and the **Automation & Insights** page.
Automation can be run manually with `family-finance automate [--dry-run]`.
The documented macOS `launchd` setup remains a manual user action; see
[`docs/automation_launchd.md`](docs/automation_launchd.md).
