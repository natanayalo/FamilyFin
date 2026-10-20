"use client";

import "./dashboard.css";
import "./expenses.css";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { ComparisonText, CompletenessBanner, ContributorDrilldown, DashboardFilterForm, QueryState, SeriesChart, useDashboardReport, useDashboardResource } from "./shared";
import { ExpenseBreakdown } from "./expense-breakdown";
import { MonthPicker } from "@/components/ui/month-picker";
import { comparisonReason, formatAmount, formatMonth, insightLabel } from "./format";
import { RecurringPatterns } from "./recurring-patterns";
import { formatHebrewMonth } from "@/lib/display";
import { hasMonthData } from "./availability";
import type { DashboardExpenses, MonthlySeriesPoint, RecurringPatternReview } from "./types";

function ExpenseDisclosure({ id, title, description, children }: { id?: string; title: string; description?: string; children: ReactNode }) {
  return <details id={id} className="expense-analysis-group" aria-label={title}>
    <summary><span><strong>{title}</strong>{description && <small>{description}</small>}</span><ChevronDown size={18} aria-hidden="true" /></summary>
    <div className="expense-analysis-content">{children}</div>
  </details>;
}

function openQualityDetails() {
  for (const id of ["expense-more-details", "expense-quality"]) {
    const details = document.getElementById(id);
    if (details instanceof HTMLDetailsElement) details.open = true;
  }
}

function BehaviorSummary({ data }: { data: DashboardExpenses }) {
  const items = [
    ["fixed", "הוצאות קבועות"],
    ["variable", "הוצאות משתנות"],
    ["unknown", "טרם סווגו לקבועות או משתנות"],
  ] as const;
  return <>
    <p className="expense-help">החלוקה מתארת עד כמה ההוצאה צפויה: התחייבות קבועה לעומת הוצאה שמשתנה לפי הצריכה. הסכומים מבוססים על הסיווג שנשמר לכל עסקה, לפני החזרים.</p>
    <div className="dashboard-grid expense-behavior-grid">
    {items.map(([key, label]) => <article className="dashboard-card" key={key}>
      <h4>{label}</h4><strong className="dashboard-value">{formatAmount(data.behavior_totals[key] ?? "0", data.currency)}</strong>
      <p>{key === "fixed" ? "התחייבויות שוטפות וצפויות, כמו שכר דירה או מנוי." : key === "variable" ? "הוצאות שמשתנות לפי השימוש והבחירה, כמו קניות בסופר או מסעדות." : "הוצאות שסווגו כהוצאה, אך טרם נקבע אם הן קבועות או משתנות."}</p>
    </article>)}
    </div>
    <p className="expense-help">גם הוצאה משתנה יכולה לחזור בכל חודש. אישור דפוס חוזר אינו משנה את הסיווג הזה.</p>
    <Link className="dashboard-link-button" href={`/classification?${new URLSearchParams({ month: data.selected_month?.month.slice(0, 7) ?? "", currency: data.currency, economic_class: "consumption", include_resolved: "true" })}`}>לעדכון סיווג קבועות ומשתנות</Link>
  </>;
}

