# Expenses clarity follow-up - 16 October 2026

Continues the selected Monthly Clarity direction in the existing FamilyFin app.
Scope: understand the selected month's expenses, refunds and net spending, then
inspect contributing transactions. Uses existing financial metrics and household
development data; no calculations, classifications or records were changed.

## Current-run audit and fixes

1. **Monthly summary - fixed.** The baseline led with fixed/variable zeros and
   unknown behavior rather than gross/refunds/net. The new summary shows all three
   service values, explains refund booking-month semantics, and identifies net
   spending as the figure also shown in Overview. Categories explicitly show gross
   spending before refunds. Evidence: 01-before-desktop.jpg and 10-desktop-final.jpg.
2. **Category transactions - passed.** Each category is a labeled button that loads
   only its contributor IDs, displays transactions inline, and closes on a second
   click. Expanded state and its controlled region are exposed to assistive tools.
   Evidence: 03-category-desktop.jpg and 06-category-mobile.jpg.
3. **Refunds and comparisons - passed.** The refund selection loaded the transaction
   matching the selected month's refund total. Unavailable comparison reasons now
   appear once per period, with no table of repeated unavailable cells. Available
   comparisons remain visible. Evidence: 07-refunds-mobile.jpg; mixed availability
   is covered by a component test because this household's months are incomplete.
4. **Phone layout - fixed and passed.** An initial 390px capture exposed a currency
   wrap below the gross amount. Reduced value sizing and padding keep the amount
   and currency together. At 320px the cards stack. Document width equals client
   width at both sizes; category and refund transaction details remain usable.
   Evidence: 04-mobile-iteration-1.jpg, 05-mobile-final.jpg, 08-narrow-final.jpg.
5. **Missing month and coverage - passed.** October displays unavailable values,
   not zero spending; the unavailable behavior breakdown is hidden. Returned to
   September after checking. Coverage diagnostics still open/close from a disclosure;
   the provisional-data statement remains beside the totals. Evidence: 09-missing-month.jpg.

Unknown fixed/variable behavior is explained separately from missing economic
classification. A scoped link opens all consumption transactions for the month and
currency so behavior can be reviewed. The desktop frame follows the 210px sidebar
and compact heading used in completed Monthly Clarity screens.

## Evidence and limits

All captures were made during this follow-up in the authenticated Codex in-app
browser and saved under `frontend/test-results/expenses-2026-10-16/` (ignored,
private development data). No external uploads or financial writes were performed.
Desktop: 1440×1024 CSS viewport, density 1; native capture 1425×1013. Phone:
390×844 CSS, native 375×812; narrow phone: 320×844 CSS, native 305×804.
Native captures omit the scrollbar and a bottom strip; no full-viewport pixel
fidelity is claimed for omitted regions. Desktop before/after images have identical
dimensions and are compared without rescaling. Mobile is a responsive adaptation.

Screenshots and DOM checks establish layout, semantics, controls and reflow, not
full accessibility compliance. No complete screen-reader, contrast, zoom, Safari or
physical-device pass was performed. This pass used the existing dark theme; the
light theme retains existing tokens but was not visually audited. No browser console
errors were observed. The browser preview remains local and authenticated.

Validation: 79 component tests + 3 health tests pass. After the final missing-month
guard, the 14 dashboard component tests were rerun and pass. TypeScript and the
production build pass; lint retains the existing ForecastsFeature dependency warning.
Focused tests cover refunds exceeding spending, exact displayed signs/decimals,
missing months, contributor scope, collapse state, deduplicated unavailable messages,
and preserving available comparisons. Backend policy and calculations are unchanged.

![Before and after desktop expense view](../frontend/test-results/expenses-2026-10-16/comparison-final.jpg)

![Final phone expense view](../frontend/test-results/expenses-2026-10-16/05-mobile-final.jpg)

![Category transactions on phone](../frontend/test-results/expenses-2026-10-16/06-category-mobile.jpg)

![Refund transaction drill-down](../frontend/test-results/expenses-2026-10-16/07-refunds-mobile.jpg)

![Narrow phone view](../frontend/test-results/expenses-2026-10-16/08-narrow-final.jpg)

![Unavailable month](../frontend/test-results/expenses-2026-10-16/09-missing-month.jpg)
