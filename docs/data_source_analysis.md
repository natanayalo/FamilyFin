# Data source analysis

## FamilyBiz export

The supplied FamilyBiz workbook has one worksheet and seven repeated account sections. The sections represent two Cal cards, two Isracard cards, one Max card, one ILS Discount account, and one USD Discount account. Account references are treated as sensitive identifiers and are fingerprinted for matching rather than reproduced in documentation or logs.

Each section repeats these source columns:

| Source field | Normalized field | Treatment |
| --- | --- | --- |
| תאריך | booking_date | Required dd/mm/yyyy; used for cash-flow and historical metrics |
| סכום | amount | Required Decimal(str(value)) |
| תאור | description | Unicode-normalized and trimmed |
| תאריך ביעדים | allocation_date | Preserved separately; never silently substituted for booking date |
| סוג תנועה | movement_type | Optional source classification |
| קטגוריה | category | Preserved as an exact source value |
| מטבע | currency | The reporting currency for the amount |
| מטבע מקורי | original_currency | Optional original transaction currency |
| תנועה מקורית | original_amount | Optional original transaction amount |

The report header states a requested range through 30 September 2026, while the latest observed booking date is 19 September 2026. Freshness therefore uses import time and the maximum booking date. It does not treat the requested report end as evidence that the period is complete.

## Observed quality findings

The workbook contains 1,452 transaction rows from 1 September 2025 through 19 September 2026:

- 85 rows have no movement type.
- 22 rows have an allocation date different from the booking date.
- Four rows have no original amount or original currency.
- 18 rows have a zero reporting amount with a non-zero original amount.
- 115 category cells contain the escaped _x000D_ marker and are normalized to a newline.
- The export has 1,438 ILS rows and 14 USD rows. Non-ILS rows are imported and displayed separately, but excluded from ILS analytics until an FX policy exists.
- The source contains duplicate-looking occurrences. Date, amount, and description are not a unique transaction identity.

These are warnings unless a value is required for safe parsing. The raw row payload is preserved in source_records; normalization is used for matching and analytics fields.

## Import matching policy and limits

FamilyBiz does not provide a stable transaction ID, so the importer uses
source-field signatures rather than assuming that a plausible match is the
same purchase. An exact match compares the account reference, booking date,
allocation date, reporting amount and currency, description, movement type,
category, and original amount and currency. Exact occurrences are reserved
one-to-one before candidate matching.

The candidate search is deliberately bounded. It can find revisions with a
same-date description or amount change, paired reporting/original amount
changes on the same date and description, and booking-date shifts of up to
seven days when the other amount, currency, and description fields still
match. A single plausible candidate and competing candidates both go to
reconciliation; the importer never applies a non-exact revision automatically.
An occurrence with no candidate under these signatures is treated as new.

There is a residual duplicate risk when multiple identifying fields change
together. For example, a nearby booking-date change combined with a changed
description and changes to both amounts can evade the current signatures and
be imported as new. The synthetic importer test records this limitation. The
available workbook has no stable transaction IDs and contains duplicate-looking
occurrences, but provides no evidence that this compound revision pattern is
common. A broader review-only search could raise many false candidates among
repeated purchases, so it is not enabled without representative exports that
justify a useful additional signal. Non-exact matches remain manual decisions.

## Planning CSV

The supplied CSV has 41 rows and 33 columns. It is a manually maintained planning sheet with five side-by-side budget versions, income, savings, notes, and monthly spending assumptions. It is not transaction-level data and is intentionally excluded from the FamilyBiz importer. Phase 4 parses the rightmost structurally recognized target block: the supplied file yields 24 explicit expense targets, two recurring income rows, one monthly savings summary, and nine notes attached to explicit targets. Observed-month columns, differences, historical savings balances, and unexpected-income history are excluded.

The CSV policy is strict UTF-8 with bounded file, row, column, and field sizes. Numeric fields must be standalone currency/number cells. Narrative text is never converted into an amount. The supplied expense block total is retained separately from the household monthly-expense control; the preview surfaces their unreconciled gap instead of deriving the blank rent target from its note. Every seeded item retains the parser version, source row/range, file SHA-256, and any explicit category mapping decision.

## Explicitly unavailable fields

The source does not provide a stable transaction ID, pending/completed status, balance, installment sequence, loan principal/interest split, or explicit transfer linkage. The importer does not invent these fields. Reliable import outputs are source-backed transaction counts, totals by currency, category/movement labels, freshness, and import/reconciliation status. Phase 2 classification remains conservative around these limitations; polished dashboards belong to later phases.