function CategoryComparisons({ data }: { data: DashboardExpenses }) {
  if (!data.categories.length) return null;
  const periods = [{ suffix: "mom", label: "לעומת חודש קודם" }, { suffix: "yoy", label: "לעומת שנה קודמת" }];
  const availablePeriods = periods.filter(({ suffix }) => data.category_comparisons.some((item) => item.metric.endsWith(`:${suffix}`) && item.available));
  const unavailable = periods.flatMap(({ suffix, label }) => {
    const reasons = [...new Set(data.category_comparisons.filter((item) => item.metric.endsWith(`:${suffix}`) && !item.available).map((item) => comparisonReason(item.reason)))];
    return reasons.length ? [`${label}: ${reasons.join(" ")}`] : [];
  });
  return <div className="expense-comparison-content">
    <p>השוואות מוצגות רק כשנתוני שני החודשים מלאים.</p>
    {(unavailable.length > 0 || availablePeriods.length === 0) && <div className="expense-comparison-unavailable">
      <strong>{availablePeriods.length ? "חלק מההשוואות עדיין אינן זמינות" : "אין עדיין השוואה זמינה"}</strong>
      {unavailable.length ? <ul className="expense-comparison-notes">{unavailable.map((message) => <li key={message}>{message}</li>)}</ul> : <p>אין נתוני השוואה מאומתים לתקופה הקודמת.</p>}
      {data.selected_month && !data.selected_month.complete && <div>
        <p>בחודש {formatHebrewMonth(data.selected_month.month)} נדרשות הבדיקות הבאות:</p>
        <ul className="expense-comparison-notes">
          {data.selected_month.metrics.source_period_completeness.source_period_complete !== true && <li>כיסוי המקורות לחודש מלא עדיין לא אושר.</li>}
          {data.selected_month.metrics.completeness.unclassified_transaction_count > 0 && <li>{data.selected_month.metrics.completeness.unclassified_transaction_count} עסקאות עדיין ללא סיווג.</li>}
          {data.selected_month.metrics.completeness.open_reconciliation_count > 0 && <li>{data.selected_month.metrics.completeness.open_reconciliation_count} מקרי התאמה עדיין פתוחים.</li>}
        </ul>
      </div>}
      <p>ההשוואה תופיע כשנתוני שני החודשים יהיו מלאים, כולל כיסוי המקורות וסיווג העסקאות.</p>
      <div className="expense-comparison-actions">
        {data.selected_month && !data.selected_month.complete && <a className="dashboard-link-button" href="#expense-quality" onClick={openQualityDetails}>לפרטי הכיסוי של החודש</a>}
        {(data.selected_month?.metrics.completeness.unclassified_transaction_count ?? 0) > 0 && <Link className="dashboard-link-button" href={`/classification?${new URLSearchParams({ month: data.selected_month!.month.slice(0, 7), currency: data.currency, economic_class: "unclassified" })}`}>לסיווג העסקאות החסרות</Link>}
        <Link className="dashboard-link-button" href="/data-quality">לבדיקת איכות הנתונים והמקורות</Link>
      </div>
    </div>}
    {availablePeriods.length > 0 && <div className="overflow-x-auto"><table className="dashboard-data-table"><thead><tr><th scope="col">קטגוריה</th><th scope="col">נוכחי</th>{availablePeriods.map(({ suffix, label }) => <th scope="col" key={suffix}>{label}</th>)}</tr></thead><tbody>
      {data.categories.map((item) => {
        return <tr key={item.category}>
          <td data-label="קטגוריה">{item.category}</td>
          <td data-label="נוכחי" className="amount">{formatAmount(item.amount, data.currency)}</td>
          {availablePeriods.map(({ suffix, label }) => {
            const comparison = data.category_comparisons.find((entry) => entry.metric === `${item.category}:${suffix}`);
            return <td key={suffix} data-label={label}>{comparison?.available ? <ComparisonText comparison={comparison} currency={data.currency} label={label} /> : <span className="dashboard-subvalue">לא זמין</span>}</td>;
          })}
        </tr>;
      })}
    </tbody></table></div>}
  </div>;
}

function CategoryTrend({ data, points }: { data: DashboardExpenses; points: MonthlySeriesPoint[] }) {
  const categories = data.categories.slice(0, 5);
  if (!categories.length) return <div className="dashboard-empty">אין קטגוריות להצגת מגמה.</div>;
  return <SeriesChart title="מגמות חודשיות בקטגוריות ההוצאה המובילות" points={points} lines={categories.map((category) => ({
    key: category.category,
    label: category.category,
    value: (point: MonthlySeriesPoint) => point.metrics.spending_by_category[category.category],
  }))} />;
}

