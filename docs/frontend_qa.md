# Frontend visual QA - 2026-10-02

Reviewed the running production-style local app with synthetic data. The demo contains 39 transactions, a saved budget scenario, a net-worth snapshot and a saved forecast. Household source storage was not used for QA mutations.

## Findings and changes

| Priority | Finding | Result |
| --- | --- | --- |
| High | Forecast percentages were incorrectly displayed and decimal percentage inputs were incorrectly converted. | Fixed the exact decimal conversion: a stored rate of `0.03` displays as `3`; entering `3.5%` sends `0.035`. Added unit and browser regression checks. |
| Medium | Dashboard comparisons repeated untranslated codes and ran together. | Hebrew explanations, separated comparison paragraphs, larger supporting text, responsive card widths, expandable original diagnostic codes. |
| Medium | Mobile filters occupied most of the first screen. | Collapsed period/currency summary on mobile, with keyboard-accessible expansion; desktop controls remain visible. |
| Medium | Amount formatting and ratio labels were difficult to scan. | Shared exact money grouping and Hebrew currency labels. Dashboard ratios display percentages rounded to two decimal places; the underlying values are unchanged. |
| Medium | Import context panels were too narrow and left an empty desktop column. | Two desktop context columns, one mobile column, isolated left-to-right date ranges, Hebrew statuses and coverage. Technical preview metadata remains expandable. |
| Medium | Native controls overflowed at 320px. | Fixed month-picker sizing and file-input sizing. Added live browser assertions at 320px. |
| Medium | Classification system explanations were in English. | Translated known system explanations, account-kind labels and issue descriptions. Original explanations remain in source details; custom household notes are preserved. |
| Low | Forecast preview caption said 36 months while showing 12. | Caption now reflects the displayed horizon. |
| Low | Settings was missing from desktop navigation. | Added the settings destination. |
| Low | Interface copy exposed Python/API implementation details or implied internet was required. | Plain Hebrew copy refers to the FamilyFin service; the apartment placeholder explicitly says it is still in development. |

## Verification

- Python: Ruff passed; 163 tests passed.
- Frontend: 3 API health tests and 38 component/formatting tests passed; lint has no errors; type checking and production-style local build passed.
- Browser: all 18 acceptance tests passed, including light/dark accessibility checks, RTL navigation, existing workflows and privacy/cache checks.
- Real local stack: the live integration test passed with external requests blocked and `navigator.onLine=false`; login, session refresh, multipart preview/commit, API-outage gating, recovery and logout passed using disposable data.
- Visual inspection covered dashboard, expenses, import/data quality, classification, planning, net worth, forecasts, operations, settings and the apartment placeholder. Checked desktop at 1440px, dashboard at 1063px, and the main financial screens at 390px. Dashboard and import also passed 320px checks. The mobile filter opened from the keyboard.
- No browser console errors were captured during the final review. Temporary viewport overrides were reset and the updated dashboard was left open.

The existing forecast `refreshAll` hook dependency lint warning remains. It does not fail lint/build. This review used Chromium on macOS; it does not certify Safari, Firefox or real mobile devices.

## Follow-up UI polish - 2026-10-02

This additional source pass addressed the remaining findings above. Planning and net-worth month/date labels now use readable Hebrew Gregorian dates, with their mixed-direction values isolated for RTL layout. The selected plan and monthly totals now precede source-import tools in the document order. Net-worth revision IDs and content hashes sit in a collapsed diagnostics disclosure; snapshot date, revision number, source type and saved time stay visible. Settings now formats FamilyBiz's date-only latest transaction value as a date while formatting import and session timestamps with their time.

Native month pickers still follow the browser/OS locale and can show English month names on this host.

### Checks run for this pass

- All 11 frontend component test files passed (41 tests), including Hebrew month/date output, settings date-only freshness, expandable net-worth diagnostics, and planning detail/monthly-before-import DOM order.
- Frontend lint passed with the existing `ForecastsFeature.refreshAll` hook dependency warning.
- Frontend type checking and `git diff --check` passed.

### Independent parent review

