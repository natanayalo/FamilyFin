"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, CircleAlert, CircleCheck, ListFilter } from "lucide-react";
import { MonthPicker } from "@/components/ui/month-picker";
import { RecentTransactions } from "./recent-transactions";
import "./dashboard.css";
import "./overview.css";
import { ActivityExplorer, ComparisonText, CompletenessBanner, DashboardFilterForm, QueryState, SeriesChart, useDashboardReport, useDashboardResource } from "./shared";
import { PeriodStatistics } from "./period-statistics";
import { MonthComparisons, RollingAverages } from "./month-statistics";
import { formatHebrewMonth, formatPercent } from "@/lib/display";
import { coverageLabel, formatAmount, formatMonth } from "./format";
import { hasMonthData, shiftMonth } from "./availability";
import type { DashboardOverview, MonthlySeriesPoint } from "./types";

const headlineCards = [
  { key: "gross_income", headline: "income", label: "הכנסה", explanation: "סכום העסקאות שסווגו כהכנסה בחודש." },
  { key: "net_consumption", headline: "net_consumption", label: "צריכה נטו", explanation: "הוצאות צריכה פחות החזרים. העברות פנימיות וחיסכון אינם צריכה." },
  { key: "operating_surplus_or_deficit", headline: "operating_surplus_or_deficit", label: "עודף או גירעון תפעולי", explanation: "הכנסה פחות צריכה נטו. סכום חיובי הוא עודף; שלילי הוא גירעון." },
  { key: "savings_rate", headline: "savings_rate", label: "שיעור חיסכון", explanation: "עודף תפעולי חלקי הכנסה. זהו שיעור מההכנסה, ולא יתרת החיסכון או ההפקדות בפועל." },
  { key: "net_observed_savings_transfers", headline: "net_observed_savings_transfers", label: "העברות חיסכון נטו", explanation: "הפקדות שסווגו כחיסכון פחות משיכות מחיסכון. זה אינו העודף התפעולי או יתרת החיסכון." },
];

function reviewLink(point: MonthlySeriesPoint) {
  return `/classification?${new URLSearchParams({ month: point.month.slice(0, 7), currency: point.currency, economic_class: "unclassified" })}`;
}

function HeadlineCards({ data, secondary = false }: { data: DashboardOverview; secondary?: boolean }) {
  const selected = data.selected_month;
  if (!selected || !hasMonthData(selected)) return null;
  return <div className={`dashboard-grid dashboard-headlines${secondary ? " overview-secondary-metrics" : ""}`}>
    {(secondary ? headlineCards.slice(3) : headlineCards.slice(0, 3)).map((item) => {
      const value = data.headline[item.headline];
      const unavailable = item.key === "savings_rate" && value == null;
      return <article className={`dashboard-card overview-metric overview-metric-${item.key}${value?.startsWith("-") ? " overview-metric-negative" : ""}`} key={item.key}>
        <h3>{item.key === "gross_income" ? "סה״כ הכנסות" : item.key === "net_consumption" ? "סה״כ הוצאות" : item.label}</h3>
        <strong className="dashboard-value">{item.key === "savings_rate" ? formatPercent(value) : formatAmount(value, data.currency)}</strong>
        <p className="dashboard-subvalue">{item.key === "operating_surplus_or_deficit" ? "הכנסות פחות הוצאות. זו אינה היתרה בחשבון הבנק." : item.key === "net_consumption" ? "לאחר החזרים, ללא העברות וחיסכון." : item.explanation}</p>
        {unavailable && <p className="dashboard-subvalue">{!selected.complete ? "שיעור החיסכון יוצג לאחר השלמת הכיסוי, הסיווג וההתאמות בחודש." : "השיעור אינו מוגדר כשאין הכנסה חיובית בחודש."}</p>}
        {selected.complete ? <><ComparisonText comparison={data.comparisons.find((c) => c.metric === item.key)} currency={data.currency} label="לעומת חודש קודם" unit={item.key === "savings_rate" ? "ratio" : "amount"} />
</> : null}
      </article>;
    })}
  </div>;
}

