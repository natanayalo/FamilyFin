# Monthly Clarity design QA


Source visual truth: `/Users/natanayalo/.codex/generated_images/01a1417a-9d4a-7a43-83ca-c0c68de30aaa/exec-2092d335-56c3-46b7-9f99-669aeef080a4.png` (first displayed ideation image, selected by user).
Implementation: http://127.0.0.1:3000/dashboard.

## Comparison history

### Iteration 1

Full-view comparison: `frontend/test-results/option-1-2026-10-16/comparison-iteration-1.jpg`; source on left, implementation on right. Implementation capture: `desktop-iteration-1.jpg` in the same folder. Source 1487×1058, normalized to 1440×1024; implementation 1440×1024 pixels/CSS viewport, density 1. Both show September 2026, authenticated, dark, RTL, collapsed detail. Source has synthetic figures; implementation uses actual development data and shows incomplete coverage.

- [P2] Month control used English browser text instead of Hebrew. Fix applied: explicit Hebrew month label over the accessible native month input, with an apply action shown only when the month draft changes. Confirmed in the final desktop/header comparison.
- [P2] Mobile headline currency wrapped onto a separate line. Evidence: initial browser inspection at 390×844. Fix applied: responsive value sizing, keeping each amount and currency together. Verified one-line values in subsequent mobile inspection, confirmed in mobile-final.jpg.
- [P2] “All monthly transactions” initially opened the unresolved-only classification queue. Fix applied: explicit include_resolved=true deep link and matching classification initialization; regression test added. Confirmed in browser: includeResolved checkbox checked after following the link.

Layout: three figures first, grouped bar/line chart second, review prompt third, concise recent-transactions table fourth. More detailed statistics and coverage remain in disclosures below. Standard Lucide icons replace text-glyph navigation. There are no raster assets in the selected target to generate; chart marks remain real data-driven chart primitives, not images.

Intentional constraints: retained existing product destinations instead of inventing income/goals pages from the generated mock. Retained an inline provisional-data statement, available cash caveat, and detailed quality/analysis tools. Uses actual service values, no fabricated percentages or reviewed states. Existing Noto Sans Hebrew and light/dark tokens retained.

## Required fidelity surfaces

- Typography: Noto Sans Hebrew 400/500/600; desktop title 30px, figure up to 38px; readable body and labels. Mobile numbers refined after wrap finding.
- Spacing/layout: slim 210px desktop sidebar, 32px page padding, three equal metric columns, lightweight separated transaction rows. Mobile reflows to two figures plus full-width surplus.
- Colors/tokens: pine/green base, mint surplus, green income bars, muted red expense bars, warning review state. Negative surplus uses expense color. Light theme uses existing corresponding tokens.
- Assets: library icons; no missing raster images, handmade icon glyphs, or placeholder image blocks in the redesigned surface.
- Copy/content: Hebrew month and financial labels, real figures and true incompleteness; no cash-availability claim. Category/refund semantics preserved.

- [P2] Tablet chart labels for the penultimate and last months collided when the final month was appended after a scheduled tick. Evidence: tablet browser view. Fix: omit a scheduled tick if it is too close to the final tick, keeping the final month visible. Added a spacing regression check.

## Final comparison and verification

No actionable P0/P1/P2 findings remain. The post-fix source/implementation comparison is
`frontend/test-results/option-1-2026-10-16/comparison-final.jpg` (source left,
implementation right). Focused type/control comparison is `comparison-header-final.jpg`
(source top, implementation bottom); focused review/table comparison is
`comparison-review-final.jpg`. These combined comparison artifacts were opened and
inspected, rather than relying only on separate captures or remembered mockups.

Final screenshots in that folder:

- `desktop-final.jpg`: 1440×1024 CSS viewport and pixels, density 1, September 2026,
  dark, authenticated, default collapsed details, twelve-month trend, actual service data.
- `mobile-final.jpg`: 390×844 CSS viewport and pixels. The first amount is at y=270px;
  all three figures fit above the chart; currency stays on the same line as its number.
- `tablet-final.jpg`: requested/measured CSS viewport 834×1194; native capture is
  834×1170, with the bottom 24px outside the captured area. No source-density comparison
  is claimed for this tablet image. Chart and primary controls are fully captured.
- `tablet-before-label-fix.jpg` retains the earlier crowded-axis evidence.

Source normalization remains 1487×1058 to 1440×1024 for the desktop comparison;
no semantic image content was changed. The tiny aspect difference is under 0.1%.
Mobile is a responsive adaptation; no separate mobile source was supplied.

The tablet chart now labels October, December, February, April, June, and September;
the closest observed label centers are 88.5px apart, with September retained.
The prior penultimate-label collision is resolved. A regression test verifies spacing
before the final month. Desktop and mobile full-view and focused inspection confirm
readable typography, consistent icon strokes, intact padding/radii, and no clipped
primary controls. Five recent rows are rendered; the final desktop row continues near
the viewport bottom as expected with actual transaction descriptions and the extra
provisional-data statement.

Browser interactions verified:

- Chart range changed to July–September without changing the selected September report.
- Next-month navigation selected October and showed a missing-data explanation, with
  no fabricated zero headline values. Previous-month navigation restored September.
- “All monthly transactions” reached classification with month=2026-09, currency=ILS,
  include_resolved=true, and the classified-rows checkbox checked.
- Review action reached the same month/currency with economic_class=unclassified.
- Inline quality link opened its native details section.
- Graph filter disclosure opens/closes on mobile; native month input remains accessible
  and has an explicit accessible name and visible focus treatment.
- 320px, 390px, and 834px checks found document width equal to viewport width.
- Final 390px page has one h1, three primary figures, and five recent transaction rows.
- No browser console errors observed. Household records were not saved during checks.

Verification: 66 component tests + 3 API-health tests pass; 3 targeted dashboard API
tests pass, covering authentication, private/no-store caching, ordering/limit, month
and currency scope, empty results, and existing dashboard behavior. Production build
and TypeScript validation pass. ESLint has no errors and retains the pre-existing
ForecastsFeature refreshAll dependency warning; Ruff and git diff --check pass.

## Accepted product constraints and follow-up polish

- Keep existing destinations and account/service controls; the generated mock's
  extra income/goals destinations are not invented. The compact month selector sits
  to the left of the title while preserving the same summary hierarchy.
- Actual amounts, long descriptions, source categories, incomplete coverage and
  exact decimal strings replace the mock's synthetic data. Unsupported percentage
  comparisons are withheld. The surplus remains explicitly distinct from bank cash.
- Existing pine tokens are slightly less saturated than the generated reference;
  this intentionally retains the product theme and light-mode compatibility.
- [P3] Source-style category-specific icons/colors can be considered when a stable
  category-to-icon mapping exists; free-form household categories currently use
  consistent readable pills.
- [P3] Touch targets on the compact month arrows can be enlarged in a later refinement.
- Light theme uses existing tokens, but this visual matching pass used the selected
  dark theme; no live household preference was changed just for QA.

## Implementation checklist

- [x] Three financial figures first; no duplicated dashboard page heading.
- [x] Compact Hebrew month selector, real data chart, scoped review and recent rows.
- [x] Coverage, statistics, comparisons, savings metrics and contributors retained.
- [x] Authenticated, scoped recent-transactions API and matching classified-row links.
- [x] Responsive figure wrapping and chart-label spacing fixed and recaptured.
- [x] Reference/implementation full-view and focused comparisons inspected.
- [x] Production preview left running and browser viewport reset.



## Hebrew money alignment follow-up

User references: `/var/folders/vx/r926hjxx7fn9bm86t8fdt9xw0000gn/T/codex-clipboard-d81aa43f-dabe-4ca6-b464-17db8ccc6924.png` and `/var/folders/vx/r926hjxx7fn9bm86t8fdt9xw0000gn/T/codex-clipboard-463be15d-9125-4b5d-a751-cf6140e0ad7f.png`.
These direct user corrections supersede the generated mock's currency ordering.

- [P2, fixed] Unisolated numeric text in an auto-direction bdi placed the minus
  sign after the digits. The shared exact-decimal formatter now uses an outer RTL
  isolate and an inner LTR numeric isolate, independently of surrounding direction.
  This also places the currency label to the left of the numeric run for Hebrew
  reading order. Missing/empty values remain ordinary Hebrew text.
- [P2, fixed] Overview transaction amounts and their column header were aligned
  left. They now align right. Shared dashboard amount cells and headline values
  use RTL/right alignment, including chart-data and statistics tables.
- Decimal digits, precision and grouping are unchanged; numeric inputs and stored
  values are unchanged. The formatter is shared by planning, net worth, forecasts,
  classification and dashboard displays.

Evidence: `frontend/test-results/hebrew-money-2026-10-16/before-desktop.jpg`,
`after-desktop.jpg` (both 1440×1024), and `after-mobile.jpg` (390×844).
Browser text-range geometry for the same -119 amount verified the correction:
previously minus x=85.43, first digit x=61.15 (sign after digits); after the fix
minus x=177.63, first digit x=182.10 (sign before digits). Currency x=163.35,
left of the numeric run; cell text-align=right. Expense contributor details also
verify a negative sign before the digits and right alignment in shared amount cells.
Mobile document width equals 390px and headline amounts remain on one line.
No browser console errors observed; no household records were changed.

74 component tests and 3 API-health tests pass. Tests cover the reported negative
values, zero/positive values, exact large decimal precision, and foreign/custom
currencies. Production build, TypeScript checks, lint (existing forecast warning)
and git diff --check pass. Browser-test expectations were updated for isolated money
strings and the current dashboard disclosures; the Playwright CLI suite was not run.



