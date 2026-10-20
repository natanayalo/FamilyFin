"use client";

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { currencyLabel, formatHebrewMonth, formatPercent, issueLabel } from "@/lib/display";
import { HebrewMonthField, isValidReportMonth } from "./hebrew-month-field";
import { getDashboardFilters, rememberDashboardFilters } from "./filter-state";
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

export function useDashboardResource<T>(endpoint: string, filters?: DashboardFilters, enabled = true) {
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
    if (!enabled) return;
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
  }, [endpoint, query, reloadToken, enabled]);

  return { data, setData, loading, error, retry: () => setReloadToken((value) => value + 1) };
}

export function DashboardFilterForm({
  value,
  onChange,
  onApply,
  loading,
  buttonLabel = "עדכון תצוגה",
  scopeLabel = "תקופת הדוח",
  formLabel = "מסנני תקופה",
}: {
  buttonLabel?: string;
  scopeLabel?: string;
  formLabel?: string;
  value: FilterDraft;
  onChange: (value: FilterDraft) => void;
  onApply: (filters: DashboardFilters) => void;
  loading: boolean;
}) {
  const [message, setMessage] = useState("");
  const [expanded, setExpanded] = useState(false);
  const filterId = useId();
  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submitted = new FormData(event.currentTarget);
    const start = String(submitted.get("start_month") ?? "").trim();
    const end = String(submitted.get("end_month") ?? "").trim();
    if (!isValidReportMonth(start) || !isValidReportMonth(end)) {
      setMessage("יש לבחור חודש התחלה וחודש סיום.");
      const invalid = !isValidReportMonth(start) ? "start_month" : "end_month";
      document.getElementById(`report-${invalid}`)?.focus();
      return;
    }
    const currency = value.currency.trim().toUpperCase();
    if (start > end) { setMessage("חודש ההתחלה צריך להיות לפני חודש הסיום."); return; }
    setMessage("");
    onChange({ start_month: start, end_month: end, currency });
    onApply({ start_month: `${start}-01`, end_month: `${end}-01`, currency });
  }
  return <div className="dashboard-filter-wrap">
    <button type="button" className="dashboard-filter-toggle" aria-expanded={expanded} aria-controls={filterId} onClick={() => setExpanded(!expanded)}>
      <strong>{scopeLabel}</strong><span>{value.start_month && formatHebrewMonth(value.start_month)} עד {value.end_month && formatHebrewMonth(value.end_month)}</span><span>{expanded ? "סגירה" : "שינוי"}</span>
    </button>
    <form id={filterId} className={`dashboard-filter${expanded ? " expanded" : ""}`} onSubmit={submit} noValidate aria-label={formLabel}>
    <HebrewMonthField name="start_month" label="מחודש" boundary="התחלה" value={value.start_month} onChange={(start_month) => onChange({ ...value, start_month })} />
    <HebrewMonthField name="end_month" label="עד חודש" boundary="סיום" value={value.end_month} onChange={(end_month) => onChange({ ...value, end_month })} />
    <button className="dashboard-action" type="submit" disabled={loading}>{loading ? "טוענים…" : buttonLabel}</button>
    {message && <span role="alert" className="form-error dashboard-filter-error">{message}</span>}
  </form></div>;
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

