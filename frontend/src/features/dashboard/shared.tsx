"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiRequestError, apiRequest } from "@/lib/api";
import { ErrorState, LoadingState } from "@/components/ui/async-state";
import { classificationLabel, comparisonReason, coverageLabel, formatAmount, formatDate, formatMonth, metricLabel } from "./format";
import type {
  DashboardFilters,
  DashboardComparison,
  MonthlySeriesPoint,
  TransactionContribution,
} from "./types";

export type FilterDraft = { start_month: string; end_month: string; currency: string };
export const defaultFilterDraft: FilterDraft = { start_month: "", end_month: "", currency: "ILS" };
let inMemoryDashboardFilters: DashboardFilters | undefined;

export function useDashboardResource<T>(endpoint: string, filters?: DashboardFilters) {
  const [data, setData] = useState<T>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiRequestError>();
  const [reloadToken, setReloadToken] = useState(0);
  const query = filters ? (() => {
    const values = new URLSearchParams({
      start_month: filters.start_month.slice(0, 7),
      end_month: filters.end_month.slice(0, 7),
      currency: filters.currency,
    });
    return `?${values.toString()}`;
  })() : "";

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(undefined);
    apiRequest<T>(`${endpoint}${query}`)
      .then((result) => { if (active) setData(result.data); })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof ApiRequestError ? reason : new ApiRequestError("הבקשה לא הושלמה.", 500));
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [endpoint, query, reloadToken]);

  return { data, loading, error, retry: () => setReloadToken((value) => value + 1) };
}

export function DashboardFilterForm({
  value,
  onChange,
  onApply,
  loading,
}: {
  value: FilterDraft;
  onChange: (value: FilterDraft) => void;
  onApply: (filters: DashboardFilters) => void;
  loading: boolean;
}) {
  const [message, setMessage] = useState("");
  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const start = value.start_month.trim();
    const end = value.end_month.trim();
    const currency = value.currency.trim().toUpperCase();
    if (!start || !end || !currency) { setMessage("יש לבחור תקופה ומטבע."); return; }
    if (start > end) { setMessage("חודש ההתחלה צריך להיות לפני חודש הסיום."); return; }
    if (currency.length > 12) { setMessage("קוד המטבע ארוך מדי."); return; }
    setMessage("");
    onApply({ start_month: `${start}-01`, end_month: `${end}-01`, currency });
  }
  return <form className="dashboard-filter" onSubmit={submit} aria-label="מסנני תקופה">
    <label className="dashboard-field">מתאריך
      <input type="month" value={value.start_month} required onChange={(event) => onChange({ ...value, start_month: event.target.value })} />
    </label>
    <label className="dashboard-field">עד תאריך
      <input type="month" value={value.end_month} required onChange={(event) => onChange({ ...value, end_month: event.target.value })} />
    </label>
    <label className="dashboard-field">מטבע
      <input type="text" value={value.currency} maxLength={12} required autoComplete="off" aria-label="מטבע" onChange={(event) => onChange({ ...value, currency: event.target.value.toUpperCase() })} />
    </label>
    {message && <span role="alert" className="form-error">{message}</span>}
    <button className="dashboard-action" type="submit" disabled={loading}>{loading ? "טוענים…" : "עדכון תצוגה"}</button>
  </form>;
}

export function QueryState({
  loading,
  error,
  retry,
}: {
  loading: boolean;
  error?: ApiRequestError;
  retry: () => void;
}) {
  if (loading) return <LoadingState label="טוענים נתונים פיננסיים מהשרת…" />;
  if (error) return <ErrorState description={error.message} requestId={error.apiError?.request_id} onRetry={retry} />;
  return null;
}

const chartColors = ["#236557", "#bc8246", "#6985ac", "#9c6f89", "#608360"];
type ChartLine = { key: string; label: string; value: (point: MonthlySeriesPoint) => string | null | undefined };