## Compact classification follow-up - passed

Existing classification code and the audit screenshots are the baseline; this
continues the selected overall direction without implementing option 3's separate
side-editor design. Secondary coverage, advanced filters and rule tools are now
native disclosures. Transactions use lightweight rows and one inline editor.

The initial all-history 50-row browser page measured 14,552px high, first row
at y=1087.6px. The first compact pass measured 6,382px and first row y=688.3px.
Source descriptions and monetary values are retained. Final page-header and primary-filter spacing refinements reduced the first-row position to y=567.2px and full page height to 6,236px, with all 50 rows retained. Tests for conditional
save semantics, rules, categories and selecting one editor pass.



Classification final evidence: `frontend/test-results/classification-2026-10-16/`.
`comparison.jpg` puts the baseline on the left and final implementation on the
right, both 1440×1024. It was opened and inspected. `after-desktop.jpg` shows the
compact default state; `after-mobile.jpg` shows the phone review list and
`editor-mobile.jpg` the inline editor. The desktop first transaction appears
520px earlier and the 50-row page is about 57% shorter. Existing pine tokens,
Noto Sans Hebrew, RTL money isolation, transaction content and financial meaning
remain consistent with the selected overall direction. Typography, section gaps,
row separators, control visibility and disclosure behavior were inspected.

[P2, fixed] A 320px check found a 314.5px intrinsic grid track extending outside
its content area, resulting in 331px document width. Root tracks now use
minmax(0,1fr), panels/fields allow shrinking, and the primary month filter uses a
bounded track. The final 320px browser check measured document width=320px with
50 rows loaded, both with the editor closed and with one editor open. No remaining
actionable P0/P1/P2 findings remain in this classification pass.

Browser checks: only one editor is open at a time; category input is reachable on
phone; advanced filters open/close and expose their controls; reusable rule tools
open and show the preview action. No real override, rule or household record was
saved. Final browser console check had no errors. 75 component tests plus 3 health
tests pass, including save/clear semantics, rule preconditions, category suggestions,
collapsed defaults and switching the selected editor. Production build, TypeScript
and lint pass with the existing forecast dependency warning. git diff --check passes.
The browser viewport is reset and the local classification preview remains open.

The single scheduled follow-up ran at 05:10 on 16 October 2026, Asia/Jerusalem,
and continued this checkpoint. No recurring follow-up was created.

final result: passed

## Expenses reconciliation follow-up - passed

Source visual truth for this extension: current-run baseline
`frontend/test-results/expenses-2026-10-16/01-before-desktop.jpg`, together with
the already selected Monthly Clarity direction and existing Noto Sans Hebrew,
pine/mint tokens, Lucide icons and responsive components. This is an authorized
clarity improvement to an existing screen, not a pixel clone of the old hierarchy.
Implementation: `/expenses`, authenticated, September 2026, dark theme, default
collapsed coverage/behavior sections. Final implementation capture:
`frontend/test-results/expenses-2026-10-16/10-desktop-final.jpg`.

Desktop source and implementation: 1440×1024 CSS viewport, devicePixelRatio=1;
native screenshots are both 1425×1013. No rescaling was used for the full comparison:
`comparison-final.jpg` (baseline left, implementation right). It was opened and
inspected. Native captures omit the scrollbar and a bottom strip; omitted regions
are not included in fidelity claims. Focused `comparison-summary.jpg` was opened
and inspected too: baseline summary above, new gross/refunds/net summary below.
The focused crops retain native scale and intentionally differ in height and
vertical placement because the summary hierarchy changed.

Findings and iteration history:

- [P2, fixed] Gross spending was not reconciled with refunds beside the summary.
  Three exact service totals now show gross, refunds, and net, with clear booking
  month semantics. Category totals are explicitly before refunds. No arithmetic
  or classification policy changed.
- [P2, fixed] Fixed/variable zeros appeared conclusive when behavior had not been
  assigned. The primary screen now explains the classification gap and links to
  the scoped review list; the behavior breakdown is secondary and describes amounts
  classified so far. It is hidden for months without data.
- [P2, fixed] Every category repeated identical unavailable comparison messages.
  Reasons are grouped once per period; only periods with available comparisons
  get table columns. Tests verify that valid comparisons remain visible.
- [P2, fixed] The first 390px capture put gross currency on a separate line.
  Evidence: 04-mobile-iteration-1.jpg. Reduced mobile padding/value sizing resolves
  the wrap in 05-mobile-final.jpg. At 320px, cards stack in 08-narrow-final.jpg.
- [P2, fixed] The initial category action loaded rows without a closing action.
  It now toggles the transaction region, exposes aria-expanded/aria-controls and
  changes the library chevron direction. Verified in browser and component tests.

Required fidelity surfaces:

- Typography: retains Noto Sans Hebrew and existing weights; summary headings are
  14px, desktop values up to 36px, body 13px. Exact numeric strings and bidi isolation
  are preserved. Current headline currency stays with its number on phone.
- Spacing/layout: 210px desktop sidebar, 28px/32px content padding, three equal
  summary columns; phone uses two supporting totals plus full-width net, stacking
  all three at 320px. Category rows and transaction content fit without document
  overflow. Both reported phone document widths equal their client widths.
- Colors/tokens: existing pine/card/line colors, mint net emphasis, existing warning
  border for classification gap. No new color palette or preference changes.
- Image quality/assets: no raster art is needed for this financial screen. Existing
  navigation icons and Lucide ChevronDown are preserved; bars and trends represent
  actual data. No decorative stand-in assets were introduced.
- Copy/content: explains gross/refunds/net, provisional data and unknown behavior
  distinctly; suppresses zero headline values for missing months. Available
  comparisons and diagnostic details remain accessible.

Browser steps: summary viewed; category transaction opened and closed on phone;
refund metric selected and its contributing transaction checked; coverage section
opened/closed; October tested as unavailable and September restored. Captures and
full numbered audit are in `docs/ui-expenses-2026-10-16.md`. No console errors were
observed. No household records were saved. Dark-theme Chromium desktop/phone
checks do not constitute a full accessibility, light-theme or Safari audit.

Verification: 79 component tests + 3 health tests pass; final targeted dashboard
suite (14 tests) passes after the last missing-month change. TypeScript and final
production build pass. Lint retains only the existing forecast dependency warning.

Checklist: summary reconciles; category drill-down scoped and reversible; valid
comparisons retained; unavailable reasons grouped; unknown behavior explained;
missing month not zero; 390px/320px reflow checked; combined full/focused comparisons
inspected. No actionable P0/P1/P2 findings remain in this bounded expenses pass.

final result: passed

## Hebrew report filters and account currency - passed

Scope: the user's supplied filter-bar screenshot and subsequent instruction to put
currency in general preferences. Source reference:
`/var/folders/vx/r926hjxx7fn9bm86t8fdt9xw0000gn/T/codex-clipboard-157452a9-d715-4d82-b49c-2dad2349baed.png`.
Current-run full baseline: `frontend/test-results/hebrew-filters-2026-10-16/01-before.jpg`.
Final expenses capture: `07-desktop-final.jpg` in that folder. Both native images
are 1425×1013 from a 1440×1024 CSS viewport at density 1. No density rescaling was
used. Native screenshots omit the scrollbar and bottom strip. Combined full-view
comparison `comparison-final.jpg` (before left, after right) and focused controls
comparison `comparison-controls.jpg` (before above, after below) were opened and
inspected. This scoped change preserves the existing page and financial values.

Changes and iteration findings:

- Removed the free-text currency control from report filters. The existing saved
  per-account currency preference remains in Settings, with an explanation that
  it filters original-currency transactions rather than converting amounts.
- Fixed stale in-memory report filters overriding a newly saved preference.
  Successful preference saves clear the remembered report scope; the next report
  requests the API's saved defaults. A navigation regression test verifies a prior
  ILS filter cannot override a newly saved USD preference, including a later date
  change. Existing nonstandard saved currency codes remain selectable in Settings.
- Replaced browser-localized native month inputs with Hebrew month selects and
  separately labeled numeric year fields. Applying a period preserves the server's
  currency. Invalid/incomplete years and reversed ranges are rejected in Hebrew.
- [P2, fixed] First phone capture squeezed month labels beside 96px year fields.
  `04-phone.jpg` records the issue. Fields stack in `05-phone-final.jpg` (390×844
  CSS, native 375×812) and `06-narrow-final.jpg` (320×844 CSS, native 305×804).
- [P2, fixed] A separate Overview mobile rule retained two narrow columns.
  `10-overview-narrow.jpg` records the issue. It now expands in normal document
  flow with stacked fields; `11-overview-narrow-final.jpg` shows readable months
  in 219px controls at 320px. Document and client widths are both 305px.
- [P2, fixed] Adding the Settings explanation stretched its neighboring select.
  `03-settings.jpg` records the issue; start alignment fixes it in
  `08-settings-final.jpg`. The explanation is linked via aria-describedby and is
  separate from the select's accessible name.

Required fidelity surfaces: existing Noto Sans Hebrew, weights and pine/mint tokens
are preserved; labels are 13px and controls 14px with 44px height. RTL month names
and LTR year digits have distinct fields. Borders/radii follow the existing controls;
desktop content hierarchy and money formatting are unchanged. No raster images or
replacement icon assets are needed. Copy distinguishes report period, saved account
preferences, original currency and conversion. The date options themselves are in
Hebrew, independently of browser locale.

