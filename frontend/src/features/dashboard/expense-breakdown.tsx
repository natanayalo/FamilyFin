"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ArrowLeft, X } from "lucide-react";
import { ErrorState, LoadingState } from "@/components/ui/async-state";
import { ApiRequestError, apiRequest } from "@/lib/api";
import { formatAmount, formatHebrewMonth } from "@/lib/display";
import { formatDate } from "./format";
import type { DashboardExpenses, TransactionContribution } from "./types";

const pageSize = 10;
const modes = [
  { value: "both", label: "הוצאות והחזרים" },
  { value: "expenses", label: "הוצאות בלבד" },
  { value: "refunds", label: "החזרים בלבד" },
] as const;
type Mode = typeof modes[number]["value"];

export function ExpenseBreakdown({ data }: { data: DashboardExpenses }) {
  const id = useId();
  const tableHeading = useRef<HTMLHeadingElement>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [mode, setMode] = useState<Mode>("both");
  const [page, setPage] = useState(0);
  const [rows, setRows] = useState<TransactionContribution[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiRequestError>();
  const [attempt, setAttempt] = useState(0);
  const breakdowns = data.selected_month?.metrics.breakdowns;
  const signature = JSON.stringify([...new Set(breakdowns?.net_consumption?.contributor_transaction_ids ?? [])].sort((a, b) => a - b));

  useEffect(() => {
    let current = true;
    const ids: number[] = JSON.parse(signature);
    setRows([]); setError(undefined); setLoading(Boolean(ids.length));
    async function load() {
      try {
        const collected: TransactionContribution[] = [];
        for (let index = 0; index < ids.length; index += 100) {
          if (!current) return;
          const result = await apiRequest<TransactionContribution[]>("/dashboard/contributors/query", {
            method: "POST", body: JSON.stringify({ transaction_ids: ids.slice(index, index + 100) }),
          });
          collected.push(...result.data);
        }
        if (current) setRows(collected.sort((a, b) => b.booking_date.localeCompare(a.booking_date) || b.transaction_id - a.transaction_id));
      } catch (reason) {
        if (current) setError(reason instanceof ApiRequestError ? reason : new ApiRequestError("לא ניתן לטעון את עסקאות החודש.", 500));
      } finally {
        if (current) setLoading(false);
      }
    }
    if (ids.length) void load();
    return () => { current = false; };
  }, [signature, attempt]);

  const filtered = rows.filter((row) => (category === null || (row.analysis_category || row.source_category) === category)
    && (mode === "both" || row.effective_classification === (mode === "refunds" ? "refund" : "consumption")));
  const lastPage = Math.max(0, Math.ceil(filtered.length / pageSize) - 1);
  const currentPage = Math.min(page, lastPage);
  const visibleRows = filtered.slice(currentPage * pageSize, (currentPage + 1) * pageSize);
  const largest = Math.max(0, ...data.categories.map((item) => Number(item.amount)));
  let categories = expanded ? data.categories : data.categories.slice(0, 6);
  const selectedCategory = data.categories.find((item) => item.category === category);
  if (!expanded && selectedCategory && !categories.includes(selectedCategory)) categories = [...categories.slice(0, 5), selectedCategory];

  function chooseCategory(next: string | null) {
    setCategory(next); setPage(0);
    tableHeading.current?.focus({ preventScroll: true });
    tableHeading.current?.scrollIntoView?.({ block: "start", behavior: "instant" });
  }

  return <section className="dashboard-panel expense-breakdown" aria-labelledby={`${id}-title`}>
    <header><div><h2 id={`${id}-title`}>התפלגות לפי קטגוריה</h2><p>{formatHebrewMonth(data.filters.end_month)} בלבד. בחרו קטגוריה לסינון טבלת העסקאות.</p></div></header>
    <div className="expense-breakdown-columns">
      <div className="expense-category-summary">
        <div className="expense-category-heading"><h3>הוצאות לפני החזרים</h3><button type="button" className="expense-all-categories" aria-pressed={category === null} aria-controls={`${id}-transactions`} onClick={() => chooseCategory(null)}>כל הקטגוריות</button></div>
        {categories.length ? <div className="dashboard-bar-list" role="list" aria-label="התפלגות הוצאות לפי קטגוריה">{categories.map((item) => <div className="expense-category" role="listitem" key={item.category}>
          <button type="button" className="expense-category-trigger" aria-label={`עסקאות בקטגוריה ${item.category} (${item.contributor_transaction_ids.length})`} aria-pressed={category === item.category} aria-controls={`${id}-transactions`} onClick={() => chooseCategory(item.category)}>
            <span className="expense-category-name">{item.category}<small>{item.contributor_transaction_ids.length === 1 ? "עסקה אחת" : `${item.contributor_transaction_ids.length} עסקאות`}</small></span>
            <span className="dashboard-bar-track" aria-hidden="true"><span className="dashboard-bar" style={{ width: largest > 0 ? `${Number(item.amount) / largest * 100}%` : "0%" }} /></span>
            <b>{formatAmount(item.amount, data.currency)}</b><ArrowLeft size={16} aria-hidden="true" />
          </button>
        </div>)}</div> : <p className="dashboard-empty">אין קטגוריות הוצאה בחודש שנבחר.</p>}
        {data.categories.length > 6 && <button type="button" className="dashboard-link-button expense-category-more" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? "הצגת פחות קטגוריות" : `כל הקטגוריות (${data.categories.length})`}</button>}
      </div>
      <section className="expense-transaction-list" id={`${id}-transactions`} aria-labelledby={`${id}-transactions-title`}>
        <h3 id={`${id}-transactions-title`} tabIndex={-1} ref={tableHeading} aria-describedby={`${id}-scope`}>עסקאות החודש</h3>
        <fieldset className="expense-transaction-modes"><legend className="sr-only">סוג העסקאות</legend>{modes.map((item) => <button type="button" key={item.value} aria-pressed={mode === item.value} onClick={() => { setMode(item.value); setPage(0); }}>{item.label}</button>)}</fieldset>
        <div className="expense-transaction-scope"><p id={`${id}-scope`} role="status">{category === null ? "כל הקטגוריות" : `קטגוריה: ${category}`}{!loading && !error && ` · ${filtered.length === 1 ? "עסקה אחת" : `${filtered.length} עסקאות`}`}</p>{category !== null && <button type="button" className="dashboard-link-button" onClick={() => chooseCategory(null)}>ניקוי סינון קטגוריה<X size={14} aria-hidden="true" /></button>}</div>
        <p className="expense-refund-note">החזרים מוצגים לפי הקטגוריה שלהם ובחודש שבו נרשמו.</p>
        {loading && <LoadingState label="טוענים את עסקאות החודש…" />}
        {error && <ErrorState description={error.message} requestId={error.apiError?.request_id} onRetry={() => setAttempt(attempt + 1)} />}
        {!loading && !error && (filtered.length ? <>
          <div className="expense-transaction-table"><table className="dashboard-data-table">
            <caption className="sr-only">עסקאות החודש לפי הסינון שנבחר</caption>
            <thead><tr><th scope="col">תאריך</th><th scope="col">תיאור</th><th scope="col">קטגוריה</th><th scope="col">סכום</th></tr></thead>
            <tbody>{visibleRows.map((row) => <tr key={row.transaction_id}>
              <td data-label="תאריך">{formatDate(row.booking_date)}</td>
              <td data-label="תיאור"><strong>{row.description}</strong><small><span className={row.effective_classification === "refund" ? "expense-refund-kind" : undefined}>{row.effective_classification === "refund" ? "החזר" : "הוצאה"}</span> · {row.account_label}</small></td>
              <td data-label="קטגוריה">{row.analysis_category || row.source_category}</td>
              <td data-label="סכום" className="amount">{formatAmount(row.amount, row.currency || data.currency)}</td>
            </tr>)}</tbody>
          </table></div>
          {filtered.length > pageSize && <nav className="expense-transaction-pages" aria-label="עמודי עסקאות"><button type="button" disabled={currentPage === 0} onClick={() => { setPage(currentPage - 1); tableHeading.current?.focus(); }}>הקודם</button><span>עמוד {currentPage + 1} מתוך {lastPage + 1}</span><button type="button" disabled={currentPage === lastPage} onClick={() => { setPage(currentPage + 1); tableHeading.current?.focus(); }}>הבא</button></nav>}
        </> : <p className="dashboard-empty">{category === null ? "אין עסקאות מהסוג שנבחר בחודש זה." : "אין עסקאות מהסוג שנבחר בקטגוריה זו בחודש זה."}</p>)}
      </section>
    </div>
  </section>;
}