export function SeriesChart({ points, lines, title }: { points: MonthlySeriesPoint[]; lines: ChartLine[]; title: string }) {
  if (!points.length) return <div className="dashboard-empty">אין נתונים להצגה בתקופה שנבחרה.</div>;
  const width = 720, height = 250, left = 42, right = 16, top = 16, bottom = 42;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const numeric = lines.flatMap((line) => points.map((point) => {
    const raw = line.value(point);
    const parsed = raw == null ? undefined : Number(raw);
    return parsed !== undefined && Number.isFinite(parsed) ? parsed : undefined;
  }).filter((value): value is number => value !== undefined));
  if (!numeric.length) return <div className="dashboard-empty">אין ערכים זמינים בגרף הזה.</div>;
  const min = Math.min(0, ...numeric), max = Math.max(0, ...numeric);
  const span = max - min || 1;
  const x = (index: number) => left + (points.length < 2 ? plotWidth / 2 : index * plotWidth / (points.length - 1));
  const y = (value: number) => top + ((max - value) / span) * plotHeight;
  const tickEvery = Math.max(1, Math.ceil(points.length / 6));
  return <div>
    <svg className="dashboard-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
      <title>{title}</title>
      {[0, 0.5, 1].map((ratio) => <line key={ratio} className="dashboard-chart-grid" x1={left} x2={width - right} y1={top + ratio * plotHeight} y2={top + ratio * plotHeight} />)}
      {min < 0 && max > 0 && <line className="dashboard-chart-grid" x1={left} x2={width - right} y1={y(0)} y2={y(0)} />}
      {lines.map((line, lineIndex) => {
        let segment: string[] = [];
        const segments: string[] = [];
        points.forEach((point, index) => {
          const raw = line.value(point);
          const value = raw == null ? undefined : Number(raw);
          if (value === undefined || !Number.isFinite(value)) {
            if (segment.length) segments.push(segment.join(" "));
            segment = [];
          } else segment.push(`${segment.length ? "L" : "M"}${x(index).toFixed(1)},${y(value).toFixed(1)}`);
        });
        if (segment.length) segments.push(segment.join(" "));
        return <g key={line.key}>
          {segments.map((path, index) => <path key={`${line.key}-${index}`} className="dashboard-chart-line" stroke={chartColors[lineIndex % chartColors.length]} d={path} />)}
          {points.map((point, index) => {
            const raw = line.value(point), value = raw == null ? undefined : Number(raw);
            if (value === undefined || !Number.isFinite(value)) return null;
            return <circle key={`${line.key}-${point.month}`} className="dashboard-chart-dot" cx={x(index)} cy={y(value)} r="3.3" fill={chartColors[lineIndex % chartColors.length]}><title>{`${formatMonth(point.month)} · ${line.label} · ${raw}`}</title></circle>;
          })}
        </g>;
      })}
      {points.map((point, index) => index % tickEvery === 0 || index === points.length - 1
        ? <text key={point.month} x={x(index)} y={height - 13} textAnchor="middle">{formatMonth(point.month)}</text>
        : null)}
    </svg>
    <div className="dashboard-legend">{lines.map((line, index) => <span key={line.key}><i style={{ background: chartColors[index % chartColors.length] }} />{line.label}</span>)}</div>
    <details className="dashboard-chart-data">
      <summary>הצגת נתונים בטבלה</summary>
      <div className="overflow-x-auto">
        <table className="dashboard-data-table" aria-label={`נתוני תרשים: ${title}`}>
          <thead><tr><th scope="col">חודש</th><th scope="col">מדד</th><th scope="col">ערך</th></tr></thead>
          <tbody>{points.flatMap((point) => lines.map((line) => {
            const value = line.value(point);
            return <tr key={`${point.month}:${line.key}`}>
              <td data-label="חודש">{formatMonth(point.month)}</td>
              <td data-label="מדד">{line.label}</td>
              <td data-label="ערך" className="amount">{value ?? "לא זמין"}</td>
            </tr>;
          }))}</tbody>
        </table>
      </div>
    </details>
  </div>;
}