Browser steps checked: Expenses period changed using Hebrew controls and the real
report's month options updated; original October–September range restored; Settings
preference and explanation inspected without saving a changed personal preference;
390px/320px Expenses expansion inspected; desktop and 320px Overview expansion
inspected and repaired. No browser console errors observed. No financial records or
personal preferences were changed during browser checks. Full accessibility,
screen-reader, light-theme and Safari checks were not performed. Save/navigation
behavior was exercised with test fixtures rather than changing the user's currency.

Validation: 82 component tests + 3 health tests pass, including Hebrew period
submission, invalid years/reversed ranges, preserving currency, and preference
navigation. All 12 focused dashboard/settings API tests pass, covering saved account
defaults and currency scoping. TypeScript, final production build and diff checks
pass. Lint retains the existing forecast dependency warning. Updated browser-test
locators were typechecked; the Playwright CLI suite was not run.

Checklist: Hebrew controls; currency only in main preferences; saved defaults
respected on return; no conversion implied; both responsive consumers inspected;
full and focused comparisons inspected. No actionable P0/P1/P2 findings remain.

final result: passed



## Independent expense month and trend range - passed

Source: current-run `frontend/test-results/expense-scopes-2026-10-16/01-before.jpg`
and the user's instruction to separate monthly reporting from historical context.
Implementation: `/expenses`, September 2026, dark, authenticated. Final capture:
`09-desktop-final.jpg` in the same folder. Desktop CSS viewport is 1440×1024,
density 1; native before/after images are both 1425×1013. No rescaling was used.
Native captures omit the scrollbar and bottom strip. Full comparison
`comparison-final.jpg` (before left, after right) and focused
`comparison-month-control.jpg` (before above, after below) were opened and inspected.

The primary Hebrew month/year control now selects a single report month. Monthly
summary, coverage, categories, behavior, comparisons and transaction details use a
separate single-month API request. The range control is next to the chart and
labeled “טווח המגמה”. It updates historical series and explicitly labeled period
insights. The chart tracks the top five categories from the report month across
that historical range. Monthly calculations and financial policy are unchanged.

Browser verification:

1. Report month and summary - passed. September opens with one month control and
   a statement that the summary, categories and transactions belong to that month.
2. Independent chart range - passed. Changing the range to June–August left the
   full September summary text unchanged. Chart labels show June, July and August;
   categories and chart caption still identify September. Evidence:
   `03-independent-range.jpg`.
3. Independent report month - passed. Choosing August updates monthly figures and
   exposes August alone in transaction activity, retaining the June–August range.
   Evidence: `04-report-month.jpg`.
4. Missing month - passed. October shows unavailable values rather than zeros;
   the historical range remains selected. With no categories for that report month,
   the category chart explains that it has no categories to plot. Historical period
   insights remain available. Evidence: `05-missing-month.jpg`.
5. Responsive controls - passed. `06-phone.jpg` uses 390×844 CSS (375×812 native);
   `07-narrow.jpg` and `08-narrow-range.jpg` use 320×844 CSS (305×804 native).
   Main month and expanded chart-range fields fit; document width equals client
   width at both sizes. Original report month/range restored after checks.

Fidelity surfaces: Noto Sans Hebrew and existing 13–14px supporting/control text
are retained; desktop month control and caption form one compact row, with stacked
phone fields and clear 44px actions. Pine, mint, border and warning tokens remain
unchanged. No image assets or decorative approximations are introduced. Copy now
states monthly versus historical scope beside the applicable controls and labels
historical insights with their actual applied period. Exact monetary precision,
RTL isolation and currency behavior are preserved. No actionable P0/P1/P2 visual
findings remain in this scoped change.

Validation: 84 component + 3 health tests pass; TypeScript and production build
pass, retaining the existing forecast lint warning. New regression tests verify
that range changes do not refetch or replace the monthly report, that changing the
report month preserves the range, and that an absent month does not become zero.
Two existing asynchronous test assertions were stabilized: classification feedback
is queried again as its DOM location changes, and the settings test waits for report
draft initialization before applying dates. No classification product behavior
changed. No new backend calculations or API routes were added.

No browser console errors observed. No household records or saved preferences were
changed. Full screen-reader, contrast, light-theme, Safari and physical-device checks
were not performed. The preview remains local and open for the user.

final result: passed

## Shared Hebrew month picker - passed

Source: the user's compact Overview selector screenshot
`/var/folders/vx/r926hjxx7fn9bm86t8fdt9xw0000gn/T/codex-clipboard-9c28dcd4-926e-4906-a8f8-7844a7d7aa19.png`
(286×79 source pixels), plus current-run Overview baseline
`frontend/test-results/shared-month-picker-2026-10-16/01-before.jpg`.
Implementation: authenticated local `/dashboard`, September 2026, dark theme.
The closed-state desktop baseline and final `10-desktop-final-closed.jpg` both use
1440×1024 CSS at density 1 and have 1425×1013 native captures. Native captures
omit the scrollbar and bottom strip; screenshots were not rescaled for comparison.

Opened and inspected `comparison-full.jpg` with the full baseline/final together,
then `comparison-control.jpg` with the original user reference, implemented compact
control, and opened calendar together. The closed control preserves the original
48px height, Hebrew month and year, calendar icon, right previous/left next arrows,
existing font and color tokens. Its measured width is 230px. The additional
interaction state intentionally has no source calendar image to compare against.
The popover uses the installed Base UI components and Lucide icons; no packages or
image assets were added.

The shared component now handles Overview, Expenses, both historical-range
boundaries, classification, scenario start, assumption timing, and history/CSV
planning start months. Values remain canonical YYYY-MM strings. Exact-day date
fields retain day precision. Report month selection applies immediately; historical
ranges retain explicit Apply so both boundaries can be edited together. Transaction
breakdowns show a fixed Hebrew month label in place of a single-option dropdown.
Existing independent month/range scopes, saved currency, money precision and
calculation policy are preserved.

Visual iteration 1: desktop, 390px and 320px captures were reviewed. P2 finding:
at 320×844, the initial 296px popup extended to x=308 while the document client
width was 305px, clipping its right edge against the scrollbar. Evidence:
`07-narrow-calendar.jpg`. Result was held until repaired.

Visual iteration 2: constrained the popup by Base UI's actual available width and
height, with internal vertical scrolling for short viewports. Rebuilt and recaptured
at the same 320×844 viewport and September Expenses state. Final bounds are
x=12, width=281, right=293 inside the 305px client width. Document scroll width
also remains 305px. Opened `comparison-mobile.jpg` with the before/after 320px
captures, final 390px Expenses, and final 320px Overview together. No actionable
P0/P1/P2 findings remain in this scope.

Browser checks:

- Opening the calendar shows all 12 Hebrew months and the selected month highlight.
- Browsing 2027 leaves the September 2026 report selected. Escape closes the popup
  and restores focus to its trigger; reopening returns to the selected year.
- RTL ArrowRight moves September focus to August; Enter selects August and updates
  actual report values. The October 2025–September 2026 trend range stays unchanged.
  Next-month arrow restores September. Outside-click dismissal also passes.
- Expenses uses the same picker and updates monthly data on selection. The trend
  filter endpoints use the same calendar within the existing range disclosure.
  Evidence: `04-trend-calendar.jpg`, `05-expenses-calendar.jpg`.
- Classification can select September and clear to “כל החודשים”, with no records
  edited. Evidence: `08-classification-calendar.jpg` (opened and inspected).
- Planning in an unsaved draft disables months after its 12-month horizon and
  disables year navigation beyond that horizon. Evidence: `09-planning-calendar.jpg`
  (opened and inspected). The agent-created draft was discarded without saving.
- Final 320px and 390px calendars fit and remain readable. At 640×400 the popup
  constrains itself to available height and scrolls internally. Evidence:
  `12-narrow-final-calendar.jpg`, `13-short-viewport.jpg`,
  `14-phone-final-calendar.jpg`, `16-overview-narrow-calendar.jpg`.
- Transaction breakdown scope is displayed as a fixed Hebrew month and remains
  aligned with its selected report. Evidence: `15-breakdown-month.jpg`.

Validation: all 89 component tests + 3 health tests pass. TypeScript and production
build pass. The build retains the pre-existing ForecastsFeature useEffect warning.
New tests cover year rollover, canonical submitted values, year browsing without
selection, Escape/focus restoration, RTL keyboard movement, bounds and clearing.
Report tests exercise calendar selection while preserving independent scopes;
planning validation still focuses/describes reversed ranges through the new trigger.
The live Playwright spec was updated for the calendar UI but was not run through
the CLI; browser verification above used the existing in-app browser. No console
errors observed during the browser checks. Full screen-reader, light-theme,
contrast audit, Safari and physical-device checks were not performed.

All screenshots remain private local ignored artifacts. No household records or
saved preferences were changed. Original report months and historical scope were
restored. The preview remains running locally for the user.

final result: passed

## Unified expense categories and transactions - passed

Source: the existing Expenses screen and the user's accepted direction to combine
category browsing with one filtered transaction table. Current-run captures:
`frontend/test-results/unified-expenses-2026-10-16/01-before.jpg`,
`02-before-transactions.jpg`, and `03-before-top.jpg`. Implementation: local
`/expenses`, authenticated, dark, September 2026. Desktop CSS viewport 1440×1024,
density 1; baseline/final native captures are both 1425×1013. Native captures omit
the scrollbar and bottom strip. No rescaling was used to compose comparisons.

