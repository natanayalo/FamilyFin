"use client";

import "./dashboard.css";
import { ActivityExplorer, ComparisonText, CompletenessBanner, ContributorDrilldown, DashboardFilterForm, QueryState, SeriesChart, useDashboardReport } from "./shared";
import { accountKindLabel, formatAmount, formatMonth, insightLabel } from "./format";
import type { DashboardExpenses, MonthlySeriesPoint } from "./types";

function CategoryDistribution({ data }: { data: DashboardExpenses }) {
  const largest = Math.max(0, ...data.categories.map((item) => Number(item.amount)));
  if (!data.categories.length) return <div className="dashboard-empty">אין קטגוריות הוצאה בחודש שנבחר.</div>;
  return <div className="dashboard-bar-list" role="list" aria-label="התפלגות הוצאות לפי קטגוריה">
    {data.categories.map((item) => {
      const width = largest > 0 ? `${Math.min(100, Number(item.amount) / largest * 100)}%` : "0%";
      return <div className="dashboard-bar-row" role="listitem" key={item.category}>
        <span>{item.category}</span><div className="dashboard-bar-track" aria-hidden="true"><div className="dashboard-bar" style={{ width }} /></div>
        <b>{formatAmount(item.amount, data.currency)}</b>
      </div>;
    })}
  </div>;
}

function BehaviorSummary({ data }: { data: DashboardExpenses }) {
  const items = [
    ["fixed", "הוצאות קבועות"],
    ["variable", "הוצאות משתנות"],
    ["unknown", "התנהגות לא ידועה"],
  ] as const;
  return <div className="dashboard-grid" style={{ gridTemplateColumns: "repeat(3,minmax(0,1fr))" }}>
    {items.map(([key, label]) => <article className="dashboard-card" key={key}>
      <h2>{label}</h2><strong className="dashboard-value">{formatAmount(data.behavior_totals[key] ?? "0", data.currency)}</strong>
    </article>)}
  </div>;
}

function CategoryComparisons({ data }: { data: DashboardExpenses }) {
  if (!data.categories.length) return null;
  return <section className="dashboard-panel">
    <header><div><h2>השוואת קטגוריות</h2><p>הזמינות וההפרשים נשארים כפי שהוחזרו על ידי השירות.</p></div></header>
    <div className="overflow-x-auto"><table className="dashboard-data-table"><thead><tr><th scope="col">קטגוריה</th><th scope="col">נוכחי</th><th scope="col">לעומת חודש קודם</th><th scope="col">לעומת שנה קודמת</th></tr></thead><tbody>
      {data.categories.map((item) => {
        const mom = data.category_comparisons.find((comparison) => comparison.metric === `${item.category}:mom`);
        const yoy = data.category_comparisons.find((comparison) => comparison.metric === `${item.category}:yoy`);
        return <tr key={item.category}>
          <td data-label="קטגוריה">{item.category}</td>
          <td data-label="נוכחי" className="amount">{formatAmount(item.amount, data.currency)}</td>
          <td data-label="לעומת חודש קודם"><ComparisonText comparison={mom} currency={data.currency} label="לעומת חודש קודם" /></td>
          <td data-label="לעומת שנה קודמת"><ComparisonText comparison={yoy} currency={data.currency} label="לעומת שנה קודמת" /></td>
        </tr>;
      })}
    </tbody></table></div>
  </section>;
}

function CategoryTrend({ data }: { data: DashboardExpenses }) {
  const categories = data.categories.slice(0, 5);
  if (!categories.length) return <div className="dashboard-empty">אין קטגוריות להצגת מגמה.</div>;
  return <SeriesChart title="מגמות חודשיות בקטגוריות ההוצאה המובילות" points={data.series} lines={categories.map((category) => ({
    key: category.category,
    label: category.category,
    value: (point: MonthlySeriesPoint) => point.metrics.spending_by_category[category.category],
  }))} />;
}