export function SeriesChart({ points, lines, title, presentation = "line" }: { points: MonthlySeriesPoint[]; lines: ChartLine[]; title: string; presentation?: "line" | "income-expense" }) {
  const chartContainer = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  useEffect(() => {
    if (!chartContainer.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, Math.round(entry.contentRect.width))));
    observer.observe(chartContainer.current);
    return () => observer.disconnect();
  }, [points, lines]);
  if (!points.length) return <div className="dashboard-empty">אין נתונים להצגה בתקופה שנבחרה.</div>;
  const height = presentation === "income-expense" ? 206 : 250, left = 78, right = 30, top = 32, bottom = 42;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const numeric = lines.flatMap((line) => points.map((point) => {
    const raw = line.value(point);
    const parsed = raw == null ? undefined : Number(raw);
    return parsed !== undefined && Number.isFinite(parsed) ? parsed : undefined;
  }).filter((value): value is number => value !== undefined));
  if (!numeric.length) return <div className="dashboard-empty">אין ערכים זמינים בגרף הזה.</div>;
  const min = Math.min(0, ...numeric), observedMax = Math.max(0, ...numeric);
  const max = observedMax === min ? min + 1 : observedMax;
  const span = max - min;
  const x = (index: number) => presentation === "income-expense"
    ? left + (index + 0.5) * plotWidth / points.length
    : left + (points.length < 2 ? plotWidth / 2 : index * plotWidth / (points.length - 1));
  const color = (index: number) => presentation === "income-expense" ? ["var(--overview-income)", "var(--overview-expense)", "var(--overview-surplus)"][index] : chartColors[index % chartColors.length];
  const barWidth = Math.min(18, plotWidth / Math.max(1, points.length) * 0.24);
  const y = (value: number) => top + ((max - value) / span) * plotHeight;
  const tickEvery = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(plotWidth / 75))));
  const orderedPoints = [...points].sort((a, b) => a.month.slice(0, 7).localeCompare(b.month.slice(0, 7)));
  return <div ref={chartContainer} className={presentation === "income-expense" ? "overview-chart" : undefined}>
    <svg className="dashboard-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
      <title>{title}</title>
      <text x={left} y={14} textAnchor="start" direction="ltr">{currencyLabel(points[0].currency)} · סכום חודשי</text>
      {[0, 0.25, 0.5, 0.75, 1].map((ratio) => <g key={ratio}>
        <line className="dashboard-chart-grid" x1={left} x2={width - right} y1={top + ratio * plotHeight} y2={top + ratio * plotHeight} />
        <text x={left - 10} y={top + ratio * plotHeight + 4} textAnchor="end" direction="ltr">{new Intl.NumberFormat("he-IL", { maximumFractionDigits: span < 10 ? 2 : 0 }).format(max - ratio * span)}</text>
      </g>)}
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
          {presentation === "income-expense" && lineIndex < 2 ? points.map((point, index) => {
            const raw = line.value(point);
            if (raw == null || !Number.isFinite(Number(raw))) return null;
            const value = Number(raw);
            return <rect key={point.month} x={x(index) + (lineIndex === 0 ? -barWidth - 2 : 2)} y={Math.min(y(0), y(value))} width={barWidth} height={Math.max(0, Math.abs(y(value) - y(0)))} rx="2" fill={color(lineIndex)}><title>{`${formatMonth(point.month)} · ${line.label} · ${formatAmount(raw, point.currency)}`}</title></rect>;
          }) : segments.map((path, index) => <path key={`${line.key}-${index}`} className="dashboard-chart-line" stroke={color(lineIndex)} d={path} />)}
          {(presentation === "income-expense" && lineIndex < 2 ? [] : points).map((point, index) => {
            const raw = line.value(point), value = raw == null ? undefined : Number(raw);
            if (value === undefined || !Number.isFinite(value)) return null;
            return <circle key={`${line.key}-${point.month}`} className="dashboard-chart-dot" cx={x(index)} cy={y(value)} r="3.3" fill={color(lineIndex)}><title>{`${formatMonth(point.month)} · ${line.label} · ${formatAmount(raw, point.currency)}`}</title></circle>;
          })}
        </g>;
      })}
      {points.map((point, index) => index === points.length - 1 || (index % tickEvery === 0 && (index === 0 || points.length - 1 - index >= tickEvery))
        ? <text key={point.month} x={x(index)} y={height - 13} textAnchor="middle">{formatMonth(point.month)}</text>
        : null)}
    </svg>
    <div className="dashboard-legend">{lines.map((line, index) => <span key={line.key}><i style={{ background: color(index) }} />{line.label}</span>)}</div>
    <details className="dashboard-chart-data">
      <summary>הצגת נתונים בטבלה</summary>
      <div className="dashboard-chart-matrix-scroll" role="region" aria-label="גלילת נתוני התרשים" tabIndex={0}>
        <table className="dashboard-data-table dashboard-chart-matrix" aria-label={`נתוני תרשים: ${title}`} dir="ltr">
          <thead><tr>{orderedPoints.map((point) => <th scope="col" key={point.month}><bdi dir="ltr">{formatMonth(point.month)}</bdi></th>)}<th scope="col" dir="rtl">מדד</th></tr></thead>
          <tbody>{lines.map((line) => <tr key={line.key}>
            {orderedPoints.map((point) => {
              const value = line.value(point);
              return <td key={point.month} className="amount">{value == null ? "אין נתונים" : formatAmount(value, point.currency)}</td>;
            })}<th scope="row" dir="rtl">{line.label}</th>
          </tr>)}</tbody>
        </table>
      </div>
    </details>
  </div>;
}

export function CompletenessBanner({ point, freshnessDate, sourceCoverage, importDate, qualityHref }: {
  point?: MonthlySeriesPoint | null;
  freshnessDate?: string | null;
  sourceCoverage: string;
  importDate?: string | null;
  qualityHref?: string;
}) {
  if (!point) return null;
  const issues = [...new Set([...point.issue_codes, ...point.metrics.completeness.issues])];
  return <section className={`dashboard-completeness${point.complete ? " complete" : ""}`} role="status">
    <strong>{point.complete ? "נתוני החודש מלאים לפי בדיקות השירות" : "הנתונים זמניים; חלק מההשוואות אינן זמינות"}</strong>
    <div className="dashboard-pills">
      <span className="dashboard-pill">עסקה אחרונה: {formatDate(freshnessDate)}</span>
      {importDate && <span className="dashboard-pill">ייבוא אחרון: {new Intl.DateTimeFormat("he-IL", { dateStyle: "short", timeStyle: "short" }).format(new Date(importDate))}</span>}
      <span className="dashboard-pill">כיסוי חשבונות: {coverageLabel(sourceCoverage)}</span>
      {point.metrics.completeness.unclassified_transaction_count > 0 && <span className="dashboard-pill">חוסרים בסיווג: {point.metrics.completeness.unclassified_transaction_count}</span>}
      {point.metrics.completeness.open_reconciliation_count > 0 && <span className="dashboard-pill">התאמות פתוחות: {point.metrics.completeness.open_reconciliation_count}</span>}
    </div>
    {!point.complete && qualityHref && <p className="dashboard-completeness-note">הכרטיסים מציגים נתונים זמניים לפי העסקאות שהתקבלו. <a className="dashboard-link-button" href={qualityHref}>לסיבות ולבדיקות הכיסוי והאיכות</a></p>}
    {issues.length > 0 && <><div className="dashboard-pills" aria-label="סוגיות לבדיקה">{issues.map((issue) => <span key={issue} className="dashboard-pill">{issueLabel(issue)}</span>)}</div><details className="dashboard-diagnostics"><summary>פרטים טכניים</summary><ul className="dashboard-issue-explanations">{issues.map((issue) => <li key={issue}><span>{issueLabel(issue)}</span><details className="dashboard-issue-code"><summary>קוד לזיהוי תקלה</summary><code><bdi dir="ltr">{issue}</bdi></code></details></li>)}</ul></details></>}
  </section>;
}