Opened and inspected `comparison-full.jpg` (baseline/final top views together),
`comparison-flow.jpg` (original category actions and separate transaction selector,
then the merged implementation), and `comparison-phone-fix.jpg` (navigation fix).
The focused flow comparison uses original-pixel crops at their respective document
positions. The new screenshot intentionally selects groceries, demonstrating the
new filtering behavior; the original separate transaction view was collapsed.
These interaction/layout differences are the requested change, not fidelity errors.

The category summary and primary transaction table now share one panel. Category
buttons filter the table, show selection, and move focus to its heading. “כל
הקטגוריות” or the clear action removes the category filter. The table loads once
for the report month, with explicit “הוצאות והחזרים”, “הוצאות בלבד”, and “החזרים
בלבד” controls. The broad metric selector and separate monthly transaction section
were removed from Expenses. Category totals remain gross expenses before refunds.
Refund rows are filtered by their own classification/category and recorded month;
refund-only categories remain available through the all-category refunds view.
No purchase/refund matching or new money calculations were added.

The first six expense categories are visible initially; all categories can be
expanded. A selected category outside the first six stays visible when collapsed.
The four-column table shows date, description, category and exact original amount;
transaction type/account appear below the description. It sorts newest first and
paginates ten rows at a time. The existing independent historical trend is below
this unified monthly section. Typography, dark theme, money isolation/precision,
month selector and financial summaries retain existing app tokens and behavior.

Visual iteration 1: desktop flow and 390px layout reviewed. P2 finding: selecting a
category on the phone scrolled only enough to show the table heading, leaving its
rows below the fixed bottom navigation. Evidence: `09-phone-transactions.jpg`.
Result held until the navigation was fixed. Also addressed a P3 mouse-focus style
that made the programmatically focused heading resemble an input, and adapted the
expanded historical-range controls to their new full-width panel.

Visual iteration 2: category selection now focuses without native scrolling, then
scrolls the table heading to the start with a 20px margin. Rebuilt and repeated the
same groceries/both-types action at 390×844 CSS. Heading measured at y=20.22px;
filters, scope and the first transaction rows are visible. Native before/after
images are both 375×812 and were inspected together in `comparison-phone-fix.jpg`.
Final 320×844 check uses 305px client width and 305px document scroll width, with
wrapped mode labels and readable refund details. Evidence: `10-phone-final.jpg`,
`11-narrow-refunds.jpg`. No actionable P0/P1/P2 findings remain in this scope.

Browser checks:

- Default September loads 46 expense/refund transactions in one primary table.
  Category clicks update that table without opening another table. Groceries shows
  five rows; keyboard Enter activation and heading focus also pass.
- Groceries plus refunds shows an explicit scoped empty state. Clearing the category
  while keeping refunds selected shows September's single refund, whose category
  has no gross expenses. Evidence: `06-empty-category.jpg`, `07-refunds.jpg`.
- Pagination advances to page 2; choosing a category resets to page 1. Expanding all
  18 expense categories, selecting Spotify and collapsing retains its selected row.
- Switching to August resets category/type filters and loads August dates only.
  Returning to September restores the September dataset. No financial records edited.
- Applying a trend end of August leaves the report month at September and the table
  at 46 transactions. Chart labels end at August. Original September trend endpoint
  restored and verified in the rendered chart. Expanded range fields fit their
  desktop row. Evidence: `12-trend-controls.jpg`.
- `14-desktop-final.jpg` shows the linked groceries category and five table rows.
  Source and implementation screenshots were inspected as described above. No
  browser console errors observed.

Validation: all 94 component + 3 health tests pass, as do TypeScript and production
build. Full ESLint has no errors and retains only the existing ForecastsFeature
useEffect warning. New tests cover combined category/type filtering, negative
refund classification, refund-only categories, scoped empty results, pagination,
100-ID batching, discarding failed partial batches, retry and late month responses.
Existing report tests still cover independent month/range scopes. Historical e2e
selectors were adapted for the automatically loaded table; CLI browser tests were
not run. No backend, schema or financial calculation changes were required.

All evidence is private local ignored output. No household records or saved
preferences changed. The original September report and October 2025–September 2026
historical range were restored; the groceries filter is left selected as a visible
example. Full screen-reader, light-theme, contrast audit, Safari and physical-device
checks were not performed. The preview remains available locally.

final result: passed


## Expenses secondary-analysis cleanup - 17 October 2026

Implemented the agreed progressive disclosure after the unified monthly table work.
The monthly summary, warnings, category/transaction panel and independent trend stay
in the primary flow. Below the trend, “תובנות ופירוט נוסף” is closed by default.
Opening it reveals independently collapsible topics: coverage/quality, fixed versus
variable classification, category comparisons, possible recurring patterns and
unusual category changes. Monthly topics name the selected report month; historical
topics show the applied trend range. Counts summarize available findings. The visible
incomplete-month warning now links directly to coverage and opens both containing
disclosures. Unknown-behavior warnings remain visible in the primary flow.
Native details/summary preserves keyboard activation and semantic grouping.
No API, schema, financial formula or household record changes were made.

Evidence: `frontend/test-results/expense-cleanup-2026-10-17/` (ignored local output).
The private browser login expired, so browser verification used an isolated copy of
the frontend, a temporary database, and synthetic local fixtures on localhost:3101.
Private preview cookies on 127.0.0.1 and household data were kept separate. Baseline
and updated builds used the same original three-row fixture for captures 01–09.
Captures 10–12 use six additional synthetic July–September rows to exercise two
populated recurring patterns and their three-transaction contributor drilldowns.
The final copy correction handles singular finding counts in Hebrew; its focused
17-test suite passes. The two-finding screenshots are unaffected by that correction.

Visual comparison inputs were composed and opened together:

- `comparison-top.jpg`: full native 02-before-top versus 03-after-top, same dataset,
  viewport and initial state. Primary totals, typography, sidebar, month control,
  exact amounts and category/transaction content are preserved. The redundant
  quality card moved into the secondary group; its warning shortcut stays above.
- `comparison-secondary.jpg`: full native 01-before versus 05-desktop-collapsed,
  same dataset and bottom-of-page position. Intentional difference: formerly
  separate comparison and historical panels collapse into one secondary row.
  This reduces the default page length while keeping the trend directly available.
- `12-desktop-final.jpg` and `11-narrow-patterns.jpg` opened at native size to check
  the expanded group hierarchy, Hebrew wrapping, money, topic spacing and populated
  contributor rows. Desktop captures are 1440×1015 pixels from a 1440×1024 CSS
  viewport. Phone captures are 390×844; narrow captures are 320×844. No screenshot
  scaling was applied before composition. The combined artifacts were automatically
  downsampled by the viewer; original native captures were also inspected.

Visual iteration 1: reviewed primary and secondary desktop surfaces, 390px and
320px layouts. No actionable P0/P1/P2 visual findings remain in this scope. Existing
app colors, type, borders, precision and money-direction isolation are retained.
The five disclosure topics, report/trend scope distinction, warning placement,
keyboard focus, and empty/populated states were checked. No unsupported new visual
assets or new interaction conventions were introduced.

Browser verification:

- Secondary group and all topic bodies start closed. Enter and Space toggle the
  outer summary. Each topic opens independently with a visible focus indication.
- “פרטי כיסוי ואיכות” opens the outer group and coverage topic only; source coverage,
  classification and reconciliation details remain reachable. Closing the group
  leaves the monthly warning in the primary view.
- Empty pattern/change explanations and unavailable comparison reasons render.
  With populated fixtures, two patterns use two columns on desktop and one column
  on phones. A pattern contributor drilldown loads all three historical dates.
- At 390px and 320px the document width equals the viewport width. Labels, monthly
  behavior amounts and contributor rows wrap readably without horizontal overflow.
- The primary table remains monthly while historical details use the applied range.
  Final browser console error list is empty.

Validation: all 95 component tests and 3 health tests pass; TypeScript passes.
The final singular-copy correction also passes the 17 dashboard feature tests.
Production build passes after that correction and the normal preview is running.
ESLint has no errors and only the existing ForecastsFeature refreshAll hook warning.
The e2e spec was adapted to open the secondary groups; CLI browser tests were not
run. Private household data could not be visually rechecked because sign-in expired;
all current browser interaction evidence uses clearly synthetic test data. Full
screen-reader, light theme, contrast, Safari and physical-device checks are outside
this pass. No household records or saved preferences changed.

final result: passed


### Household-data verification after sign-in - 17 October 2026

The user completed sign-in following the optional browser request. Rechecked the
normal 127.0.0.1:3000 Expenses preview with household data. This resolves the
expired-session verification limitation from the preceding pass. September totals
remain gross 24,757.79 ILS, refunds 988 ILS and net 23,769.79 ILS; the primary table
shows 46 monthly transactions. Thirteen historical patterns appear under the
independent applied October 2025–September 2026 range. The warning shortcut opens
only the outer group and quality topic. Other analysis topics remain closed.
Actual incomplete-source and classification warnings are visible and readable.

Inspected native screenshots 13-household-top, 14-household-quality,
15-household-narrow-patterns and 16-household-details in the same ignored evidence
folder. The household browser has a conventional scrollbar: desktop captures are
1425×1013 at 1440×1024 CSS; narrow captures are 305×804 at 320×844 CSS. At 320px,
document and client widths are both 305px. Long real historical month lists and
Hebrew/Latin merchant labels wrap; amounts and range boundaries remain readable.
No new actionable P0/P1/P2 visual findings or browser console errors observed.
No code, records or saved preferences changed in this follow-up. Original report
month and trend range preserved. Outer detail group is left open with its topics
closed as an example. The earlier test results remain applicable.

