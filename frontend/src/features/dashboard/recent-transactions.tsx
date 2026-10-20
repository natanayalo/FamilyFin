"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { classificationLabel, formatAmount, formatDate } from "./format";
import { QueryState, useDashboardResource } from "./shared";
import type { DashboardFilters, TransactionContribution } from "./types";

export function RecentTransactions({ filters }: { filters: DashboardFilters }) {
  const recent = useDashboardResource<TransactionContribution[]>("/dashboard/recent-transactions", filters);
  const allTransactions = `/classification?${new URLSearchParams({ month: filters.end_month.slice(0, 7), currency: filters.currency, include_resolved: "true" })}`;
  return <section className="overview-transactions" aria-labelledby="overview-transactions-title">
    <header><h2 id="overview-transactions-title">עסקאות אחרונות בחודש</h2><Link href={allTransactions}>כל עסקאות החודש<ArrowLeft size={16} /></Link></header>
    <QueryState loading={recent.loading} error={recent.error} retry={recent.retry} />
    {!recent.loading && !recent.error && recent.data && (recent.data.length ? <div className="overview-transactions-scroll" role="region" aria-label="עסקאות אחרונות" tabIndex={0}>
      <table className="overview-transactions-table">
        <thead><tr><th scope="col">תאריך</th><th scope="col">תיאור</th><th scope="col">קטגוריה</th><th scope="col">סכום</th></tr></thead>
        <tbody>{recent.data.map((row) => <tr key={row.transaction_id}>
          <td><bdi>{formatDate(row.booking_date)}</bdi></td>
          <th scope="row"><span>{row.description}</span>{row.effective_classification === "unclassified" && <small>ממתינה לסיווג</small>}</th>
          <td><span className="overview-category">{row.analysis_category || row.source_category || classificationLabel(row.effective_classification)}</span></td>
          <td className={`overview-transaction-amount ${row.amount.startsWith("-") ? "debit" : "credit"}`}><bdi>{formatAmount(row.amount, row.currency)}</bdi></td>
        </tr>)}</tbody>
      </table>
    </div> : <p className="dashboard-empty">אין עסקאות להצגה בחודש זה.</p>)}
  </section>;
}