export function ComparisonText({ comparison, currency, label = "השוואה", unit = "amount" }: {
  comparison?: DashboardComparison;
  currency: string;
  label?: string;
  unit?: "amount" | "ratio";
}) {
  if (!comparison) return <span className="dashboard-subvalue">אין נתון השוואה.</span>;
  if (!comparison.available) return <span className="dashboard-subvalue">{label}: {comparisonReason(comparison.reason)}</span>;
  const display = (value: string | null) => unit === "ratio"
    ? formatPercent(value)
    : formatAmount(value, currency);
  return <span className="dashboard-subvalue">{label} · הפרש: {unit === "ratio" && comparison.delta != null ? `${formatPercent(comparison.delta).replace("%", "")} נק׳ אחוז` : display(comparison.delta)} · קודם: {display(comparison.previous)}</span>;
}

export function ActivityExplorer({ point: activeMonth, currency, defaultMetric = "gross_income" }: { point?: MonthlySeriesPoint | null; currency: string; defaultMetric?: string }) {
  const [metric, setMetric] = useState(defaultMetric);

  useEffect(() => {
    if (!activeMonth) { setMetric(""); return; }
    const available = Object.keys(activeMonth.metrics.breakdowns);
    if (!available.includes(metric)) setMetric(available.includes(defaultMetric) ? defaultMetric : available[0] ?? "");
  }, [activeMonth, metric, defaultMetric]);

  const breakdown = activeMonth?.metrics.breakdowns[metric];
  if (!activeMonth) return <div className="dashboard-empty">אין עסקאות בחודש שנבחר.</div>;
  const metricKeys = Object.keys(activeMonth?.metrics.breakdowns ?? {});
  return <section>
    <div className="dashboard-activity-controls">
      <p className="dashboard-field" aria-label="חודש העסקאות">חודש<strong>{formatHebrewMonth(activeMonth.month)}</strong></p>
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

export function ContributorDrilldown({ transactionIds, currency, label = "הצגת עסקאות תורמות", buttonContent }: {
  transactionIds: number[];
  currency: string;
  label?: string;
  buttonContent?: ReactNode;
}) {
  const [rows, setRows] = useState<TransactionContribution[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiRequestError>();
  const [loaded, setLoaded] = useState(false);
  const contentId = useId();
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
    <button className={buttonContent ? "expense-category-trigger" : "dashboard-link-button"} aria-label={buttonContent ? `${label} (${transactionIds.length})` : undefined} aria-expanded={buttonContent ? loaded || loading || !!error : undefined} aria-controls={buttonContent ? contentId : undefined} type="button" disabled={!transactionIds.length || loading} onClick={() => {
      if (buttonContent && (loaded || error)) { setRows([]); setLoaded(false); setError(undefined); }
      else void loadContributors();
    }}>
      {buttonContent ?? (loading ? "טוענים עסקאות…" : `${label} (${transactionIds.length})`)}
    </button>
    <div id={contentId}>
    {error && <ErrorState description={error.message} requestId={error.apiError?.request_id} onRetry={() => void loadContributors()} retrying={loading} />}
    {loading && <LoadingState label="טוענים את העסקאות התורמות…" />}
    {!loading && loaded && rows.length === 0 && <div className="dashboard-empty">לא נמצאו עסקאות תורמות.</div>}
    {!loading && rows.length > 0 && <TransactionTable rows={rows} currency={currency} />}
    </div>
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
  const [draft, setDraft] = useState<FilterDraft>(() => {
    const filters = getDashboardFilters();
    return filters ? { start_month: filters.start_month.slice(0, 7), end_month: filters.end_month.slice(0, 7), currency: filters.currency } : defaultFilterDraft;
  });
  const [applied, setApplied] = useState<DashboardFilters | undefined>(getDashboardFilters);
  const resource = useDashboardResource<T>(endpoint, applied);
  const apply = useCallback((filters: DashboardFilters) => {
    rememberDashboardFilters(filters);
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