final result: passed


## Recurring decisions and expense explanations - 17 October 2026

Implemented the user's approved scope: persist household approval/dismissal of
recurring patterns, stop tracking, restore to review, clarify fixed/variable
classification, and replace unexplained comparison gaps with actionable reasons.
Approved decisions remain accessible outside the selected detection window.
Current observations replace saved evidence when the same identity is detected;
otherwise the card explicitly labels its saved evidence. Decisions are independent
of transaction classification, totals, forecasts, payments and alert rules.

Source visual truth: existing signed-in household Expenses screen, captured before
edits as `01-comparison-before.jpg`, `02-patterns-before.jpg` and
`03-patterns-first-before.jpg`. Implementation evidence is in
`frontend/test-results/expense-actions-2026-10-17/` (private ignored output).
Desktop source and implementation captures are both 1425×1013 native pixels at
1440×1024 CSS. Narrow synthetic previews are 305×804 native pixels at 320×844 CSS;
client/document widths both 305px. All composition uses native pixel density with
no source scaling. The browser viewer downsampled the large composed full views;
native captures and the focused comparison were also opened and inspected.

Opened source and implementation together in `compare-unavailable.jpg` and
`compare-patterns.jpg`. Same household data, September report, applied October
2025–September 2026 history, dark theme and expanded corresponding topic. The
comparison view is anchored at the page bottom; new content intentionally moves
the upper headings above that viewport. Pattern captures bring the first merchant
heading into view; the added controls intentionally increase card height.
`compare-patterns-focus.jpg` aligns native Google One card crops and makes retained
financial text, the new status label and decision actions readable together.

Visual iteration 1: no actionable P0/P1/P2 discrepancies found against the existing
screen plus the agreed changes. Five fidelity surfaces reviewed explicitly:

- Typography: existing Hebrew font, weights, heading levels and money isolation
  retained. Long merchant names, month lists, help text and labels wrap at 320px.
- Spacing/layout: existing two-column cards on desktop; one column on narrow
  screens. Mode buttons and approval actions stack on phones. Minimum 40px action
  heights, clear grouped spacing, no horizontal overflow, visible keyboard focus.
- Colors/tokens: existing card/muted backgrounds, borders, mint selected states,
  primary/outline buttons and warning styles reused. No new palette introduced.
- Asset fidelity: existing shared components and icons retained. No new imagery
  required or fabricated.
- Copy/content: detector rule explained, saved household decisions distinguished
  from classifications, fixed/variable examples added, and incomplete comparisons
  name current source/classification blockers with specific navigation links.

Functional browser checks used an isolated temporary database at localhost:3101
with two synthetic recurring patterns. Approve → approved view, dismiss → previous
decisions, stop tracking → previous decisions, and restore → pending all persisted
through the real authenticated/CSRF-protected API. Reload retained decisions.
Changing only report month retained the approved state without refreshing history.
Shortening the applied history to end in August left fewer than three observed
months: detection became empty while the approved saved expense remained visible
with its saved-evidence explanation. Original September report and trend endpoint
were restored. Keyboard Enter switched views; Tab showed visible action focus.
Screenshots 04–06 and 11–12 record these states. The temporary build differs from
final only in the neutral introductory detector-rule wording; final wording is
verified on the normal household preview in 09–10.

Normal household preview: 13 pending patterns, zero saved decisions; no household
pattern was approved or dismissed during verification. September amounts and 46
monthly transactions remain unchanged. Screenshot 07 shows the explicit unavailable
state, partial/unknown monthly source coverage and two unclassified transactions.
The coverage link opens the correct topic; classification link preserves September,
ILS and unclassified scope. Screenshot 08 shows fixed/variable examples and the
classification link. Screenshots 09–10 show real pattern cards with the new actions.
Narrow screenshots 13–14 verify wrapped comparison reasons/links. Error lists from
both browser tabs are empty. Viewport overrides reset after verification.

Validation: 101 component + 3 health tests pass, with a final 23-test focused rerun
after the neutral copy correction. Six dashboard/recurring API tests and 31 detector,
operations and automation/backup regressions pass. API checks cover persistence,
stable identity across ranges, cross-household-login visibility, currency separation,
unchanged metrics/behavior, CSRF/auth/schema/state validation and rollback on audit
failure. A new UI regression covers preserving decisions across report-month changes.
Failure/retry and duplicate-submission behavior is covered by component tests.
Final production build and TypeScript validation pass. ESLint has no errors; only
the existing forecast refreshAll hook warning remains. E2e fixture has a stable
pattern ID; CLI browser suite was not run. Full screen-reader, light-theme,
contrast, Safari and physical-device tests remain outside this pass.

Migration 0014 adds only the review table/index; real transaction/classification
records and saved preferences were preserved. All mutation walkthroughs used the
synthetic account. Documentation records the new request and response contract.
Implementation checklist complete for the agreed scope.

final result: passed


## Net Worth hierarchy, setup and Hebrew money - 17 October 2026

Source visual truth: current-run QA captures in
`frontend/test-results/net-worth-design-2026-10-17/`: 01-populated-before,
02-empty-before and 03-accounts-before. Existing option 1 styling is retained while
implementing the user's requested Net Worth refinement. Implementation: local
http://localhost:3101/net-worth, captures 06/10 (empty) and 15–20 (populated/editor).
The initial sign-in image and transient phone capture were rejected; accepted
sources and final captures show loaded application content.

Normalization: desktop source and final are both 1280×720 native pixels at
1280×720 CSS. Phone comparison pairs are both 320×844 native pixels at 320×844 CSS;
390×844 was also checked. No image scaling occurred before composition. The
large combined desktop images were downsampled by the tool viewer; native images
and focused card crops were separately inspected. Same dark theme, route, QA
household, snapshot date and amounts. Empty screenshots have zero accounts; populated
screenshots use the same eight-account/three-snapshot fixture. The initial end-to-end
single-account test was discarded by restarting only its disposable QA stack.

Source and implementation were opened together in these comparison inputs:
compare-empty-desktop.jpg, compare-populated-desktop.jpg,
compare-setup-phone.jpg, compare-money-phone.jpg, compare-headline-focus.jpg.
Full views establish hierarchy and intended changes; the focused headline band
makes precision, currency placement, type size, color and wrapping directly readable.

Iteration 1 findings held the result blocked:
- P2 setup: the first action was below all explanatory steps on a 320px phone.
  Evidence 05-empty-narrow-first-pass. Moved the action before the step list.
- P2 money: currency wrapped on the desktop emphasis card and decimal digits split
  inside two narrow phone cards. Evidence 11-populated-final-desktop (intermediate)
  and 12-populated-320-first-pass. Reduced the emphasis size, used smaller secondary
  figures at 390px and stacked all three cards at 320px.

Final post-fix evidence: 10-empty-final-320, 15-populated-final-desktop,
16-populated-final-320, 17-balances-phone, 18-populated-390, 19-light-phone,
20-final-editor-phone. Setup action bounds are y=507.32–543.32 at 320×844.
Client and document widths match at both 320 and 390. The three 320px headline
amounts each occupy one line (native bdi heights 38px, 32.5px, 32.5px) and fit their
cards. Combined before/after inputs were inspected after these corrections.
No actionable P0/P1/P2 finding remains.

Required fidelity surfaces:
- Fonts/typography: retained Noto Sans Hebrew and shared weights; removed the
  duplicate inner title, established summary/setup headings, reused shared exact
  Hebrew currency formatting and isolates. Long names, complete decimals, dates
  and mobile form labels wrap appropriately. Revision headings use Hebrew dates.
- Spacing/layout: existing card radii, borders and gaps retained. Primary totals,
  dated account balances and trend precede collapsed management. Native setup
  steps, one first-use action and automatic editor focus make the next step clear.
- Colors/tokens: existing brand/mint/card colors reused. Warning/notice/error
  colors now respect theme tokens instead of fixed light backgrounds. A light
  phone state was inspected and dark mode restored. No quantitative contrast claim.
- Image/assets: no raster assets required. Existing icon library and native
  controls are used; no drawn substitutes or decorative assets were introduced.
- Copy/content: measured date and source scope explicit, assets/debts separated,
  ownership gross aggregation described accurately, missing balances distinguished
  from zero and duplicate measurement dates linked to the revision route.

Functional browser checks: completed first account and first snapshot through the
real isolated API; observed the expected 12,345.67 ILS result. Then reseeded eight
accounts and three dated snapshots in a fresh disposable database. September
selection shows September totals and balances; current October is restored.
Duplicate-date creation is disabled with a revision alternative; the revision
prefills current saved balances. Final test drafts cancelled. Native details
supports Enter toggling; form entry focus and visible focus states checked.
Both browser console error lists are empty. Household data was never mutated.

105 component + 3 health tests pass, with a final passing 12-test focused rerun.
New regression coverage includes setup progression, default-collapsed management,
exact values, duplicate-date revision routing and ignoring late summary responses.
Original stale-revision/concurrency, account-version and decimal-string tests pass.
TypeScript and final build pass. ESLint has no errors and only the pre-existing
forecast hook warning. No backend financial logic or schema changed. CLI e2e,
full screen-reader certification, quantitative contrast, physical devices and
Safari/Firefox certification were not performed. Full flow notes and accepted
screenshots: docs/ui-net-worth-2026-10-17.md.

Implementation checklist complete for the requested Net Worth refinement.

final result: passed

### Final Net Worth tablet checkpoint - 17 October 2026