function ExpenseInsights({ data, onReviewSaved }: { data: DashboardExpenses; onReviewSaved: (review: RecurringPatternReview) => void }) {
  return <div className="expense-analysis-stack">
    <ExpenseDisclosure title="דפוסי הוצאה חוזרים אפשריים" description="זיהוי, אישור ומעקב אחר הוצאות חוזרות">
      <RecurringPatterns data={data} onSaved={onReviewSaved} key={data.currency} />
    </ExpenseDisclosure>
    <ExpenseDisclosure title="שינויים חריגים בקטגוריות" description={data.unusual_category_spending.length === 1 ? "שינוי אחד לבדיקה" : data.unusual_category_spending.length ? `${data.unusual_category_spending.length} שינויים לבדיקה` : "לא זוהו שינויים חריגים בטווח"}>
      <p>קטגוריות שבהן ההוצאות שונות מהדפוס הרגיל.</p>
      {data.unusual_category_spending.length === 0
        ? <div className="dashboard-empty">לא זוהו שינויים חריגים בתקופה שנבחרה.</div>
        : <div className="dashboard-insight-list">{data.unusual_category_spending.map((item, index) => <article className="dashboard-insight" key={`${item.month}-${item.category}-${index}`}>
          <h4>{insightLabel(item.label)}: {item.category}</h4>
          <p>{formatMonth(item.month)} · {item.direction === "high" ? "מעל הבסיס" : item.direction === "low" ? "מתחת לבסיס" : item.direction}</p>
          <p>הוצאות בתקופה: {formatAmount(item.target_total, item.currency)} · חציון בסיס: {formatAmount(item.baseline_median, item.currency)} · הפרש: {formatAmount(item.difference, item.currency)}</p>
          <details className="dashboard-diagnostics"><summary>כלל הזיהוי</summary><p>{item.rule}</p></details>
          <ContributorDrilldown transactionIds={item.contributor_transaction_ids} currency={item.currency} label="הצגת העסקאות החריגות" />
        </article>)}</div>}
    </ExpenseDisclosure>
  </div>;
}