function QualityDimensions({ selected, currency }: { selected?: MonthlySeriesPoint | null; currency: string }) {
  if (!selected) return null;
  const metrics = selected.metrics;
  const available = hasMonthData(selected);
  const coverage = metrics.source_period_completeness.source_period_complete ?? metrics.source_period_completeness.complete;
  return <section className="dashboard-panel">
    <header><div><h2>כיסוי ואיכות · {formatMonth(selected.month)}</h2><p>הבדיקות מסבירות עד כמה אפשר להסתמך על הסכומים בחודש הסקירה.</p></div></header>
    <div className="dashboard-grid dashboard-quality-grid">
      <article className="dashboard-card"><h3>כיסוי תקופת המקור</h3><strong className="dashboard-value">{coverage ? "מלא" : "חלקי או לא ידוע"}</strong><p className="dashboard-subvalue">{coverage ? "תקופת הייבוא תומכת בחודש מלא לפי בדיקות השירות." : "אין הוכחה שהייבוא מכסה את כל החודש. הסכומים עשויים להשתנות לאחר השלמתו."}</p><Link className="dashboard-link-button" href="/data-quality">בדיקת ייבוא וכיסוי</Link></article>
      <article className="dashboard-card"><h3>כיסוי חשבונות המשפחה</h3><strong className="dashboard-value">{coverageLabel(metrics.completeness.source_coverage)}</strong><p className="dashboard-subvalue">כיסוי תקופה אינו מוכיח שכל חשבונות הבנק והכרטיסים נכללו. יש לוודא שכל המקורות המשפחתיים יובאו.</p></article>
      <article className="dashboard-card"><h3>שלמות הסיווג</h3><strong className="dashboard-value">{!available ? "אין נתונים לבדיקה" : metrics.completeness.classification_complete ? "מלאה" : "חלקית"}</strong>{available ? <p className="dashboard-subvalue">{metrics.completeness.unclassified_transaction_count} עסקאות ללא סיווג · {formatAmount(metrics.completeness.unclassified_absolute_amount, currency)} בערך מוחלט. עסקאות אלה אינן נכללות במדדי ההכנסה והצריכה.</p> : <p className="dashboard-subvalue">לא ניתן להעריך שלמות סיווג לפני קבלת נתוני החודש.</p>}{metrics.completeness.unclassified_transaction_count > 0 && <Link className="dashboard-link-button" href={reviewLink(selected)}>סיווג עסקאות החודש</Link>}</article>
      {metrics.completeness.open_reconciliation_count > 0 && <article className="dashboard-card"><h3>התאמות פתוחות</h3><strong className="dashboard-value">{metrics.completeness.open_reconciliation_count}</strong><p className="dashboard-subvalue">נדרשת בדיקה לפני שהחודש נחשב מלא.</p><Link className="dashboard-link-button" href="/data-quality">בדיקת התאמות</Link></article>}
    </div>
  </section>;
}