A further 768×1024 check reopened the visual result for a P2: the three-card row
wrapped the currency onto a second line (21-tablet-check.jpg). Changed only the
621–1100px layout to two columns, with net worth across the full first row.
Rebuilt the production app and refreshed a newly seeded isolated QA stack.

22-tablet-final.jpg shows all three amounts and currencies on one line. Their
headline heights are 40.59px / 31.90px / 31.90px; document and client widths both
equal 768px. Opened compare-money-tablet.jpg with source and corrected implementation
together, both native 768×1024, same dark theme, route, fixture, date and amounts.
Typography, token colors, spacing, content and existing icon assets remain
consistent with the accepted desktop/phone views. No actionable P0/P1/P2 remains.
Both QA browser error lists are empty; viewport override reset and QA preview kept
open. Final production build and git diff check pass; prior 108 frontend tests and
final 12-test Net Worth rerun remain applicable to this CSS-only correction.

final result: passed

## Planning refinement - 17 October 2026

Source truth: current-run screenshots under
/Users/natanayalo/dev/FamilyFin/frontend/test-results/planning-design-2026-10-17/:
01-empty-before, 02-editor-before, 03-populated-before and 04-actual-before
(the last is a full-top populated view, not actuals evidence). Existing application
code, shared MonthPicker and the previously selected option 1 tokens are the target.
This is an intentional scoped refinement, not a new visual direction or exact clone.
Implementation: http://localhost:3101/planning; 05–06 setup, 09 phone summary,
17–19 actuals/editor, 21–22 tablet/themes, 23 final desktop, 24 final comparison.
All accepted saved images were opened and inspected; no login/loading state accepted.

Normalization: source/final desktop screenshots are native 1280×720 at 1280×720 CSS.
The phone iteration pair is native 390×844 at 390×844 CSS. Tablet 768×1024 and
320×844 states were also checked. No scaling before composition. Desktop combined
images are 2580×754 and viewer-downsampled to 2048×599; native images and focused
crops were separately opened. Both populated comparison states use dark theme,
same QA five-item plan, September selected, revision 1 and matching amounts.
The final capture was made before creating its QA clone. Empty pair has zero plans.

Opened combined comparisons: compare-empty.jpg, compare-month-desktop.jpg,
compare-month-desktop-final.jpg, compare-month-phone.jpg, compare-money-focus.jpg.
Full views establish hierarchy/spacing. Focused money crops use the original
03 y596–683 band and final summary y515–636 band without stretching: changes in
font size, emphasis and the replacement of assumption count with savings/remaining
are intentional. Content and card sizes differ as requested, not density artifacts.

Iteration findings/fixes:
- P2: first-pass phone summary had no monetary amount visible above navigation
  (08-month-phone-first-pass). Compacted scenario controls and made remaining money
  the first card. 09-month-phone-final and opened compare-month-phone verify the
  result at the same 390×844 viewport, October state and dataset. The 5,000.25
  remainder is fully visible above navigation. Result was held until this recheck.
- Keyboard cancel check found focus lost while the create button was disabled.
  Return focus now runs after the editor closes; final-build DOM/AX confirms focus
  on תרחיש חדש. Covered by a component regression test.
- Increased secondary comparison/history text after inspecting the rendered results.
  Final 24-comparison-final confirms readable scenario names and monetary lines.

Required fidelity surfaces:
- Fonts/typography: retained Noto Sans Hebrew and shared weights. Monthly heading,
  22px desktop/24px phone totals and 12–14px details establish the same hierarchy.
  Shared exact money formatting retains signs/decimals and Hebrew currency isolation.
  Whole headline values fit desktop/tablet/phone; 320px actuals remain readable.
- Spacing/layout: retained theme cards, radii and gaps, with compact scenario controls.
  Remaining money first; actual comparison next; annual/admin sections collapsed.
  Phone edit fields, sticky actions and fixed app navigation fit without horizontal
  document overflow. Document/client widths equal 320 and 768 in measured checks.
- Colors/tokens: retained mint emphasis, card/background and semantic warning tokens.
  Light tablet and dark phone/desktop were inspected; restored dark QA preference.
  No quantitative contrast certification claimed.
- Image/assets: no raster assets required. Existing MonthPicker and Lucide chevron
  are reused; no substitute artwork, custom SVG or decorative assets introduced.
- Copy/content: one selected month governs plan and actuals, remaining balance formula
  is explicit, partial actuals visibly qualified, missing actuals preserved as unavailable,
  all-scenario assumptions labeled as such. Archive restore action text corrected.

Functional checks: real first-plan save returns expected 2,500.25; shared calendar
selects November deficit; September partial and November missing actuals verified;
edit/cancel and native Enter disclosures work. Clone plus comparison loads both
selected scenarios without refresh/reset. Final preview has original plan/October,
no draft, collapsed tools, default viewport and dark theme. Both QA console error
lists are empty. Household records unchanged. tests/qa_planning.py is opt-in,
temporary-path guarded and refuses existing scenarios; guard smoke checks pass.

113 component + 3 health tests pass; 10 Planning cases cover the monthly view,
partial/complete actuals, revision mismatch, late responses, comparison choices,
new-draft horizon, validation and returned focus. Final production build and full
lint pass with only the existing forecast hook warning. No backend/API/math changes.
CLI e2e, complete-coverage browser fixture, full import/restore flows, full screen-reader
certification, quantitative contrast and physical/Safari/Firefox tests not performed.
Complete flow report: docs/ui-planning-2026-10-17.md.

No actionable P0/P1/P2 remains for this scope. Implementation checklist complete.

final result: passed

## Savings Forecast refinement - 17 October 2026

Source truth: current-run screenshots in
/Users/natanayalo/dev/FamilyFin/frontend/test-results/forecast-design-2026-10-17/:
01-empty-before, 02-editor-before, 03-populated-before, 04-results-before.
Existing code, selected option 1 language and shared MonthPicker are the visual
reference. This is an intentional refinement, not a new visual direction or clone.
Implementation: http://localhost:3101/savings-forecast; 05–08 setup, 16–19 chart/
opening/tablet/themes, 23-final-desktop, 24-preview-layout-final. Saved files were
opened and inspected; login/loading states were not accepted as evidence.

Normalization: desktop source/final are native 1280×720 at 1280×720 CSS. The chart
iteration pair is native 320×844 at 320×844 CSS. Also inspected 390×844 and 768×1024.
No image scaling before composition. Desktop composites 2580×754 were downsampled
by the viewer to 2048×599; native captures and focused money crops were inspected
separately. Source/final populated state is dark theme, same route, forecast name,
36-month baseline, 42,000.25 opening, 4,000 monthly deposits and revision 1. Temporary
record IDs differ after fixture recreation; displayed assumptions and totals match.
Empty comparison has Planning present and no forecasts on both sides.

Opened combined comparison inputs: compare-empty.jpg, compare-populated-final.jpg,
compare-chart-phone.jpg, compare-preview-final.jpg, compare-preview-money-focus.jpg.
Full views establish hierarchy and proportions. Focused preview crops use the actual
22 y425–570 and 24 y425–655 money bands, native scale without stretching. Both are
36-month 4% previews with the same balances and totals; one was a QA copy and the
other the base fixture, without a visible identity difference in the compared region.

Iteration record (result held until fixes and post-fix inspection):
- P2 chart: leading scale digits clipped at 320px (14). Made the chart respond to
  its container, reduced redundant axis text and placed the currency/scale key
  above it. Capture 16 and combined chart pair show complete labels.
- P2 opening form: pool inputs used a three-column grid inside a half-width card
  and obscured the Hebrew pool name (08). Local two-column layout, one on phone;
  capture 17 shows the complete name, amount and date.
- P1 saved editing: actual API rejected the saved pool_id returned by the read
  model (21). Forecast write serialization now whitelists editable pool fields.
  Preview/create/save regression cases preserve precision and source/quality fields.
  Real edited preview, revision-2 save, historical inspection and revision-3 restore
  all succeeded. No schema relaxation or backend calculation change.
- P2 nested preview: currency wrapped below the number in a narrow emphasis card
  (22). Two-column desktop preview and one-column phone layout; capture 24 plus
  full/focused combined comparisons verify all values and currency on one line.

Required fidelity surfaces:
- Fonts/typography: retained Noto Sans Hebrew and shared weights. Main heading
  hierarchy replaces the duplicate feature title. Readable 13px explanatory text,
  22px desktop/26px phone totals and responsive chart text; signs, decimals and
  Hebrew currency use the exact shared formatter. Complete monetary values fit.
- Spacing/layout: existing 16px radii, theme surfaces and gaps retained. Compact
  forecast selection, primary result, case comparison, chart and one selected
  month's flow precede management. Opening and preview grids respond to their
  narrower context. Native dates, disclosures, editor actions and phone navigation
  remain usable; measured narrow document/client width both equal 320.
- Colors/tokens: mint emphasis and semantic warning/error/notice tokens retained.
  Chart colors use theme variables with readable dark variants. Light tablet and
  dark desktop/phone were opened; QA dark preference restored. No measured contrast
  compliance claim.
- Assets/image quality: reused existing Lucide chevron and the product's data chart;
  no raster assets, decorative substitutes or new custom artwork required. Existing
  chart is still rendered from service projection data and now resizes to its slot.
- Copy/content: starting capital, cumulative contributions and assumed returns are
  distinct; swept surplus and funded forecast withdrawals are explicit. Missing
  checkpoints stay unavailable rather than showing a single month's totals. Shortfall
  warnings respect the selected period. Full Hebrew months replace numeric offsets
  in user-facing event/adjustment controls while transport offsets remain unchanged.
  Source template recurrence, historical versions and scenario-wide return assumption
  are stated plainly; no promised returns or measured-balance implication.