export function ExpensesFeature() {
  const trend = useDashboardReport<DashboardExpenses>("/dashboard/expenses");
  const [month, setMonth] = useState("");
  useEffect(() => {
    if (!month && trend.data) {
      const initial = trend.data.filters.end_month.slice(0, 7);
      setMonth(initial);
    }
  }, [month, trend.data]);
  const currency = trend.applied?.currency ?? trend.data?.currency ?? "ILS";
  const resource = useDashboardResource<DashboardExpenses>("/dashboard/expenses", month ? { start_month: `${month}-01`, end_month: `${month}-01`, currency } : undefined, Boolean(month));
  const data = resource.data;
  const selected = data?.selected_month;
  const monthAvailable = hasMonthData(selected);
  const reviewHref = `/classification?${new URLSearchParams({ month: selected?.month.slice(0, 7) ?? "", currency: data?.currency ?? "ILS", economic_class: "consumption", include_resolved: "true" })}`;
  return <div className="dashboard-feature expense-feature">
    <section className="expense-month-picker dashboard-panel" aria-label="בחירת חודש להוצאות">
      <MonthPicker name="report_month" label="חודש להצגה" showLabel value={month} onChange={setMonth} disabled={!month} />
      <p>הסיכום, הקטגוריות והעסקאות מתייחסים לחודש זה בלבד.</p>
    </section>
    <QueryState loading={!month ? trend.loading : resource.loading} error={!month ? trend.error : resource.error} retry={!month ? trend.retry : resource.retry} />
    {!resource.loading && !resource.error && data && <>
      <>
          <section className="expense-summary" aria-label="סיכום הוצאות חודשי">
            <header><h2>ההוצאות של {formatHebrewMonth(month)}</h2><p>הוצאות לפני החזרים, פחות ההחזרים שנרשמו בחודש, שוות להוצאות נטו.</p></header>
            {!monthAvailable && <p className="expense-status">אין נתוני עסקאות לחודש שנבחר. הסכומים אינם זמינים.</p>}
            <div className="expense-totals">
              {([
                ["gross_consumption", "הוצאות לפני החזרים", "סכום העסקאות שסווגו כהוצאה."],
                ["refunds", "החזרים", "מקוזזים בחודש שבו נרשמו, גם אם הרכישה הייתה בחודש אחר."],
                ["net_consumption", "הוצאות נטו", "הסכום שמופיע גם בסקירה החודשית."],
              ] as const).map(([key, label, explanation]) => <article className={`dashboard-card expense-total ${key === "net_consumption" ? "expense-net" : ""}`} key={key}>
                <h3>{label}</h3><strong className="dashboard-value">{formatAmount(monthAvailable ? selected?.metrics[key] : null, data.currency)}</strong><p>{explanation}</p>
              </article>)}
            </div>
            {selected && monthAvailable && !selected.complete && <p className="expense-status"><span>נתונים זמניים לפי העסקאות שהתקבלו. הוצאות שטרם סווגו עשויות לשנות את הסיכום.</span> <a className="dashboard-link-button" href="#expense-quality" onClick={openQualityDetails}>פרטי כיסוי ואיכות</a></p>}
          </section>
          {monthAvailable && Number(data.behavior_totals.unknown ?? "0") > 0 && <div className="expense-behavior-note"><div><strong>הסיווג לקבועות ומשתנות טרם הושלם</strong><p>{formatAmount(data.behavior_totals.unknown, data.currency)} מתוך ההוצאות עדיין ללא סיווג זה.</p></div><Link className="dashboard-link-button" href={reviewHref}>לסיווג ההוצאות</Link></div>}
          <ExpenseBreakdown key={`${month}:${currency}`} data={data} />
            <section className="dashboard-panel expense-trend" aria-label="מגמות לאורך זמן">
              <header><div><h2>מגמות בקטגוריות</h2><p>חמש הקטגוריות המובילות של {formatHebrewMonth(month)} לאורך זמן. שינוי הטווח אינו משנה את חודש הדוח.</p></div></header>
              <DashboardFilterForm value={trend.draft} onChange={trend.setDraft} onApply={trend.apply} loading={trend.loading} scopeLabel="טווח המגמה" formLabel="מסנני טווח המגמה" buttonLabel="עדכון מגמה" />
              <QueryState loading={trend.loading} error={trend.error} retry={trend.retry} />
              {!trend.loading && !trend.error && trend.data && <CategoryTrend data={data} points={trend.data.series} />}
            </section>
          <details id="expense-more-details" className="dashboard-panel expense-more-details">
            <summary><span><strong>תובנות ופירוט נוסף</strong><small>השוואות, דפוסים ובדיקות כיסוי לפי נושא</small></span><ChevronDown size={20} aria-hidden="true" /></summary>
            <div className="expense-more-content">
              {(selected || data.categories.length > 0) && <section className="expense-month-analysis" aria-labelledby="expense-month-analysis-title">
                <header><h3 id="expense-month-analysis-title">פירוט לחודש {formatHebrewMonth(month)}</h3></header>
                {selected && <ExpenseDisclosure id="expense-quality" title="כיסוי ואיכות הנתונים" description="כיסוי מקורות, סיווג והתאמות">
                  <CompletenessBanner point={selected} freshnessDate={selected.metrics.data_freshness_date} sourceCoverage={selected.metrics.completeness.source_coverage ?? "unknown"} />
                </ExpenseDisclosure>}
                {monthAvailable && <ExpenseDisclosure title="סיווג לקבועות ומשתנות" description="פירוט ההוצאות לפני החזרים"><BehaviorSummary data={data} /></ExpenseDisclosure>}
                {data.categories.length > 0 && <ExpenseDisclosure title="השוואת קטגוריות" description={data.category_comparisons.some((item) => item.available) ? "לעומת חודש קודם ושנה קודמת" : "לא זמין עדיין - חסרים נתונים להשוואה"}><CategoryComparisons data={data} /></ExpenseDisclosure>}
              </section>}
              {!trend.loading && !trend.error && trend.data && <section className="expense-period-insights" aria-label="תובנות מטווח המגמה">
                <header><h3>תובנות מטווח המגמה</h3><p>{formatHebrewMonth(trend.data.filters.start_month)} עד {formatHebrewMonth(trend.data.filters.end_month)}. הדפוסים והחריגות מתייחסים לכל הטווח.</p></header>
                <ExpenseInsights data={trend.data} onReviewSaved={(review) => trend.setData((current) => current?.currency === review.pattern.currency ? {
                  ...current, recurring_pattern_reviews: [...(current.recurring_pattern_reviews ?? []).filter((item) => item.pattern.pattern_id !== review.pattern.pattern_id), review],
                } : current)} />
              </section>}
              <p className="dashboard-note">ההוצאות מקובצות לפי הקטגוריה שנקבעה בסיווג, או לפי קטגוריית המקור כשלא נקבעה קטגוריה. דפוסים חוזרים וחריגות הם רמזים לבדיקה ואינם משנים סיווגים או רישומים.</p>
            </div>
          </details>
        </>

    </>}
  </div>;
}
