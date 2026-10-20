# Final cross-app QA · 19 October 2026

This pass continues the selected option 1 design and existing Hebrew/mint/Noto system. It is a scoped consistency and defect pass, not a new feature redesign. All browser work used the preserved isolated QA household. No financial records, household preferences, parser, engine, schema, import decisions, classifications or automation runs were changed.

## Findings and corrections

1. **P2 · Tablet navigation lost accessible names.** At 768px `.nav-text` becomes `display:none` and icons are `aria-hidden`, leaving all ten rail destinations unnamed. Confirmed in the live accessibility tree before changes. Each shared navigation link now has a persistent explicit accessible name and a hover title. The live final tree names all ten destinations at 768px. A regression hides the labels with the actual CSS rule and verifies all destinations remain named.
2. **P2 · Apartment Planning looked available before entry.** Desktop navigation and mobile More now show `בפיתוח`; the compact rail also carries the badge. The accessible name includes availability. The existing direct route remains accessible and explains that no purchase/mortgage calculator is available, with working links to Net Worth and Planning. No calculator, estimated result or new route was built. Evidence: `02` → `14`, `15`, `18`, `19`; `compare-apartment.jpg` and native `compare-apartment-nav-focus.jpg`.
3. **P2 · Operations confused pending/failed reads with empty results.** File/history state is now explicitly never-loaded until successful reads. Pending reads show loading; failed initial reads show unavailable guidance; failed refreshes retain prior data with stale wording, including previously empty results. Failed status no longer keeps claiming loading. Refresh controls prevent duplicate pending reads; automation controls cannot act on pending/failed status. No automation was executed. Two new tests failed against the old implementation before the fix; three regressions cover pending→empty, initial failure, and cached-empty refresh failure. Live read-only proxy verified loading (`22`), initial failure (`20/21`, final `24`), recovery and stale cached results (`25`).
4. **P2 · Dark error banners were difficult to read.** Operations and Settings combined pale danger text with hard-coded near-white error surfaces. Operations failure was captured before correction (`20`) and compared with the same 1280×720 dark failure state after correction (`24`). Both classes now use the established dark form-error surface/text/border treatment. `compare-operations-error.jpg` and native `compare-error-focus.jpg` show the readability fix. Settings final failure checked at 390px (`30`). This is not a full contrast certification.
5. **P2 · Settings stayed loading after a failed initial read.** A real injected request failure reproduced simultaneous error and permanent loading (`26`). Explicit loading state now ends on failure and exposes a retry (`30`). Retry was successfully used to load preferences again (`31`), without saving or changing them. Component regression covers pending, failure, retry and successful recovery.
6. **P2 · Narrow Classification month selector was squeezed.** The month+currency columns left too little room for the shared calendar label/icon/arrows at 320px (`33`). The primary filters stack below 400px, giving the shared month control its full width. This is a caller layout correction; shared date/value behavior is unchanged.
7. **P3 · Unavailable Statistics comparison stretched to its neighbor's height.** The comparison grid now aligns cards to their content. Missing previous-year data remains unavailable, without a large empty card. `12` → `13` / `compare-statistics.jpg` use identical August review, October–September range, observed population, QA data, dark theme, viewport and scroll alignment. No calculations changed.

## Cross-app walkthrough and evidence

All numbered screenshots were captured, saved and opened in this run under ignored `frontend/test-results/final-app-qa-2026-10-19/`.

