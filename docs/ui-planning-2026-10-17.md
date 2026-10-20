# Planning design review - 17 October 2026

Refined the existing Planning page in the selected option 1 design direction.
All browser mutations used the disposable QA household at
http://localhost:3101/planning. Real household records and preferences were untouched.
Screenshots below were captured and opened in this review, using the in-app browser.

## Flow review

1. **First use - improved and verified.** The original empty state led with scenario
   administration and a generic empty box (01). The new guide explains amounts,
   timing and monthly money remaining, with an immediate first-plan action (05–06).
   Completed creation through the real QA API: income 12,000.50, expenses 7,500.25,
   savings 2,000, remaining 2,500.25 (07). The guide action and shared calendar work;
   validation, input labels and exact decimal transport remain intact.
2. **Monthly plan - improved and verified.** Originally the summary showed only
   first-month totals and the assumption count (03–04). A shared month selector now
   controls a dated summary of money remaining, income, expenses and savings (23).
   The description explains withdrawals and that this is a plan, not a bank balance.
   Annual planning and all saved assumptions remain available in disclosures.
   For the five-item sample, normal months leave 5,000.25; November's 9,000 one-time
   expense produces a -3,999.75 funding gap and an explicit warning (13).
3. **Actuals and secondary tools - improved and verified.** Actuals now appear
   directly below the selected month's plan in matching columns. Partial September
   data shows the observed 17.4 expense with a coverage warning (17–18). November
   actuals remain unavailable instead of zero (14). Signed variances appear only
   when the service reports complete data; that branch is component-tested.
   Clone and two-scenario comparison work without resetting selections (24).
   CSV/history import and revision controls remain grouped in additional tools.

![Guided setup](/Users/natanayalo/dev/FamilyFin/frontend/test-results/planning-design-2026-10-17/05-empty-after.jpg)
![Selected-month plan](/Users/natanayalo/dev/FamilyFin/frontend/test-results/planning-design-2026-10-17/23-final-desktop.jpg)
![Partial actuals](/Users/natanayalo/dev/FamilyFin/frontend/test-results/planning-design-2026-10-17/17-partial-actuals-phone-final.jpg)

## Corrections and accessibility observations

The first implementation still placed too much scenario metadata ahead of money
on phones (08). Compacted the selector/actions and put remaining money first (09).
The result appears above fixed navigation at 390×844. Matched before/after images
were opened together. Tablet, 320px actuals/editor and light theme were inspected
(18–19, 21–22); measured document and client widths match at 320 and 768.
Native disclosures support Enter, calendar controls expose bounded months, and
editor fields keep visible labels. A cancel-focus issue found during browser QA
was fixed: focus now returns after the create button becomes enabled. Verified
in the final build and covered by a regression test. This is not full accessibility
certification or a quantitative contrast audit.

Fixed a scenario-comparison state bug: changing checkbox choices no longer retriggers
loadData and clears comparisons. Request sequencing ignores outdated scenario and
actuals responses. Revision mismatches reject actual comparisons rather than mixing
versions. New scenario timing/currency now uses its own draft instead of the
previously selected saved scenario's values. Financial calculations remain server-owned.

## Evidence and checks

Private ignored captures: frontend/test-results/planning-design-2026-10-17/.
01/02/03/04 are pre-change empty/editor/populated evidence; 04 is a populated
full-top view despite its historical filename, not accepted evidence of actuals.
15 similarly shows a September summary, not the actuals table; 17 replaces it for
that claim. Desktop source/final are native 1280×720. Phone is 390×844 and 320×844;
tablet is 768×1024. Full and focused combined comparisons were inspected; see
root design-qa.md for the fidelity review and iteration record.

113 component + 3 health tests pass (116 total), including 10 Planning tests.
Final production build validates TypeScript and passes. Full ESLint: no errors,
only the existing ForecastsFeature refreshAll hook warning. git diff --check passes.
The guarded tests/qa_planning.py seeder rejects non-QA paths and repeat seeding;
both refusals were smoke-tested. No backend financial logic, API contract or schema
changed. CLI e2e was not run. Complete-coverage actuals were checked in component
tests, not fabricated in the browser. Full import/restore browser revalidation,
physical devices and Safari/Firefox certification are outside this scoped pass.

Final preview is at October 2026, original QA plan selected, no draft pending,
extra tools and annual projection collapsed, dark theme and default viewport restored.
A QA clone remains for comparison. The existing eight-account/three-snapshot
Net Worth fixture was also restored in the final disposable QA stack.
