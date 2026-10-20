# Savings Forecast review - 17 October 2026

Refined the existing screen in the selected option 1 direction, using the in-app
browser and disposable QA household. No real household financial records or
preferences changed. Preview: http://localhost:3101/savings-forecast.

## Flow review

1. **Starting a forecast - improved and verified.** The original empty state was
   generic and the source editor emphasized internal identifiers (01–02). The
   guide now explains planning source → opening money → comparison (05–07).
   Source names, revision and recurring/one-time behavior are readable; identifiers
   remain in a disclosure. Opening fields use Hebrew currency labels and larger
   columns (17). Renaming a pool preserves field focus and updates its routes.
   Completed the first forecast through the real QA API with 42,000.25 opening
   money and the sample plan's 4,000 monthly contribution.
2. **Understanding the result - improved and verified.** The original first screen
   led with administration and source verification, ahead of results (03–04).
   The new screen leads with selected forecast and period, then separates projected
   closing money, starting money, cumulative contributions and assumed growth (23).
   Case cards change the breakdown and monthly detail together. Shared MonthPicker
   replaces the long list and numeric event/adjustment month inputs. A 12-month
   baseline shows 48,000 contributions and 91,916.72 closing; 36 months shows
   144,000 contributions, 10,286.84 assumed growth and 196,287.09 closing. The
   12-month optimistic case shows 93,826.37. Monthly details separate deposits
   from swept surplus rather than mislabeling a deposit-only number as both.
3. **Changing assumptions and saved versions - fixed and verified.** Editing a
   saved forecast exposed a pre-existing strict-request failure (21): saved pool
   objects contain pool_id, which is absent from the write schema. The frontend
   now sends only editable pool fields while retaining source references, exact
   decimal strings, acknowledgements and expected revision. Changing baseline
   return from 3% to 4% yields 199,808.92, with 13,808.67 assumed growth (24).
   Save remains blocked until assumptions are confirmed. A QA copy was saved as
   revision 2, revision 1 inspected, and restored as revision 3. The original
   forecast remained unchanged. Source/revision/clone/archive tools are below
   the main result; historical selection has a prominent warning.

![Guided first use](/Users/natanayalo/dev/FamilyFin/frontend/test-results/forecast-design-2026-10-17/05-empty-after.jpg)
![Final forecast](/Users/natanayalo/dev/FamilyFin/frontend/test-results/forecast-design-2026-10-17/23-final-desktop.jpg)
![Changed assumption preview](/Users/natanayalo/dev/FamilyFin/frontend/test-results/forecast-design-2026-10-17/24-preview-layout-final.jpg)

## Visual corrections and accessibility observations

- P2: 320px chart labels clipped their leading digits (14). Responsive chart
  dimensions, compact Hebrew scale labels and a separate currency key fix this
  (16, opened compare-chart-phone).
- P2: opening-pool fields were too narrow in the desktop half-width card (08).
  Switched that local grid to two columns, retaining a single column on phones
  (17).
- P2: the nested preview wrapped currency to a separate line (22). Its totals now
  use two columns on desktop and one on phones (24). Full and focused combined
  comparisons were opened before acceptance.

Phone 320×844 and 390×844, tablet 768×1024, desktop 1280×720 and light/dark were
inspected. Document/client widths both equal 320 in the narrow chart check. Main
projected money is visible above phone navigation (11,13). Native disclosures,
calendar bounds, labels, selected case state and returned editor focus were checked.
This is not full accessibility or quantitative contrast certification.

## Verification and limits

128 frontend tests pass: 125 component + 3 health, including 12 new forecast tests
and the existing empty-state test. Coverage includes exact large-money aggregation,
cumulative checkpoint semantics, role/period/month changes, shortfall period bounds,
pool renaming/routes, calendar-to-offset transport, focus, failed loads and sanitized
preview/create/save requests. Type checking, full lint, production build and diff
check pass. The previous forecast hook warning is resolved. Also corrected an
unsupported Testing Library option in the existing Planning test so full test
source type checking passes.

The forecast engine, financial policy, API schemas and database schema are unchanged.
CLI Playwright was not run; its fixtures were updated to the new disclosures and
preview copy. Full auth-loss/uncertain-mutation browser replay, all quality-ack/import
variants, physical devices and Safari/Firefox certification remain outside this pass.
Existing protections remain in place. Final browser error lists are empty.

All evidence is private/ignored under frontend/test-results/forecast-design-2026-10-17/.
Capture 09 proves initial confirmation/save state, not a full preview overview.
The final fixture was recreated after disposable creation/edit/restore checks: one
base Planning scenario, eight Net Worth accounts/three snapshots and one baseline
forecast at revision 1. tests/qa_forecasts.py refuses non-QA paths and existing
forecasts; both refusals were smoke-tested. Preview is left at baseline/36 months,
no draft, management closed, dark theme and default viewport restored.