function ExpenseInsights({ data }: { data: DashboardExpenses }) {
  return <div className="dashboard-two-col">
    <section className="dashboard-panel">
      <header><div><h2>דפוסי הוצאה חוזרים אפשריים</h2><p>כל זיהוי הוא היוריסטי בלבד ואינו סיווג חשבונאי.</p></div></header>
      {data.potential_recurring_spending.length === 0
        ? <div className="dashboard-empty">לא נמצאו דפוסים חוזרים בטווח שנבחר.</div>
        : <div className="dashboard-insight-list">{data.potential_recurring_spending.map((item, index) => <article className="dashboard-insight" key={`${item.normalized_description}-${index}`}>
          <h3>{insightLabel(item.label)}: {item.normalized_description}</h3>
          <p>קטגוריה: {item.analysis_category} · חשבון: {accountKindLabel(item.account_kind)} · מטבע: {item.currency}</p>
          <p>חציון: {formatAmount(item.median_amount, item.currency)} · טווח: {formatAmount(item.minimum_amount, item.currency)}–{formatAmount(item.maximum_amount, item.currency)}</p>
          <p>חודשים: {item.occurrence_months.map(formatMonth).join(" · ")}</p>
          <ContributorDrilldown transactionIds={item.contributor_transaction_ids} currency={item.currency} label="הצגת העסקאות בדפוס" />
        </article>)}</div>}
    </section>
    <section className="dashboard-panel">
      <header><div><h2>שינויים חריגים בקטגוריות</h2><p>הסבר וכללי הזיהוי מגיעים מהשירות.</p></div></header>
      {data.unusual_category_spending.length === 0
        ? <div className="dashboard-empty">לא זוהו שינויים חריגים בתקופה שנבחרה.</div>
        : <div className="dashboard-insight-list">{data.unusual_category_spending.map((item, index) => <article className="dashboard-insight" key={`${item.month}-${item.category}-${index}`}>
          <h3>{insightLabel(item.label)}: {item.category}</h3>
          <p>{formatMonth(item.month)} · {item.direction === "high" ? "מעל הבסיס" : item.direction === "low" ? "מתחת לבסיס" : item.direction}</p>
          <p>הוצאות בתקופה: {formatAmount(item.target_total, item.currency)} · חציון בסיס: {formatAmount(item.baseline_median, item.currency)} · הפרש: {formatAmount(item.difference, item.currency)}</p>
          <p>{item.rule}</p>
          <ContributorDrilldown transactionIds={item.contributor_transaction_ids} currency={item.currency} label="הצגת העסקאות החריגות" />
        </article>)}</div>}
    </section>
  </div>;
}

export function ExpensesFeature() {
  const resource = useDashboardReport<DashboardExpenses>("/dashboard/expenses");
  const data = resource.data;
  const selected = data?.selected_month;
  return <div className="dashboard-feature">
    <DashboardFilterForm value={resource.draft} onChange={resource.setDraft} onApply={resource.apply} loading={resource.loading} />
    {resource.loading && <QueryState loading retry={resource.retry} />}
    {resource.error && <QueryState loading={false} error={resource.error} retry={resource.retry} />}
    {!resource.loading && !resource.error && data && <>
      {data.series.length === 0
        ? <div className="dashboard-empty">לא נמצאו עסקאות במטבע ובתקופה שנבחרו.</div>
        : <>
          <CompletenessBanner point={selected} freshnessDate={selected?.metrics.data_freshness_date} sourceCoverage={selected?.metrics.completeness.source_coverage ?? "unknown"} />
          <section className="dashboard-panel">
            <header><div><h2>הוצאות בחודש {selected ? formatMonth(selected.month) : ""}</h2><p>כל הסכומים במטבע {data.currency} לפי מדדי השירות.</p></div></header>
            <BehaviorSummary data={data} />
          </section>
          <div className="dashboard-two-col">
            <section className="dashboard-panel">
              <header><div><h2>התפלגות לפי קטגוריה</h2><p>ממוינת לפי הסכומים שהחזיר השירות.</p></div></header>
              <CategoryDistribution data={data} />
            </section>
            <section className="dashboard-panel">
              <header><div><h2>מגמות בקטגוריות</h2><p>חמש הקטגוריות המובילות בחודש האחרון בטווח.</p></div></header>
              <CategoryTrend data={data} />
            </section>
          </div>
          <CategoryComparisons data={data} />
          <section className="dashboard-panel">
            <header><div><h2>פעילות עסקאות</h2><p>בחירת חודש ומדד או קטגוריה תציג את התורמים המדויקים שחושבו ב‑Python.</p></div></header>
            <ActivityExplorer points={data.series} currency={data.currency} />
          </section>
          <ExpenseInsights data={data} />
        </>}
      <div className="dashboard-note">נתוני הוצאות הם תצוגה לפי סיווגי המקור. דפוסים חוזרים וחריגות הם רמזים לבדיקה ואינם משנים סיווגים או רישומים.</div>
    </>}
  </div>;
}