export function CompletenessBanner({ point, freshnessDate, sourceCoverage }: {
  point?: MonthlySeriesPoint | null;
  freshnessDate?: string | null;
  sourceCoverage: string;
}) {
  if (!point) return null;
  const issues = [...new Set([...point.issue_codes, ...point.metrics.completeness.issues])];
  return <section className={`dashboard-completeness${point.complete ? " complete" : ""}`} role="status">
    <strong>{point.complete ? "נתוני החודש מלאים לפי בדיקות השירות" : "הנתונים זמניים; חלק מההשוואות אינן זמינות"}</strong>
    <div className="dashboard-pills">
      <span className="dashboard-pill">עדכון אחרון: {formatDate(freshnessDate)}</span>
      <span className="dashboard-pill">כיסוי: {coverageLabel(sourceCoverage)}</span>
      <span className="dashboard-pill">חוסרים בסיווג: {point.metrics.completeness.unclassified_transaction_count}</span>
      {point.metrics.completeness.open_reconciliation_count > 0 && <span className="dashboard-pill">התאמות פתוחות: {point.metrics.completeness.open_reconciliation_count}</span>}
    </div>
    {issues.length > 0 && <div className="dashboard-pills" aria-label="קודי סוגיות">{issues.map((issue) => <span key={issue} className="dashboard-pill" dir="ltr">{issue}</span>)}</div>}
  </section>;
}

export function ComparisonText({ comparison, currency, label = "השוואה", unit = "amount" }: {
  comparison?: DashboardComparison;
  currency: string;
  label?: string;
  unit?: "amount" | "ratio";
}) {
  if (!comparison) return <span className="dashboard-subvalue">אין נתון השוואה.</span>;
  if (!comparison.available) return <span className="dashboard-subvalue">{label} אינה זמינה: {comparisonReason(comparison.reason)}</span>;
  const display = (value: string | null) => unit === "ratio"
    ? `${value ?? "לא זמין"} יחס`
    : formatAmount(value, currency);
  return <span className="dashboard-subvalue">{label} · הפרש: {display(comparison.delta)} · קודם: {display(comparison.previous)}</span>;
}

export function ActivityExplorer({ points, currency }: { points: MonthlySeriesPoint[]; currency: string }) {
  const monthOptions = points;
  const [month, setMonth] = useState("");
  const [metric, setMetric] = useState("");
  const activeMonth = monthOptions.find((point) => point.month === month) ?? monthOptions.at(-1);

  useEffect(() => {
    if (!activeMonth) { setMonth(""); setMetric(""); return; }
    if (month !== activeMonth.month) setMonth(activeMonth.month);
    const available = Object.keys(activeMonth.metrics.breakdowns);
    if (!available.includes(metric)) setMetric(available[0] ?? "");
  }, [activeMonth, metric, month]);

  const breakdown = activeMonth?.metrics.breakdowns[metric];
  if (!points.length) return <div className="dashboard-empty">אין עסקאות בטווח המסונן.</div>;
  const metricKeys = Object.keys(activeMonth?.metrics.breakdowns ?? {});
  return <section>
    <div className="dashboard-activity-controls">
      <label className="dashboard-field">חודש
        <select value={activeMonth?.month ?? ""} onChange={(event) => setMonth(event.target.value)}>
          {monthOptions.map((point) => <option key={point.month} value={point.month}>{formatMonth(point.month)}</option>)}
        </select>
      </label>
      <label className="dashboard-field">מדד או קטגוריה
        <select value={metric} onChange={(event) => setMetric(event.target.value)}>
          {metricKeys.map((key) => <option key={key} value={key}>{metricLabel(key)}</option>)}
        </select>
      </label>
      <span className="dashboard-pill">{breakdown?.contributor_transaction_ids.length ?? 0} עסקאות תורמות</span>
    </div>
    {breakdown && <ContributorDrilldown key={`${activeMonth?.month}:${metric}`} transactionIds={breakdown.contributor_transaction_ids} currency={currency} />}
  </section>;
}

