# Family Finance

Family Finance is a local-first household finance application. Phase 1 establishes a safe FamilyBiz XLSX import vertical slice with immutable source provenance, occurrence-aware reconciliation, and a Streamlit review flow.

## Local setup

The project uses Python 3.12 and uv.

    uv sync --dev
    uv run family-finance inspect "data/familybiz report 21-09-26.xlsx"
    uv run streamlit run streamlit_app.py

If uv is not available on PATH, bootstrap it in the ignored local environment:

    python3 -m venv .uv-bootstrap
    .uv-bootstrap/bin/python -m pip install uv
    .uv-bootstrap/bin/uv sync --dev

The database and archived uploads live under data/local/, which is intentionally excluded from Git. Streamlit is configured for localhost and telemetry is disabled.

## Scope

The importer preserves source values and provenance, normalizes dates, text, and numbers for matching, keeps non-ILS rows visible but outside ILS totals, and never deletes a transaction because it disappears from a later export. Phase 2 adds SQLAlchemy-backed classification and monthly metrics; dashboards, balances, installments, FX conversion, and net-worth calculations remain later phases.

See [`docs/financial_metrics.md`](docs/financial_metrics.md) for signs, formulas, completeness rules, exclusions, and source limitations.

See docs/ for the evidence-based data analysis, architecture, data model, and roadmap.