| Step | Surface and state | Result / evidence |
| --- | --- | --- |
| 1 | Data Quality, desktop | Clear source/account distinctions and partial-month actions retained. `01`. |
| 2 | Apartment entry | Development availability visible before entry; explicit direct-route explanation and working alternatives. `02`, `14/15`, `18/19`. |
| 3 | Overview, desktop / phone | Correct negative money and partial-month caveat. Complete August comparisons preserved. `03`, `12/13`, `28`. |
| 4 | Expenses, 320px | Month control fits, calendar opens, RTL ArrowRight moves September→August, Enter selects and restores trigger focus. Correct 20,000.25 and negative transaction signs. `04/05`; live DOM verified. |
| 5 | Mobile navigation | All destinations reachable in More; Escape closes and restores focus; navigation closes the disclosure. `06`, `18`; component regression. |
| 6 | Net Worth, 320px | 1,534,751.00 net / 2,182,751.00 assets / 648,000 debt fit; stale valuation warning retained. `07`. Apartment alternative successfully opens this screen. |
| 7 | Planning, 320px | Shared month next control switches October→November; deficit -3,999.75 remains intact. `08`. No plan was saved. |
| 8 | Savings Forecast, 390px | Selected baseline/36 months, 196,287.09 closing, horizon and source controls fit. `09`. No forecast draft/save. |
| 9 | Classification, 390/320px | Queue and opened editor fit document width; imported sign distinction retained. Data Quality action lands on September/ILS (2 pending). `10`, `33` and final narrow-control evidence. No transaction saved. |
| 10 | Settings, 768/390px | Tablet light/dark inspected; currency explicitly filters original-currency transactions without conversion. Failed read/retry/recovery verified. `11`, `16/17`, `26`, `30/31`. No preference save/revoke. |
| 11 | Operations, read-only | Initial loading, successful empty, failed initial, failed cached refresh and recovery verified. `20/21`, `22`, `24/25`. No dry run or mutation. |
| 12 | Data Quality failed history | Previously unverified inline failure now visually verified using a synthetic 400 history response. It explicitly says existence of imports cannot be determined; no false empty claim (`23`). A 503 deliberately uses global reconnect instead. |
| 13 | Global service/auth states | Synthetic 503 hides financial content, successful authenticated retry reloads reports (`27/28`); synthetic 401 returns to sign-in without financial content (`29`). Privacy behavior preserved. |

## Visual QA

The current built product and the pre-change captures are the source/reference. Full matched comparisons were opened together for Apartment, tablet Settings, Statistics and Operations errors; native crops resolve the small availability badge/error copy. All comparisons preserve original pixel density; 1280×720 desktop / 768×1024 tablet / 390×844 and 320×844 phone viewports were used. The tablet image pair is a visual consistency comparison; the accessible-name fix is proven by the live AX tree and regression, not pixels.

- **Fonts/typography:** existing Noto Sans Hebrew and hierarchy retained. No new font assets; complete positive/negative/large decimal amounts inspected. Native money helpers remain unchanged.
- **Spacing/layout:** existing shell/cards retained; narrow classification filters get sufficient room, unavailable comparisons size to content, apartment alternatives wrap on phones. Checked phone documents measured exactly 320/320 or 390/390 client/document width in Expenses, Net Worth, Forecast, Classification editor, Settings failure and Data Quality states.
- **Colors/tokens:** established dark/light colors retained. Error fix reuses the existing dark form-error palette. Light tablet Settings and dark desktop/phone feedback inspected.
- **Images/assets:** no raster or new custom art needed; existing library icons and shared empty-state treatment reused. No image fidelity substitution.
- **Copy/content:** unfinished feature availability explicit; empty vs missing vs loading vs stale remains distinct. No conversion or completeness claims introduced. Apartment copy does not imply that a calculator is usable.

Iterations: tablet lost names → explicit names tested/live-verified; apartment unlabeled → badge/route guidance verified; Operations false empty/loading → regressions/live proxy verified; first error capture revealed dark contrast defect → palette correction compared at matching state; Settings fault revealed stuck loading → retry state tested/live-recovered; narrow month handoff revealed squeezed control → stacked filters checked on final build. No actionable P0/P1/P2 remains in the inspected states.

## Verification and limits

- Full frontend: **153 passed** (**150 component + 3 health**). Typecheck, full frontend lint, production build and diff check passed. No backend code changed; no new backend-suite result claimed.
- Six new regressions: two navigation, three Operations state, one Settings recovery. A pre-existing recurring-pattern focus assertion raced React's effect under full-suite load; it now waits for focus, retaining the assertion rather than weakening it.
- CLI Playwright/e2e was not run under Product Design browser policy. Browser actions used the in-app CUA tool. No physical-device, Safari/Firefox, full screen-reader, zoom/reduced-motion or comprehensive contrast certification.
- Fault proxy was GET-only and forwarded only the disposable QA backend. Synthetic 400s verify inline errors without triggering intentional global health failure; 503 and 401 verify service/auth privacy. No uncertain mutation replay, import commit, automation execution or concurrent multi-user writes were exercised in this pass; existing guards and their tests remain unchanged.
- Small pre-existing Hebrew age copy such as `לפני 0 ימים`/`נמדד לפני 1 ימים` remains a P3 wording opportunity, without changing dates or meaning. Broader Automation/Insights redesign and the Apartment calculator remain separate feature work.

