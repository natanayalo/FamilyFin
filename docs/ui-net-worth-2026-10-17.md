# Net Worth design review - 17 October 2026

Used the isolated QA household, first empty and then with eight synthetic accounts
and three snapshots. No real household accounts, balances or preferences changed.
The established option 1 direction, existing Hebrew type and theme tokens remain
the visual reference. This was a scoped refinement, not a new visual direction.

## Flow and findings

1. **First use - improved.** The original screen repeated its title and led with an
   empty summary without a first-step action. Capture 02. It now explains accounts
   → dated balances → assets minus debts, with one immediate setup action. The
   action opens the management area and focuses the editor. After an account is
   saved, the guide advances to the first balance entry. Captures 06 and 10.
2. **Measured worth and balances - improved.** The original screen emphasized
   registry/technical details and gross breakdowns ahead of account balances.
   Captures 01 and 03. The primary view now names its measurement date, shows net
   worth/assets/debts and the balances behind them. Liquid/restricted/illiquid
   amounts remain visible. Older valuations stay prominent. Ownership breakdown
   explicitly says that it sums asset and debt balances before offsetting debts;
   its underlying calculation was preserved. Captures 15–19.
3. **Updates and history - verified.** Account management, revisions, CSV import
   and forecast comparison are in a native collapsed group. Dated measurement
   selection remains in the primary summary. Duplicate dates offer an existing
   measurement revision instead of a failed duplicate save. Editors keep the
   original concurrency, quality acknowledgement and exact decimal transport.
   Capture 20 shows a Hebrew revision date and labeled mobile fields.

## Visual iterations

- P2: the first implementation placed the phone's setup action after all three
  explanation steps. Capture 05. Moved it immediately after the introduction.
  Capture 10 verifies its bounds at y=507.32–543.32 in an 844px-high viewport.
- P2: large totals could wrap the currency or split decimals in narrow cards.
  Captures 11–12. Reduced the headline size and stacked cards at 320px; 390px
  retains two smaller asset/debt cards beneath net worth. Captures 15–16 and 18
  verify whole amounts and no horizontal overflow.
- P2: the final 768px tablet check still wrapped currency in three narrow cards
  (capture 21). At 621–1100px, net worth now spans the first row with assets/debts
  below. Capture 22 and the opened compare-money-tablet image verify whole values;
  document/client widths both equal 768px. All three headline heights are one line.
- Final comparisons contain source and implementation together at native scale:
  compare-empty-desktop, compare-populated-desktop, compare-setup-phone,
  compare-money-phone, compare-headline-focus, compare-money-tablet. No actionable
  P0/P1/P2 remains.

## Evidence

All captures are private ignored files under `/Users/natanayalo/dev/FamilyFin/frontend/test-results/net-worth-design-2026-10-17`. Desktop images are
1280×720; native phone images are 320×844 and 390×844; tablet images are 768×1024.
The complete comparison and
fidelity review is appended to the root design-qa.md. Captures were saved and
opened before acceptance. Initial sign-in captures and a transient phone render
were rejected and replaced with loaded-state captures.

![First-use setup](/Users/natanayalo/dev/FamilyFin/frontend/test-results/net-worth-design-2026-10-17/06-empty-final-desktop.jpg)
![Populated measured worth](/Users/natanayalo/dev/FamilyFin/frontend/test-results/net-worth-design-2026-10-17/15-populated-final-desktop.jpg)
![Phone account balances](/Users/natanayalo/dev/FamilyFin/frontend/test-results/net-worth-design-2026-10-17/17-balances-phone.jpg)

## Verification and limits

Completed the first-account → first-snapshot flow through the real QA API using
12,345.67 ILS, then recreated the separate populated fixture. Changing the selected
measurement to September displayed 1,519,251.00 ILS and September balances. Current
October totals remain 1,534,751.00 ILS net, 2,182,751.00 assets and 648,000 debts.
Existing-date revision entry prefills the current saved values; test drafts were
cancelled. Native disclosure keyboard toggling, focus, stale valuation status,
light/dark appearance and 320px/390px document widths were checked. Console error
lists are empty. The populated fixture is left at October 17 with management and
breakdowns collapsed. Viewport overrides were reset.

105 component + 3 health tests pass; the final 12-test Net Worth rerun also passes.
TypeScript and final production build pass. ESLint retains only the existing
forecast refreshAll dependency warning. No financial API or calculation changes.
CLI e2e was not run. Full screen-reader certification, quantitative contrast checks,
Safari/Firefox certification and physical-device testing remain outside this pass.