The polish was implemented by a GPT-6 Luna sub-session at maximum reasoning and then reviewed separately against a pre-session source snapshot. The review confirmed that API payloads, date-input values, financial decimal strings, authentication and availability gating were unchanged. The source tools remain accessible when no plan is selected.

The parent review corrected an existing first-month income caption that incorrectly described an average, stacked narrow net-worth section headers so descriptions use the full width, and enlarged the new diagnostic disclosure captions.

- Re-ran lint, all 41 component tests, production-style local build, type checking and all 18 browser acceptance tests after those final presentation corrections; all passed, with the existing lint warning noted above.
- The 3 API health tests and real live-stack integration test also passed in this pass. The latter used disposable data and blocked external browser requests, including `navigator.onLine=false`, login, session refresh, populated dashboard, multipart import preview/commit, outage gating/recovery and logout.
- Rebuilt and restarted the loopback synthetic demo for visual review. Planning, net worth and settings were inspected at desktop and narrow mobile widths. Planning and net-worth diagnostics were checked at 320px; no document overflow was found, and the diagnostic disclosure opened from the keyboard.
- Final manual checks also covered the net-worth comparison disclosure in the light theme. No browser console errors were captured. The original dark theme and default viewport were restored, and the planning page was left open with the synthetic demo running.
- Python tests were not re-run for this presentation-only follow-up; the earlier 163-test result belongs to the previous pass.

Apartment planning remains an existing unfinished module. No financial API contracts or database migrations were changed by this presentation pass.

## Dashboard clarity fixes - 3 October 2026

- Added an explicit reporting month. Cards, month-quality checks and contributor
  activity use that month; the graph has independent start/end controls. Currency
  applies to both scopes. Form submission reads the submitted native input values.
- Missing months show an import/coverage explanation rather than zero cards, and
  gaps in the graph. Verified covered zero-activity months still display zero.
- Added visible financial definitions, consolidated provisional comparison messages,
  a savings-rate explanation and links to the required quality checks.
- Historical 3/6-month averages use the latest eligible service-calculated window
  ending in the twelve months up to the reporting month. Each window shows its dates;
  unavailable windows list the incomplete months and their issues. No disjoint
  averages or financial equations were introduced.
- Separated period, household-account and classification coverage. Unclassified
  review links preselect month/currency/class before fetching the queue. Empty
  months do not claim classification completeness.
- Added numeric Y ticks, currency units and exact formatted point titles. Charts
  lay out at the available width, preserving readable labels on mobile; zero-only
  charts retain a nonnegative scale. Renamed
  raw diagnostic disclosures to “פרטים טכניים”; import timestamp and last observed
  transaction date have distinct labels.

Verification: 168 Python tests; Python lint; 47 frontend component tests and 3 health
checks; production-style local build; type checking; all 18 browser acceptance tests;
and the real-API integration suite passed. New cases cover covered zero vs missing
months/currencies, activity outside metric breakdowns, exact historical window labels,
independent reporting/graph scopes, scoped classification links and missing October
with the September trend still available. The existing ForecastsFeature `refreshAll`
React-hook lint warning remains. Automated writes used disposable data.

Manual review on the existing household development copy confirmed September cards,
missing October, the independently retained September graph range, and a classification
link showing September/ILS/unclassified with two queue items. Every month in the
October 2025–September 2026 history has unclassified transactions, explaining why no
complete consecutive average window exists. Mobile chart labels were inspected at
390px and document overflow checked at 390px and 320px. Financial records were not
changed during manual review.
The final desktop check extended the graph through October without changing the
September report, and confirmed that no October zero points were plotted. The graph
range was restored to September, the temporary viewport override was reset, and the
September overview was left open with the QA server running. No browser console
errors were captured in the final session.

## Dashboard comment follow-up - 3 October 2026

The five additional browser comments were implemented by a GPT-6 Luna session at
maximum reasoning and reviewed independently by the parent session.

- Replaced repeated provisional card links with one shared month-quality action.
  Card definitions remain visible; the savings-rate card retains its specific
  unavailable-state explanation. The shared banner only shows a quality anchor
  when its caller supplies a destination, avoiding broken anchors on expenses.