Functional evidence: completed first create through real QA API; changed case and
12/36-month periods; calendar selected November as forecast month 3; renamed pool
routes remained connected. After the transport fix, editing 3% to 4% recalculated
196,287.09 to 199,808.92. Save required renewed confirmations; QA copy revisions and
restore worked. Final CSS-only preview correction was rechecked in the final build.
No draft pending, base revision 1/baseline/36 months restored, management collapsed,
viewport override reset, dark theme, and both final QA console error lists empty.
Household financial data/preferences unchanged. QA seed path/repeat guards tested.

128 frontend tests pass (125 component +3 health), full TypeScript/lint and production
build pass. CLI e2e was not run; fixtures updated for changed disclosures and copy.
No backend engine/API-schema/database-schema changes. Full screen-reader/contrast,
physical devices, alternate browsers, every import/quality path and all auth-loss
browser scenarios were not certified. Full report: docs/ui-forecasts-2026-10-17.md.

No actionable P0/P1/P2 remains in the requested scope. Implementation checklist complete.

final result: passed

## Statistics clarity · 18 October 2026

Source truth: selected option 1's existing FamilyFin surfaces and current-run baseline
`frontend/test-results/statistics-design-2026-10-18/03-populated-before.jpg`.
Implementation: same directory `09-summary-final.jpg` (same source data/range/state),
`19-final-desktop.jpg` (final meaningful Jan–Aug2026 sample), `20-final-tablet.jpg`,
`21-final-phone390.jpg`, `22-exact-phone320.jpg`. Browser route: localhost:3101,
Overview → Statistics disclosure. Full report: docs/ui-statistics-2026-10-18.md.

Source/implementation full views are1280×720 CSS/pixels at1x; the combined
`compare-hierarchy.jpg` is2580×754 and its viewer downsampled to2048×599. Native
aligned panel-top comparison `compare-hierarchy-focus.jpg` is2032×422, with two
1006×388 crops. Full-view scroll positions differ; matched panel crops ground the
intentional hierarchy change. Both use the same Oct2025–Sep2026 period, observed
12-month population with one partial month, ILS and dark theme. Final Jan–Aug2026
captures deliberately use a different range and are not used for value fidelity.

First-pass comparison evidence08 (320×844) versus corrected14 (320×844), same August
review/July comparison data: `compare-difference-labels.jpg`, two286×250 crops at1x.
Enclosing summary population differs, outside the compared region. Finding[P2]: bare
numbers did not say difference versus prior amount. Fixed by explicit Hebrew labels;
post-fix combined comparison opened/accepted. Hebrew singular agreement fixed in
population warnings. Finding[P2]: date application reset complete-only silently;
selection now survives request unmount, verified in browser and integration test.
Final screenshots16/17 distinguish incomplete and missing months;18 shows missing
period coexisting with valid, independently scoped August comparisons.

Required surfaces checked: Noto Sans Hebrew/weights/line-height and money wrapping;
12–16px layout rhythm, 3 desktop cards and stacked responsive structure; existing
mint/dark/light tokens and warning semantics; no image assets required/replaced;
Hebrew copy/date/scope/definitions and explicit difference labels. Normal money rounds
exactly to2decimal display places; service precision remains optional and unchanged.
No actionable P0/P1/P2 remains. P3: unavailable comparison cards could use less unused
height when beside a populated comparison.

Interactions: observed/complete, graph/review independent changes, empty/missing,
exact-table disclosure, source-month lists, 3/6-window selection semantics, keyboard
Enter disclosure/radio arrows/contained table ArrowLeft. Viewports1280×720,768×1024,
390×844,320×844; light/dark inspected, default reset. At320 document width320,
exact table region254 with620internal scroll; keyboard scrollLeft became-39.5.
Final browser console errors[]. Full frontend137tests, final focused28, backend
Statistics7, typecheck/lint/QA+main production builds/diff check pass. No CLI e2e,
physical-device/multiple-engine/screen-reader or full contrast certification. No
financial engine/schema change; only disposable QA records mutated.

Implementation checklist complete: useful averages first; optional detail; visible
coverage; separate month scopes; clear comparisons; safe empty states; stable choice;
responsive Hebrew amounts; exact display; focused regressions; browser proof and
handoff. Main52450/QA60344 running; QA tab1 retained, dark/default viewport.

final result: passed

## Data Quality/import clarity - 18 October 2026

Source visual truth: existing selected option 1 FamilyFin design, captured before edits
at `frontend/test-results/data-quality-design-2026-10-18/01-before.jpg`.
Implementation: `20-final-desktop.jpg` in that folder, http://localhost:3101/data-quality.
This is a scoped improvement of the existing app: information hierarchy/copy changes
are intentional, while Noto Hebrew, dark/mint tokens, shell, cards and controls remain
consistent with the selected product design.

### Evidence and normalization

- Source and final desktop both 1280x720 CSS/pixels, DPR 1, dark, authenticated synthetic
  household, top of `/data-quality`, no pending import, no open reconciliation cases.
  Source had 19 accepted transactions; the final isolated copy has 20 after a verified
  import. Both have one partial source month, two unclassified transactions and 72.4 ILS
  absolute review amount. The extra accepted transaction/history dates are expected
  test changes, not visual mismatches; no pixel claims depend on those values.
- Full-view combined input `compare-desktop.jpg`: source 01 beside final 20, native size
  with labels/padding,2580x754. Opened and inspected; tool display resizes the combined
  preview to 2048x599, while originals were separately inspected at 1280x720.
- Focused money/type input `compare-money-focus.jpg`: source crop(500,475,980,720)
  and final crop(360,348,660,592), padded without stretching,980x279. Opened and inspected.
- Matching invalid-file 320x844 states 08 vs19 in `compare-validation-phone.jpg`,660x878,
  opened and inspected. Same synthetic invalid workbook; random request ID is now
  hidden by default. Final history is open in 19 and closed in 08; below-form differences
  are excluded from conclusions about the error region.
- Responsive originals05/06/13 are 390x844;07/14/19 are 320x844;11/12 are 768x1024.
  Fresh empty household 15 is 1280x720 and 16 is 390x844. These new states are functional
  verification, not falsely paired against the populated source. An initial transient
  scaled empty-phone capture was rejected and replaced with stable 390x844 evidence.

### Findings and iteration history

- P1, before 01: first/last transaction dates presented as covered period and identical
  incomplete-month labels gave no remediation. Replaced with separate service-backed
  source/classification/reconciliation checks and specific month actions. Relevant
  complete assessments are optional; account coverage stays explicitly unknown.
  Final20 plus month/tablet11 show the revised hierarchy. Intentional redesign accepted.
- P2, first pass 02: singular Hebrew heading read `1 חודשים`, and the browser file picker
  exposed English text. Final 04/20 use natural singular wording; custom Hebrew file
  button appears in 19 and empty 15. Original native input and accepted type remain.
- P2, candidate selection: pre-fix DOM width 415 at 390px (10 captured the adjacent import
  area, not a valid screenshot of the candidate layout). Fixed grid/label/select intrinsic
  minimum widths. Revised actual candidate screenshots 13/14 show controls/source money
  inside the card; DOM width verified 390/390 and 320/320. No assertion of a screenshot
  before/after candidate comparison is made from 10.
- P2, invalid-file 08: support UUID was as prominent as the corrective message. Collapsed
  support details in 19; combined 08/19 evidence confirms reduced noise and readable action.
- P2, empty API assessment: no-import households receive 12 source-missing checks. New first
  use guidance avoids repeating 12 identical negative rows or implying completeness.
  Fresh empty household 15/16 inspected and accepted.
- No actionable P0/P1/P2 findings remain. No change was made solely from build success;
  final browser renders and state transitions were checked after fixes.

### Five required fidelity surfaces

- **Fonts/typography:** retained Noto Sans Hebrew. Final DOM confirms h1 = 34px/600;
  check text = 14px, 23.8px line height. Native paired captures show consistent letterforms,
  readable Hebrew body copy, correct wrapping and no clipped amounts/signs. Singular
  counts use Hebrew phrases; long internal IDs live in optional details.
- **Spacing/layout rhythm:** retained rounded cards,18px stack spacing and existing shell.
  Three task cards on desktop, one readable column on tablet/phone. Top import CTA remains
  accessible on phones. Candidate selects and history now fit 320px; document width equals
  viewport in checked states. Source-to-task hierarchy changes are intentional.
- **Colors/tokens:** existing dark/mint card/primary/muted/warning tokens retained. Success
  uses a calm muted notice; correction warnings retain readable semantic treatment.
  Light tablet 12 and dark phone/desktop inspected. No full contrast certification claimed.
- **Image quality/assets:** no new raster art or custom icon approximation. Existing wordmark,
  app shell and library icons remain intact; this slice is text/forms/data. No missing assets.
- **Copy/content:** checked range and ILS scope explicit. Source-period checks do not prove
  household account coverage. Missing data is not labeled zero. Preview/commit/duplicate
  consequences and reconciliation choices are clear; diagnostic/provenance content remains
  accessible. Money uses exact existing Hebrew bidi helper (72.4 and negative 17.4 inspected).

### Interaction checks and limits

In-app browser tested first use, populated/partial months, complete-month disclosure by
keyboard, month-specific classification handoff, Hebrew file chooser, warning/duplicate
preview, explicit successful import, invalid XLSX, explicit matching and candidate choices,
saved reconciliation, history disclosure,320/390/768/1280 widths and light/dark. Final
console errors []. Viewport/theme reset; clean Data Quality tab retained as deliverable.