export function OverviewFeature() {
  const trend = useDashboardReport<DashboardOverview>("/dashboard/overview");
  const [month, setMonth] = useState("");
  const [statisticsPopulation, setStatisticsPopulation] = useState<"observed" | "complete">("observed");
  useEffect(() => {
    if (!month && trend.data) {
      const initial = (trend.data.freshness_date ?? trend.data.filters.end_month).slice(0, 7);
      setMonth(initial);
    }
  }, [month, trend.data]);
  const currency = trend.applied?.currency ?? trend.data?.currency ?? "ILS";
  const report = useDashboardResource<DashboardOverview>("/dashboard/overview", month ? { start_month: `${shiftMonth(month, -11)}-01`, end_month: `${month}-01`, currency } : undefined, Boolean(month));
  const data = report.data;
  const selected = data?.selected_month;
  const available = hasMonthData(selected);
  const unclassified = selected?.metrics.completeness.unclassified_transaction_count ?? 0;
  const monthFilters = month ? { start_month: `${month}-01`, end_month: `${month}-01`, currency } : undefined;
  return <div className="dashboard-feature overview-feature">
    <header className="overview-heading">
      <div><h1>סקירה כללית</h1><p>תמונה ברורה של ההכנסות, ההוצאות והיתרה החודשית.</p></div>
      <div className="overview-month-selection"><MonthPicker name="report_month" label="חודש לסקירה" value={month} onChange={setMonth} disabled={!month} /></div>
    </header>
    <h2 className="sr-only">סקירת חודש · {month && formatMonth(month)} · {currency}</h2>
    <QueryState loading={report.loading} error={report.error} retry={report.retry} />
    {!report.loading && !report.error && data && <>
      {!available ? <div className="dashboard-empty">אין נתונים לחודש זה במטבע שנבחר. לא התקבלו עסקאות ואין כיסוי מאומת לחודש; אין להסיק שהסכומים הם אפס. <Link className="dashboard-link-button" href="/data-quality">בדיקת ייבוא הנתונים</Link></div> : <>
        <HeadlineCards data={data} />
        <div className="overview-data-status" role="status"><span>{selected?.complete ? <CircleCheck size={15} /> : <CircleAlert size={15} />}{selected?.complete ? "נתוני החודש מלאים לפי בדיקות השירות" : "סכומי החודש זמניים עד להשלמת הבדיקות"}</span><a className="dashboard-link-button" href="#month-quality" onClick={() => { const details = document.getElementById("month-quality")?.querySelector("details"); if (details) details.open = true; }}>פרטי כיסוי ואיכות</a></div>
      </>}
    </>}
    <section className="dashboard-panel overview-trend">
      <header><h2>הכנסות והוצאות בחודשים האחרונים</h2><DashboardFilterForm value={trend.draft} onChange={trend.setDraft} onApply={trend.apply} loading={trend.loading} buttonLabel="עדכון גרף" /></header>
      <QueryState loading={trend.loading} error={trend.error} retry={trend.retry} />
      {!trend.loading && !trend.error && trend.data && <SeriesChart presentation="income-expense" title="מגמת הכנסה, צריכה נטו ועודף תפעולי" points={trend.data.series} lines={[
        { key: "gross_income", label: "הכנסה", value: (point) => hasMonthData(point) ? point.metrics.gross_income : null },
        { key: "net_consumption", label: "צריכה נטו", value: (point) => hasMonthData(point) ? point.metrics.net_consumption : null },
        { key: "operating_surplus_or_deficit", label: "עודף תפעולי", value: (point) => hasMonthData(point) ? point.metrics.operating_surplus_or_deficit : null },
      ]} />}
    </section>
    {!report.loading && !report.error && data && selected && available && <>
      <section className={`overview-review${unclassified ? " needs-review" : ""}`} aria-labelledby="overview-review-title">
        <div>{unclassified ? <CircleAlert aria-hidden="true" /> : <CircleCheck aria-hidden="true" />}<div><h2 id="overview-review-title">{unclassified ? "דורש תשומת לב" : "כל עסקאות החודש מסווגות"}</h2><p>{unclassified ? `${unclassified} עסקאות ללא סיווג אינן נכללות בסיכום. השלימו את הבדיקה כדי לדייק את התמונה.` : "אפשר לעיין בעסקאות ובסיווגים של החודש."}</p></div></div>
        <Link className="overview-primary-action" href={unclassified ? reviewLink(selected) : `/classification?${new URLSearchParams({ month: month, currency, include_resolved: "true" })}`}><ListFilter size={18} />{unclassified ? `סקירת עסקאות (${unclassified})` : "סקירת עסקאות"}<ArrowLeft size={17} /></Link>
      </section>
      <RecentTransactions key={`${month}:${currency}`} filters={monthFilters!} />
    </>}
    <section className="overview-analysis" aria-labelledby="overview-analysis-title">
      <h2 id="overview-analysis-title">פרטים נוספים</h2>
      <section id="month-quality" className="overview-disclosure">
        <details><summary>כיסוי ואיכות הנתונים</summary>
          {!report.loading && !report.error && data && <><CompletenessBanner point={selected} freshnessDate={data.freshness_date} importDate={data.last_import_at} sourceCoverage={data.source_coverage} /><QualityDimensions selected={selected} currency={data.currency} /></>}
        </details>
      </section>
      <details className="overview-disclosure"><summary>סטטיסטיקה והשוואות</summary>
        <p className="overview-scope-note">תקופת הגרף קובעת את הממוצע לתקופה. ההשוואות והרצפים בהמשך מבוססים על חודש הסקירה; המטבע משותף לשניהם.</p>
        {!trend.loading && !trend.error && trend.data && <PeriodStatistics population={statisticsPopulation} onPopulationChange={setStatisticsPopulation} statistics={trend.data.period_statistics} filters={trend.data.filters} currency={trend.data.currency} />}
        <QueryState loading={trend.loading} error={trend.error} retry={trend.retry} />
        <QueryState loading={report.loading} error={report.error} retry={report.retry} />
        {!report.loading && !report.error && data && <>
          <MonthComparisons data={data} month={month} currency={data.currency} />
          <RollingAverages points={data.series} month={month} currency={data.currency} />
          {available && <details className="statistics-details statistics-savings"><summary>עוד על החיסכון · {formatHebrewMonth(month)}</summary><p className="overview-scope-note">לפי חודש הסקירה. שיעור החיסכון והעברות לחיסכון מודדים דברים שונים.</p><HeadlineCards data={data} secondary /></details>}
        </>}
      </details>
      {available && selected && <details className="overview-disclosure"><summary>בדיקת העסקאות שמרכיבות את הסיכום</summary><ActivityExplorer key={`${selected.month}:${currency}`} point={selected} currency={currency} /></details>}
    </section>
  </div>;
}