- Technical details show Hebrew issue explanations first. Raw diagnostic codes
  require a separate nested disclosure and remain available for troubleshooting.
- Chart tables now have metric rows and chronological month columns, with a sticky
  metric column, exact currency formatting, keyboard-accessible horizontal scrolling
  and distinct missing/zero values. Mobile table styles preserve actual table cells.
- Added service-calculated monthly mean, median and interpolated 25th/75th
  percentiles for the graph period. Every month has equal weight. Users can choose
  observed months (including provisional values) or complete months only; counts,
  exclusions and incomplete-month warnings explain the sample. Missing months never
  become zero observations. This is an additive API response field, with no migration.
- Explained the purpose and arithmetic of complete consecutive 3/6-month windows.
  Their eligible ending dates are the twelve months up to the reporting month;
  their start can precede that period. This differs from graph-period statistics,
  which do not require consecutive months.

Parent review additionally isolated the inline date range for RTL, simplified the
percentile explanation, and narrowed sticky labels so a full numeric month column
fits small mobile screens.

Automated verification: 175 Python tests and Ruff; 50 frontend component tests and
3 health checks; frontend lint, type checking and local production build; all 18
browser acceptance tests and the real-API browser integration suite passed. The live
test covers population switching, keyboard-focusable monthly matrix scrolling,
390/320px overflow, disconnected-internet auth/import, API outage recovery and logout
using disposable data. The existing ForecastsFeature hook dependency warning remains.

Manual parent review on the existing household development copy verified the single
quality action, Hebrew-first technical details, chronological horizontal matrix and
statistics population switch. Its twelve observed months are all incomplete, so
complete-only statistics correctly show an empty sample. Desktop widths of 944px and
1440px and mobile widths of 390px and 320px were inspected; the monthly matrix fits
a full value beside its sticky metric label at 320px. Both mobile sizes had no
document overflow, keyboard horizontal scrolling worked, and numeric statistics cells
did not repeat mobile labels. No console errors were captured. Financial records were
not changed. The temporary viewport override was reset and the updated QA app remains
running on loopback using the existing development copy.

## Classification save feedback - 3 October 2026

An override may be recorded successfully while the service keeps its effective
classification unclassified, for example when consumption is requested for a
positive amount. The editor previously discarded the mutation response and merely
refreshed, making this look like a save failure. It now reports the returned effective
classification, distinguishes stored-but-incompatible decisions from applied ones,
keeps incompatible decisions open for review, and explains sign conflicts in Hebrew.
Feedback survives the version-changing queue refresh, including a successfully
classified item disappearing from the unresolved queue. Existing sign-conflict cards
show direction guidance even after a page reload. Domain policy, financial amounts,
API contracts and persisted household decisions are unchanged by this UI fix.

Verification: 52 component tests, 3 health checks, lint, type checking, local production
build and all 19 browser acceptance tests passed. The added regression exercises an
HTTP-success response with an unclassified result, persistence through refresh, and
subsequent valid classification. The existing ForecastsFeature lint warning remains.
Manual review verified the existing PAYBOX sign-conflict guidance at 944px and 390px,
with no mobile document overflow or console errors. No household decisions were saved
during this review. The QA stack was rebuilt and restarted; the temporary viewport
was reset.

## Analysis category suggestions - 6 October 2026

The transaction override and reusable-rule editors now suggest categories from the
authenticated planning category endpoint, scoped by currency across the complete
transaction history rather than just the visible review page. Free text remains
available, and suggestions refresh after classification changes. Loading, empty and
failed lookups have Hebrew guidance. The lookup is separate from queue loading.

Native datalist suggestions remain available in supporting browsers. An explicit
category-choice control also exposes keyboard-accessible buttons because the Codex
in-app browser did not open the native datalist popup. Selecting a suggestion fills
the input, closes the choices and restores input focus. Adjacent form fields stay
aligned when choices expand. No API contracts or migrations changed.

