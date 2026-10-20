# Data Quality and import clarity - 18 October 2026

Implemented the next selected option 1 design slice. Preview: http://localhost:3101/data-quality.

The page now leads with the work to complete: source-period coverage, transaction
classification, and reconciliation. A month shows its actual reason and relevant
next action. Classification links carry the month and ILS filter. Passing monthly
checks remains explicitly separate from knowing whether every household account
was included in the FamilyBiz export.

## Flow review and resulting behavior

1. **Find the next task - passed.** Three compact checks replace six context metrics.
   A direct import action is available at the top on desktop and phone. The checked
   range is explicit (the service's default 12-month scope); classification and
   aggregate review money are explicitly ILS. No missing month is rendered as zero.
2. **Review incomplete months - passed.** Source gaps, unresolved classifications
   and open matches have distinct explanations and actions. Passed months are in
   optional details. First/last transaction dates are correctly labeled in details,
   rather than called proof of a continuously covered period. Account coverage is
   still unknown in this QA household even when individual months pass.
3. **Choose a workbook - passed.** Hebrew file-selection button and selected filename
   replace the browser's English file-picker text. Native file validation/accept
   remains; 25 MiB limit and FamilyBiz XLSX requirement remain visible.
4. **Preview and decide - passed.** Preview stays read-only. Predicted new, unchanged,
   updated and unresolved counts precede explicit approval. Duplicate-file previews
   clearly say no transactions will be added. Readable warning explanations and
   rejected-row consequences are visible; full plans/provenance remain available.
5. **Import and recover - passed for success/validation.** An explicit browser commit
   added one synthetic transaction, leaving three unchanged. Invalid workbook showed
   Hebrew correction guidance. Support request IDs are optional. The existing unknown
   commit outcome/fresh-preview guard is retained and component-tested; no automatic
   commit replay was added.
6. **Resolve a potential duplicate - passed.** Description, source date/amount, candidate
   dates/amounts and decision consequences are visible before editing. No decision is
   preselected. Saving requires a choice; linking also requires a candidate. Two QA
   ambiguous imports were linked to an existing transaction, without additional inserts.
   Result/error feedback appears inside reconciliation. Existing idempotent uncertain
   retries preserve the original decision and key (component regression).
7. **Inspect history - passed.** History is collapsed with latest date/status summary.
   Useful period/results columns remain; batch IDs and issue codes are optional.
   Keyboard Enter opens history/month details; narrow history uses the existing
   responsive cards. Diagnostic issue counts explain that several issues may refer to
   one transaction and source notes can remain after classification corrections.
8. **Start without data - passed.** A separate empty synthetic household shows first-import
   guidance instead of twelve repetitive missing-month rows or a misleading all-clear.

## Defects fixed

- Incomplete month labels did not identify which completeness check failed. The
  quality response now adds `monthly_checks`, projected from the already calculated
  monthly assessments. Existing fields and completeness arithmetic are unchanged.
- First/last transaction dates were labeled as a covered period, and the source/account
  coverage distinction was unclear. Copy and disclosure hierarchy now reflect the
  actual service semantics.
- Reconciliation defaulted to accepting the source as a new transaction. An explicit
  decision is now required; candidate validation remains server-owned.
- Candidate select intrinsic width expanded a 390px page to 415px. Final select,
  label and grid sizing measures 390/390 and 320/320 with both selects visible.
- Reconciliation feedback was rendered in the import section, away from the action.
  Feedback is now shown in the relevant import, reconciliation or pagination area.
- Older refresh responses could overwrite a newer load. Request-generation guard
  and a regression preserve the latest result.
- Initial load failure could display an empty reconciliation list. It now says the
  list is unavailable rather than claiming there are no open matches.
- Generic reconciliation warning now has a specific Hebrew explanation. Success
  notices and invalid-file feedback no longer lead with internal IDs.

No financial engine calculations, parser/provider integration, database schema,
import duplicate matching, provenance, authorization, preview tokens, stale-preview
validation or mutation replay policy changed. The backend response extension is
additive and uses existing service assessments.

## Verification

- 143 frontend tests passed: 140 component + 3 health. Eight Data Quality tests cover
  preview/unknown import outcome, realistic empty assessment, per-month reasons and
  exact large decimal display, explicit matching/idempotent retry, duplicate warning,
  failed load and refresh ordering.
- 34 quality/import backend tests passed; existing dashboard API suite also passed.
  Transport regression checks each month against its service assessment and keeps
  unknown household coverage separate.
- Typecheck, frontend lint, touched Python Ruff checks, production build and
  `git diff --check` passed. Main and QA use the final build.
- In-app browser: desktop 1280x720; tablet 768x1024; phone 390x844 and 320x844;
  dark/light; keyboard disclosures; partial/missing source, classification and
  reconciliation; first use; valid commit; duplicate preview; invalid file; deep link.
- Final clean route's console error list was empty. The deliberate invalid workbook
  returned the expected validation error during its test.
- CLI Playwright was not run (Product Design restriction). Two existing e2e assertions
  were updated to the new heading/success notice; their CLI run remains unverified.
- No physical-device, Safari/Firefox, full screen-reader or contrast certification.
  Full auth-loss/unknown mutation replay was component/API tested, not network-fault
  injected in the browser. Import plan download remains covered by existing tests,
  not downloaded manually in this pass.

## Evidence and design QA

Private ignored folder: `frontend/test-results/data-quality-design-2026-10-18/`.
All accepted screenshots were opened and inspected. Important captures:

- `01-before.jpg`: initial populated screen, context metrics ahead of actions.
- `02-after-first.jpg`: first hierarchy pass; singular Hebrew wording was refined.
- `03-preview-before-commit.jpg`: successful read-only preview before explicit import.
- `05-phone390.jpg`, `06-duplicate-phone390.jpg`, `07-preview-phone320.jpg`.
- `08-invalid-phone320.jpg`: request-ID noise before refinement.
- `09-reconciliation-desktop.jpg`: readable source/candidates and unselected decision.
- `10-reconciliation-phone390.jpg`: pre-fix document-width measurement was 415px;
  screenshot itself shows the import area, so it is not used as a visual candidate-layout
  comparison. Actual revised candidate layouts are `13` and `14`.
- `11-tablet-month-checks.jpg`, `12-tablet-light.jpg`.
- `13-reconciliation-phone390-fixed.jpg`, `14-reconciliation-phone320-fixed.jpg`:
  both controls and money fit, verified document widths equal viewport widths.
- `15-first-import-desktop.jpg`, `16-first-import-phone390.jpg`: fresh empty household.
  An initial transient scaled phone capture was rejected and replaced with stable 390x844.
- `18-history-desktop.jpg`, `19-invalid-phone320-final.jpg`.
- `20-final-desktop.jpg`: final handoff image, no draft or notice.

Combined inputs actually opened: `compare-desktop.jpg` (01 vs20),
`compare-money-focus.jpg` (native crops, padded not stretched), and
`compare-validation-phone.jpg` (08 vs19 at matching 320x844). Fonts, spacing, tokens,
assets and copy evaluated in the appended root `design-qa.md` entry. Final result: passed.

![Final Data Quality](/Users/natanayalo/dev/FamilyFin/frontend/test-results/data-quality-design-2026-10-18/20-final-desktop.jpg)

## Runtime and fixture safety

Main session 49274: http://127.0.0.1:3000 / API8000, existing `data/dev-local`.
Safely stopped via supported launcher before each production rebuild. Household
records/preferences and original `data/local` were never imported into or modified.

Final QA session 7224: http://localhost:3101 / API8101,
`/tmp/familyfin-quality-preview.py`.
`/tmp/familyfin-quality-project` and `/tmp/familyfin-expense-cleanup-project` point
at the final temporary frontend; `/tmp/familyfin-quality-root` points at the data.
The original Statistics fixture was copied to a new guarded `familyfin-live-quality-*`
root with SQLite backup and archived source-path relocation before browser mutations.
Original Statistics root/project remain preserved. The QA copy retains Planning,
eight Net Worth accounts/three snapshots, Forecast and Jan-Aug Statistics fixtures.
Browser tests added one synthetic transaction (19 to 20) and two resolved match batches;
no open matches or pending import remains. September still has two unclassified
transactions and partial source-period coverage, absolute amount 72.4 ILS.

The additional empty QA stack (3102/8102) was stopped and its tab closed. Populated
QA login restored. Tab1 is retained as a deliverable on `/data-quality`, dark theme,
default viewport, all details closed, no selected file, no draft, console errors [].
Generated `frontend/next-env.d.ts` route reference restored to `.next/types/routes.d.ts`.
All pre-existing uncommitted work was preserved; no commit/deploy/PR was created.

## Independent-review correction - 19 October 2026

Parent review identified a P2 history-state contradiction: when the initial data load
failed, the collapsed summary said history was unavailable but expanding it rendered
an empty-history table. This could mislead someone checking an uncertain import.

History now uses an explicit never-loaded state (`null`). Pending and failed initial
loads show loading/unavailable guidance instead of either empty-history claim.
A successful empty response shows the genuine empty state. A failed refresh retains
previously loaded rows with a warning that the snapshot may be out of date. Previously
empty snapshots are labeled as previous results, rather than fresh proof of no import.
No import request, outcome-unknown guard, API, database or financial semantics changed.

Four regressions added: pending to successful empty; initial history failure; populated
history retained after refresh failure; and previously empty history after refresh
failure. All 12 focused Data Quality tests, typecheck, frontend lint, production build
and `git diff --check` pass. The full 143-test and backend results above are the original
slice checks; they were not rerun for this isolated frontend state correction.

Runtime update: main session 91677 (3000/8000); QA session 37714 (3101/8101), both with
this correction and the same existing data directories/fixture. Generated Next route
reference restored. No synthetic or household data/preference mutations were needed.

Current browser verification limitation: the subagent's CUA inventory contains no browsers;
both the former browser handle and creating an in-app tab report unavailable. A temporary
read-only failure preview was prepared for parent verification on localhost:3102, forwarding
QA GET requests and failing only import-history reads. It makes no application mutations.
No new browser screenshot or console validation is claimed for this correction. Parent
verification status and temporary preview cleanup are recorded in the following handoff.

Parent follow-up - 19 October 2026: independently reviewed the corrected code and
reran all 12 focused Data Quality tests successfully. Normal QA at localhost:3101
loads correctly. The read-only fault preview's deliberate 503 response triggered
the app-provider's global reconnect state, so it did not provide valid visual evidence
of the inline history-failure state. That specific browser path remains unverified;
its loading/failure/empty/cache distinctions are covered by the component regressions.
Temporary fault-preview session 88773 was stopped. Main 91677 and normal QA 37714
remain running; no data or app code changed during this cleanup.