## Runtime handoff

Final runtime sessions and retained browser state are recorded in `docs/ui-build-handoff.md`. Temporary fault preview is stopped after verification; normal main and synthetic QA previews remain on final code. The QA SQLite database and archived files were reused, not reseeded. Existing uncommitted work was preserved; no commit, stash, reset, deployment or PR.

**final result: passed**

Final narrow-layout evidence: `34-classification-month-final.jpg` and the opened
`compare-classification-month.jpg` compare the same September/ILS queue at320px with
`33`; the shared calendar icon, complete month label and arrows now have space.
`35` confirms the month popup fits and Escape restores trigger focus. The document
measures320/320. `compare-settings-retry.jpg` compares `26`/`30` at390px in the same
synthetic failed-request state; `31` confirms successful retry. Final normal preview
`36-final-preview.jpg`, default1280×720, dark theme, console errors `[]`.

Runtime: main **20703** serves127.0.0.1:3000/API8000 from existing `data/dev-local`;
QA **44249** serveslocalhost:3101/API8101 from the preserved temporary fixture.
Temporary fault preview **25790** was stopped. Final QA project is
`/var/folders/vx/r926hjxx7fn9bm86t8fdt9xw0000gn/T/familyfin-finalqa-ui-2zyaoncj`.
Generated Next route import restored to `.next/types/routes.d.ts`.

## Independent-review correction · Operations run feedback

Parent review reproduced a remaining P2 in the touched Operations flow: a rejected
`startAutomation` set an action error, then automatic status refresh immediately
cleared the same state. This made a failed/uncertain run disappear after successful
status/history reads. A new regression reproduced the missing alert before the fix.

Run feedback now has its own `runError`, independent of `statusError`. Automatic and
manual refreshes clear only status-read errors. Run feedback persists until the user
explicitly starts another run, which clears old action feedback before displaying
that new result. No automatic run retry was introduced. Fresh status still controls
readiness; pending/failed status blocks run actions even when action feedback exists.

Generic/network/server failures during an actual run explicitly say its result cannot
be confirmed and the operation may have completed; they direct the user to check run
history and files before another attempt. Definite client rejections keep the server
explanation and rejection/recovery guidance. Failed dry runs ask the user to check
run history before another check; they do not claim a successful no-change outcome.

Three regressions cover failed dry run→successful automatic refresh→manual refresh→
new explicit run, HTTP400 definite rejection and HTTP500 unknown outcome, including
subsequent failed/successful reads and independent action blocking. **26 focused tests**
across Operations/Settings, navigation and Data Quality pass; typecheck, full frontend
lint, production build and diff check pass. Earlier153 full-suite results above are
historical; the full suite/backend suite/CLIe2e were not rerun for this narrow correction.

No automation was executed or forwarded to any backend. A temporary preview was
prepared that forwarded only QA GETs and rejected every POST locally, then stopped
when browser access proved unavailable. Existing browser handle2 reported unavailable;
fresh CUA inventory returned no browsers. No new screenshot or visual run-error result
is claimed. Parent screenshot37 is normal Apartment evidence, not run-error evidence.
The new feedback/recovery behavior is component-tested; its browser path remains a
named verification limit, not a claim that privacy/auth states have changed.

Correction runtime: main **33731** (3000/8000), QA **59233** (3101/8101) on final code;
QA project `familyfin-finalqa-ui-4wm1c85c` with unchanged quality-root database/archives.
Temporary local-rejection preview **52619** stopped. Next route import restored.
Functional correction passed; narrow browser/design-QA follow-up remains unavailable.


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