Verification: 54 component tests, 3 health checks, lint, production build, type checking,
19 browser acceptance tests and the live API integration suite passed. Coverage includes
historical suggestions, currency scoping, failed lookups, choosing existing names,
new names in override/rule payloads, and refreshing suggestions after save. The existing
ForecastsFeature lint warning remains. The final layout adjustment was rebuilt and
reviewed manually on desktop and at 390px/320px with no document overflow. Both editors
were exercised with disposable synthetic data after the household browser session
expired. No classification changes were saved during visual review; no console errors
were captured. The temporary viewport was reset and the normal development copy restored.

## Transaction conflict resolution - 6 October 2026

The transaction editor compares imported and original amounts, preserves the saved
classification/category, and exposes an explicit debit/credit and amount correction.
It previews the report effect and requires a correction reason. Invalid direction
blocks Save; the API also rejects the decision without writes. A valid correction
updates reports and contributor amounts, disappears from the unresolved queue, and
can be undone through “ביטול תיקון וחזרה למקור”. Source records remain unchanged;
corrections, undo and actor audit use the existing append-only history. No migration
was added. If a later import changes source amount/currency fields, the previous
amount correction stops applying and the transaction returns for confirmation.

Verification: 177 Python tests and Ruff; 54 frontend component tests and 3 health
checks; lint, type checking and production build; 19 browser acceptance tests and
the live API integration suite passed. Disposable fixtures cover incompatible saved
decisions, explicit direction confirmation, unchanged source fields, corrected totals
and category reports, stale edits, changed source data, atomic audit and undo. Browser
coverage includes the correction panel at 390px and accessibility checks. The existing
ForecastsFeature hook dependency warning remains.

Manual review of the disposable live fixture verified the imported/original amount
comparison, previously saved category, explicit debit confirmation, report preview,
successful queue removal and undo. Desktop 944px and mobile 390px/320px layouts had
no document overflow; no console errors were captured. The temporary viewport was
reset and the normal QA app restored with the existing isolated development copy.
No household transaction decisions were changed.

## Reporting amount authority - 6 October 2026

Read-only source inspection confirmed 24 positive reporting amounts with negative
original values. “סכום” remains authoritative for amount and direction; “תנועה
מקורית” is metadata and cannot establish that a positive reporting amount is a debit.
The editor names both columns explicitly, identifies the reporting basis, and warns
against reversing a sign solely to match the original value. Original-value numeric
displays isolate direction so their minus sign is readable in the Hebrew layout.

Verification: 27 targeted parser/classification/API Python tests, Ruff, 55 frontend
component tests, lint, type checking and a local production build passed. New fixtures
verify reporting-sign preservation through import, bank income, card refunds, explicit
card income, metrics and an income-only editor save without an amount override.
The known ForecastsFeature lint warning remains. Visual review of disposable data
verified that selecting income keeps +72.4 and leaves amount correction unchecked.
No household transaction or override was changed; neither database has active amount
corrections. The normal QA app was restored with the isolated development copy.

## Reviewed zero-value rows - 6 October 2026

The classification editor adds “נבדק - ללא השפעה כספית” for confirmed zero-value
rows, such as an uncharged card administration fee. The option preserves the imported
amount and source row, removes the row from the default unresolved queue, and adds
nothing to financial totals or contributors. The source original-value warning is
preserved as provenance while explicit review resolves it in classification.
Nonzero imported or effective amounts cannot use this classification, including an
attempt to zero a charge via an amount override. A later nonzero source amount makes
the decision invalid and returns it to review. Save and undo retain actor audit and
optimistic concurrency protection. The new class uses existing text persistence;
no database migration was added.

Verification: 182 Python tests and Ruff; 56 frontend component tests; lint, type
checking and local production build; 20 browser acceptance tests and the real API
integration suite passed. Tests cover zero-fee save/undo, report and contributor
neutrality, unchanged source records, resolved classification completeness, rejecting
nonzero suppression, and re-review after changed source amounts. The known
ForecastsFeature lint warning remains. The final layout adjustment was rebuilt.
Manual review verified the full decision label at 944px, no document overflow at
390px/320px, and successful save on a disposable live fixture. No console errors were
captured. The temporary viewport was reset and normal QA restored. Household fee
rows were not classified automatically.
