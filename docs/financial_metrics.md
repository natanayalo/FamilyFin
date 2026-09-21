# Financial metrics and classification policy

Phase 2 uses booking date and an explicit currency scope. The default scope is
ILS. Non-ILS rows remain importable and reviewable, but are never converted or
included in the default ILS metrics.

## Signs and formulas

Source amounts retain their source sign: debits are negative and credits are
positive. The metrics layer reports positive magnitudes for expense-like
values.

| Value | Formula |
| --- | --- |
| Gross income | Sum of positive `income` rows |
| Gross consumption | Sum of `abs(amount)` for negative `consumption` rows |
| Refunds | Sum of `abs(amount)` for `refund` rows |
| Net consumption | Gross consumption − refunds |
| Operating surplus or deficit | Gross income − net consumption |
| Savings rate | Operating surplus ÷ gross income, only when income is positive and the month is complete |
| Savings contributions | Sum of `abs(amount)` for negative `savings_transfer` rows |
| Savings withdrawals | Sum of positive `savings_transfer` rows |
| Net observed savings transfers | Contributions − withdrawals |

Operating surplus is a cash-flow measure. Observed savings transfers are
separate. Actual asset or balance change cannot be calculated because the
source does not provide balances or complete account linkage.

Spending by category uses the effective analysis category of consumption rows.
Consumption is split into fixed, variable, and unknown behavior. Fixed and
variable behavior is never inferred by the built-in policy; it starts as
unknown until a rule or override supplies it.

## Classification precedence

For each accepted transaction the engine evaluates, in order:

1. latest transaction-specific override;
2. latest active exact reusable rule;
3. versioned conservative built-in rule;
4. `unclassified`.

Source category, movement type, dates, and amounts remain immutable. Consumption
and refunds default their analysis category to the source category. A rule or
override can replace that category and can set fixed/variable behavior.

The built-in policy recognizes income, refunds, explicit savings/investment
transfers, variable bank credit-card settlements, ordinary negative purchases,
explicit interest, and explicit debt principal. It deliberately leaves
unlinked transfers, cash withdrawals, generic positive rows, positive card
income-like rows, unsplit loan payments, and zero-amount anomalies unclassified.
For an otherwise generic negative bank or card row, a description-only transfer
signal is retained as a review warning and keeps the row unclassified; stronger
source labels, reusable rules, and explicit overrides retain precedence.
If an override or rule requests a class whose direction is impossible for the
source sign, the result receives `INVALID_CLASS_SIGN` and is explicitly marked
`unclassified`; it cannot silently disappear from metrics.

## Completeness and comparisons

A month is source-period complete only when a committed export covers its entire
calendar boundary and the export's latest observed transaction provides
freshness through that boundary. A requested `report_end` alone is not
evidence that the trailing month is complete. Boundary months are partial when
the export starts or ends inside that month. Open reconciliation cases make
the month incomplete.
Unclassified transactions are reported separately and also make classification
incomplete. Source coverage for external accounts is recorded as unknown unless
explicitly configured; it is never inferred from the current source.

Incomplete months may be displayed provisionally. They are excluded by default
from rolling three- and six-month averages and from month-over-month and
year-over-year comparisons. The reported comparison values are absolute
Decimal deltas (current month minus comparison month); a comparison is
available only when both months are complete. Each aggregate retains the
transaction IDs that contributed to it, so a displayed value can be reconciled
exactly.

## Known source limitations

The FamilyBiz export has no stable transaction identifier, pending state,
balance, installment sequence, reliable transfer linkage, or loan component
split. No FX conversion, balance reconstruction, pending inference, or loan
allocation is performed in Phase 2.