export function ContributorDrilldown({ transactionIds, currency, label = "הצגת עסקאות תורמות" }: {
  transactionIds: number[];
  currency: string;
  label?: string;
}) {
  const [rows, setRows] = useState<TransactionContribution[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiRequestError>();
  const [loaded, setLoaded] = useState(false);
  useEffect(() => { setRows([]); setError(undefined); setLoaded(false); }, [transactionIds]);

  async function loadContributors() {
    if (!transactionIds.length) return;
    setLoading(true); setError(undefined); setLoaded(false); setRows([]);
    try {
      const ids = [...new Set(transactionIds)];
      const collected: TransactionContribution[] = [];
      for (let index = 0; index < ids.length; index += 100) {
        const result = await apiRequest<TransactionContribution[]>("/dashboard/contributors/query", {
          method: "POST",
          body: JSON.stringify({ transaction_ids: ids.slice(index, index + 100) }),
        });
        collected.push(...result.data);
      }
      setRows(collected); setLoaded(true);
    } catch (reason) {
      setError(reason instanceof ApiRequestError ? reason : new ApiRequestError("לא ניתן לטעון את העסקאות.", 500));
    } finally { setLoading(false); }
  }

  return <div className="dashboard-drilldown">
    <button className="dashboard-link-button" type="button" disabled={!transactionIds.length || loading} onClick={() => void loadContributors()}>
      {loading ? "טוענים עסקאות…" : `${label} (${transactionIds.length})`}
    </button>
    {error && <ErrorState description={error.message} requestId={error.apiError?.request_id} onRetry={() => void loadContributors()} retrying={loading} />}
    {loading && <LoadingState label="טוענים את העסקאות התורמות…" />}
    {!loading && loaded && rows.length === 0 && <div className="dashboard-empty">לא נמצאו עסקאות תורמות.</div>}
    {!loading && rows.length > 0 && <TransactionTable rows={rows} currency={currency} />}
  </div>;
}

export function TransactionTable({ rows, currency }: { rows: TransactionContribution[]; currency: string }) {
  return <div className="overflow-x-auto">
    <table className="dashboard-data-table">
      <caption className="sr-only">עסקאות תורמות למדד שנבחר</caption>
      <thead><tr><th scope="col">תאריך</th><th scope="col">תיאור</th><th scope="col">קטגוריה</th><th scope="col">חשבון</th><th scope="col">סיווג</th><th scope="col">סכום</th></tr></thead>
      <tbody>{rows.map((row) => <tr key={row.transaction_id}>
        <td data-label="תאריך">{formatDate(row.booking_date)}</td>
        <td data-label="תיאור">{row.description}</td>
        <td data-label="קטגוריה">{row.analysis_category ?? row.source_category}</td>
        <td data-label="חשבון">{row.account_label}</td>
        <td data-label="סיווג">{classificationLabel(row.effective_classification)} · {classificationLabel(row.expense_behavior)}</td>
        <td data-label="סכום" className="amount">{formatAmount(row.amount, row.currency || currency)}</td>
      </tr>)}</tbody>
    </table>
  </div>;
}

export function useDashboardReport<T extends { filters: DashboardFilters }>(endpoint: string) {
  const [draft, setDraft] = useState<FilterDraft>(() => inMemoryDashboardFilters
    ? {
      start_month: inMemoryDashboardFilters.start_month.slice(0, 7),
      end_month: inMemoryDashboardFilters.end_month.slice(0, 7),
      currency: inMemoryDashboardFilters.currency,
    }
    : defaultFilterDraft);
  const [applied, setApplied] = useState<DashboardFilters | undefined>(() => inMemoryDashboardFilters);
  const resource = useDashboardResource<T>(endpoint, applied);
  const apply = useCallback((filters: DashboardFilters) => {
    inMemoryDashboardFilters = filters;
    setApplied(filters);
  }, []);
  useEffect(() => {
    if (resource.data && !draft.start_month && !applied) {
      setDraft({
        start_month: resource.data.filters.start_month.slice(0, 7),
        end_month: resource.data.filters.end_month.slice(0, 7),
        currency: resource.data.filters.currency,
      });
    }
  }, [resource.data, draft.start_month, applied]);
  return { ...resource, draft, setDraft, applied, apply };
}