143 frontend tests, 34 quality/import backend tests plus 3 existing dashboard API tests,
typecheck, frontend lint, touched Python Ruff, production build and diff check pass.
Unknown import outcome, locked idempotent decision retry, failed loads and refresh ordering
have meaningful component/API coverage. CLI Playwright not run; two e2e assertions updated
for new copy. Physical browsers/devices, full screen-reader/contrast certification and
browser network-fault replay injection remain unverified. No outstanding implementation
fix is inferred from those test limits.

Implementation checklist complete: month assessments; remediation hierarchy; first use;
preview and validation; explicit reconciliation; responsive controls; tests; evidence;
main/QA runtime; household preservation; handoff documentation.

final result: passed

### Data Quality independent-review follow-up - 19 October 2026

P2: initial request failure showed an unavailable history summary and a contradictory
empty-history table. Corrected with an explicit never-loaded history state; genuine
empty results require a successful response. Refresh failure keeps prior records,
clearly labeled as potentially stale, including previously empty snapshots.

Twelve focused Data Quality component tests pass, including four new regressions for
loading, initial failure, genuine empty success and both cached refresh-failure cases.
Typecheck, frontend lint, production build and diff check pass. No styles, service
math, API or database changes. The earlier accepted screenshots remain the visual
reference for this narrowly scoped state correction.

Browser evidence for the correction is currently blocked in the subagent: CUA lists
no browser surfaces and cannot create the in-app tab. Parent verification was requested
using an isolated read-only failure preview. No new screenshot/console pass is claimed.
This follow-up result does not invalidate the historical completed main-screen QA above.

Follow-up browser verification remains pending.

final result: blocked

Parent follow-up: independently reviewed corrected history code and reran all 12
focused component tests successfully; normal QA3101 loads correctly. The temporary
503 fault preview triggered global reconnect, so it was not accepted as evidence of
the inline history error. That narrow browser state remains unverified. Fault preview
88773 stopped; main91677 and normal QA37714 preserved. No further visual/app changes.

## Final cross-app consistency pass - 19 October 2026

Reference: selected option1 and current built screens, captured before edits in
`frontend/test-results/final-app-qa-2026-10-19/`. Full report and route/state matrix:
`docs/ui-final-qa-2026-10-19.md`. Only narrowly scoped defects/consistency were changed.

Findings resolved: P2 unnamed tablet navigation, P2 unlabeled Apartment availability,
P2 Operations pending/failed reads shown as empty or permanent loading, P2 unreadable
dark Operations/Settings error banners, P2 Settings failed loading without retry,
P2 squeezed Classification calendar at320px, P3 stretched empty Statistics card.

Comparison inputs opened together: Apartment02→14, Settings tablet11→16, Statistics
12→13, Operations dark error20→24, Settings failed loading26→30, Classification33→34.
Same viewport/theme/data/state within each pair, original screenshot density; native
error and availability crops resolve small copy. Statistics retains identical August
review/October–September graph/observed population. Tablet naming is proven by live
AX and hidden-label regression, not appearance. All final comparisons accepted.

Required surfaces: existing Noto typography and readable money retained; spacing follows
the shell with purposeful narrow-filter stacking and content-height comparison cards;
theme tokens retained and dark error palette reused from existing form feedback;
no new images/custom art; Hebrew copy distinguishes development/loading/failed/empty/stale
and never invents currency conversion or data completeness. Existing icon library used.

Live IAB checks: desktop1280×720, tablet768×1024, phone320/390×844; selected light/dark;
month calendar RTL arrows/selection/Escape/focus, More Escape/navigation, month-specific
quality→classification handoff, apartment→NetWorth link, large and negative money,
loading/initial failure/stale/recovery. Final320classification document width320; other
checked narrow states also equal viewport width. No financial writes were performed.

GET-only proxy verified previous Data Quality inline history failure with synthetic400,
which now explicitly cannot determine whether imports exist. This closes the earlier
narrow browser gap. Deliberate503 invokes intended global reconnect, hides financial
content and only restores it after authenticated retry;401 returns to sign-in. The
proxy forwarded only synthetic QA reads and is now stopped. No weakening of privacy,
authentication or unknown-outcome guards.

153 frontend tests(150component+3health), typecheck, full lint, final production build,
and diff check pass. Six meaningful new state/navigation regressions. Corrected a
pre-existing test race by waiting for the unchanged recurring-pattern focus effect.
No backend changes/test claims or CLIPlaywright runs. No physical-browser/device,
full screen-reader, full contrast, zoom/reduced-motion or uncertain-mutation replay
certification. Remaining minor age-wording P3 is documented; Apartment calculator and
broader Automation redesign are separate work.

Main20703 and QA44249 run final code with unchanged dev/synthetic data respectively;
fault25790 stopped. Dark/default viewport, QA tab1 retained as deliverable on Apartment
availability; final console errors[]. Existing work, real household data/preferences
preserved. Next route import restored.

final result: passed

### Operations parent-review correction - 19 October 2026

Remaining P2: failed run feedback was cleared by automatic successful status refresh.
`runError` and `statusError` are now independent. Only a new explicit run clears old
action feedback; automatic/manual reads cannot erase it. Unknown actual-run outcomes
warn that the operation may have completed and direct history/file checks. Client
rejection and failed dry-run guidance remain distinct. No automatic mutation retry.
Fresh/pending/failed status still independently determines action readiness.

Regression reproduced the missing alert before correction. Three new cases cover
failed action plus successful automatic/manual refresh and explicit retry clearing,
HTTP400/500 outcomes, and subsequent failed/successful status reads. All26 focused
tests, typecheck, full lint, production build and diff check pass. No backend change,
real automation execution or full-suite rerun; earlier153 result remains historical.

Browser follow-up is blocked: former handle2 unavailable and fresh inventory has no
browsers. The prepared review proxy rejected ALL POSTs locally and forwarded only
QA GETs; it has been stopped. No mutation reached a backend. No new screenshot,
visual run-error result or console check is claimed; parent37 is Apartment only.
This narrow visual limit does not invalidate the earlier cross-app screenshot QA.
Normal previews run final code; runtime33731main /59233QA, data preserved.

Functional correction: passed. Browser design-QA follow-up remains unavailable.

final result: blocked


Parent closeout - 19 October 2026. Independently reviewed the Operations correction:
runError is separate from statusError; automatic/manual reads preserve action feedback,
only an explicit new run clears it, and unknown outcomes never imply no writes occurred.
No further Operations code change needed. Full frontend suite rerun: 156 passed
(153 component +3 health), typecheck/lint and production build passed. Existing
regressions cover failed run followed by successful/failed automatic/manual reads.

Fixed remaining Hebrew age wording in shared formatHebrewDaysAgo, Settings and Net
Worth: zero → לפני פחות מיום, one → לפני יום, two → לפני יומיים, plural unchanged.
Unknown Net Worth age explicitly says מועד המדידה אינו ידוע. Service day counts,
dates, money and data remain unchanged. Formatter smoke-checked at 0/1/2/8; no new
copy-only tests. Settings live AX confirmed the corrected zero-day label before
browser access was lost. 38-age-before.jpg is accepted before evidence; the first
39-age-after.jpg capture did not frame the label and is rejected as visual evidence.
The Mac subsequently locked; CUA inventory is empty and reports manual unlock is
needed. Final live run-error verification and matched visual age comparison remain
blocked by that lock; no successful action-error screenshot claimed.

Main and QA rebuilt on final source, preserved household and synthetic DB/archives.
Tool reconnection lost launcher exec handles; verified actual listeners: main web
28291/API28240 on3000/8000, QA web28297/API28237 on3101/8101. Existing npm parents
28254/28255 remain serving. Temporary rejection-only proxy exited; its leftover
3102 npm/server28317/28339 were explicitly stopped, no8102 listener. No automation
was executed. QA project /var/folders/vx/r926hjxx7fn9bm86t8fdt9xw0000gn/T/familyfin-final-copy-ui-mcleedb6;
quality/finalqa/expense pointers updated; same QA root, not reseeded. Generated
next-env import restored to.next/types/routes.d.ts. Preserve all uncommitted work.


Browser closeout - 20 October 2026. Mac unlocked; parent completed the previously
blocked live checks in IAB with the synthetic QA household. Settings shows לפני יומיים
for its current two-day service age; Net Worth shows נמדד לפני 3 ימים with unchanged
1,534,751.00 net worth. Accepted/opened screenshot40-age-verified.jpg captures the
Settings correction; elapsed day count differs from before38, so this is wording
verification, not an identical-date-state comparison.

Started the existing local rejection-only proxy for browser verification (session72661).
Every POST is rejected locally and never forwarded; only QA GETs are forwarded.
A synthetic400 run rejection remained visible after the automatic status/history
refresh and after explicit manual רענון. Accepted/opened41-run-error-after-refresh.jpg
shows readable light-theme error feedback and refreshed status. No automation or
financial mutation executed. Stopped proxy72661 successfully; normal main/QA remain.
Unknown500/network outcomes retain component coverage; this live check is specifically
400 rejection persistence. The prior Mac-lock/browser gap is now closed. Broader
physical-device/other-browser/accessibility certification remains outside this scope.
No new app code changes or repeated suite claimed; prior156 tests/typecheck/lint/build
and subsequent43 focused tests are passing. Parent QA tab retained on normal3101/net-worth,
dark/default viewport, no draft. Docs/handoff updated; all uncommitted work preserved.
