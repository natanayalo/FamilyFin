"use client";

import "./dashboard.css";
import { ActivityExplorer, ComparisonText, CompletenessBanner, DashboardFilterForm, QueryState, SeriesChart, useDashboardReport } from "./shared";
import { formatAmount } from "./format";
import type { DashboardOverview, MonthlySeriesPoint } from "./types";

const headlineCards = [
  { key: "gross_income", headline: "income", label: "הכנסה" },
  { key: "net_consumption", headline: "net_consumption", label: "צריכה נטו" },
  { key: "operating_surplus_or_deficit", headline: "operating_surplus_or_deficit", label: "עודף או גירעון תפעולי" },
  { key: "savings_rate", headline: "savings_rate", label: "שיעור חיסכון · יחס" },
  { key: "net_observed_savings_transfers", headline: "net_observed_savings_transfers", label: "העברות חיסכון נטו" },
];

function comparisonFor(data: DashboardOverview, key: string, suffix: string) {
  return data.comparisons.find((comparison) => comparison.metric === (suffix ? `${key}:${suffix}` : key));
}

function HeadlineCards({ data }: { data: DashboardOverview }) {
  return <div className="dashboard-grid">
    {headlineCards.map((item) => {
      const value = data.headline[item.headline];
      return <article className="dashboard-card" key={item.key}>
        <h2>{item.label}</h2>
        <strong className="dashboard-value">{item.key === "savings_rate" ? (value == null ? "לא זמין" : `${value} יחס`) : formatAmount(value, data.currency)}</strong>
        <ComparisonText comparison={comparisonFor(data, item.key, "")} currency={data.currency} label="לעומת חודש קודם" unit={item.key === "savings_rate" ? "ratio" : "amount"} />
        <ComparisonText comparison={comparisonFor(data, item.key, "yoy")} currency={data.currency} label="לעומת שנה קודמת" unit={item.key === "savings_rate" ? "ratio" : "amount"} />
      </article>;
    })}
  </div>;
}

function RollingAverages({ selected, currency }: { selected?: MonthlySeriesPoint | null; currency: string }) {
  if (!selected) return null;
  const metrics = selected.metrics;
  const rows = [
    ["הכנסה", "gross_income"],
    ["צריכה נטו", "net_consumption"],
    ["עודף תפעולי", "operating_surplus_or_deficit"],
  ] as const;
  return <section className="dashboard-panel">
    <header><div><h2>ממוצעים נעים</h2><p>הערכים מוצגים כפי שחושבו בשירות; חודש חסר נשאר לא זמין.</p></div></header>
    <div className="overflow-x-auto"><table className="dashboard-data-table"><thead><tr><th scope="col">מדד</th><th scope="col">3 חודשים</th><th scope="col">6 חודשים</th></tr></thead><tbody>
      {rows.map(([label, key]) => <tr key={key}><td data-label="מדד">{label}</td><td data-label="3 חודשים" className="amount">{formatAmount(metrics.rolling_three_month_averages[key], currency)}</td><td data-label="6 חודשים" className="amount">{formatAmount(metrics.rolling_six_month_averages[key], currency)}</td></tr>)}
    </tbody></table></div>
  </section>;
}

function QualityDimensions({ selected, currency }: { selected?: MonthlySeriesPoint | null; currency: string }) {
  if (!selected) return null;
  const metrics = selected.metrics;
  const items = [
    ["כיסוי תקופת מקור", metrics.source_period_completeness.complete ? "מלא" : "חלקי"],
    ["שלמות סיווג", metrics.completeness.classification_complete ? "מלאה" : "חלקית"],
    ["עסקאות ללא סיווג", String(metrics.completeness.unclassified_transaction_count)],
    ["סכום ללא סיווג", formatAmount(metrics.completeness.unclassified_absolute_amount, currency)],
  ];
  return <section className="dashboard-panel">
    <header><div><h2>כיסוי ואיכות</h2><p>מצבי הכיסוי נשארים נפרדים כפי שמדד השירות החזיר אותם.</p></div></header>
    <div className="dashboard-grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))" }}>
      {items.map(([label, value]) => <article className="dashboard-card" key={label}><h3>{label}</h3><strong className="dashboard-value">{value}</strong></article>)}
    </div>
  </section>;
}

export function OverviewFeature() {
  const resource = useDashboardReport<DashboardOverview>("/dashboard/overview");
  const data = resource.data;
  const selected = data?.selected_month;

  return <div className="dashboard-feature">
    <DashboardFilterForm value={resource.draft} onChange={resource.setDraft} onApply={resource.apply} loading={resource.loading} />
    {resource.loading && <QueryState loading retry={resource.retry} />}
    {resource.error && <QueryState loading={false} error={resource.error} retry={resource.retry} />}
    {!resource.loading && !resource.error && data && <>
      {data.series.length === 0
        ? <div className="dashboard-empty">לא נמצאו עסקאות במטבע ובתקופה שנבחרו. לא חושב סכום אפס במקום נתון חסר.</div>
        : <>
          <CompletenessBanner point={selected} freshnessDate={data.freshness_date} sourceCoverage={data.source_coverage} />
          <HeadlineCards data={data} />
          <section className="dashboard-panel">
            <header><div><h2>מגמה חודשית</h2><p>הסכומים נלקחים מהמדדים החודשיים של השירות.</p></div></header>
            <SeriesChart title="מגמת הכנסה, צריכה נטו ועודף תפעולי" points={data.series} lines={[
              { key: "gross_income", label: "הכנסה", value: (point) => point.metrics.gross_income },
              { key: "net_consumption", label: "צריכה נטו", value: (point) => point.metrics.net_consumption },
              { key: "operating_surplus_or_deficit", label: "עודף תפעולי", value: (point) => point.metrics.operating_surplus_or_deficit },
            ]} />
          </section>
          <QualityDimensions selected={selected} currency={data.currency} />
          <RollingAverages selected={selected} currency={data.currency} />
          <section className="dashboard-panel">
            <header><div><h2>פעילות עסקאות</h2><p>בחירת חודש ומדד תציג את העסקאות התורמות מתוך פירוק המדד שהחזיר השירות.</p></div></header>
            <ActivityExplorer points={data.series} currency={data.currency} />
          </section>
        </>}
    </>}
  </div>;
}
