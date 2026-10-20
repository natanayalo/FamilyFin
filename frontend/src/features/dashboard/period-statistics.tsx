"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { formatHebrewMonth } from "@/lib/display";
import { formatAmount } from "./format";
import { formatStatisticAmount } from "./statistics-format";
import type { DashboardFilters, PeriodStatisticMetric, PeriodStatistics } from "./types";

type PopulationKey = "observed" | "complete";
const metricRows = [
  ["gross_income", "הכנסה", "סכום העסקאות שסווגו כהכנסה."],
  ["net_consumption", "הוצאות נטו", "הוצאות פחות החזרים, ללא העברות וחיסכון."],
  ["operating_surplus_or_deficit", "עודף או גירעון", "הכנסה פחות הוצאות נטו. זו אינה יתרת הבנק."],
] as const;
const statisticColumns: { key: keyof PeriodStatisticMetric; label: string }[] = [
  { key: "mean", label: "ממוצע" }, { key: "p25", label: "אחוזון 25" },
  { key: "median", label: "חציון" }, { key: "p75", label: "אחוזון 75" },
];
const countLabel = (count: number) => `${count} ${count === 1 ? "חודש" : "חודשים"}`;

export function PeriodStatistics({ statistics, filters, currency, population: selectedPopulation, onPopulationChange }: {
  statistics?: PeriodStatistics; filters: DashboardFilters; currency: string;
  population?: PopulationKey; onPopulationChange?: (key: PopulationKey) => void;
}) {
  const [localPopulation, setLocalPopulation] = useState<PopulationKey>("observed");
  const populationKey = selectedPopulation ?? localPopulation;
  const setPopulationKey = onPopulationChange ?? setLocalPopulation;
  const controlId = useId();
  const population = statistics?.[populationKey];
  const partialMonths = statistics?.observed.partial_months ?? [];
  const missingMonths = statistics?.observed.excluded_months ?? [];
  const period = `${formatHebrewMonth(filters.start_month)} עד ${formatHebrewMonth(filters.end_month)}`;

  return <section className="dashboard-panel dashboard-period-statistics" aria-labelledby={`${controlId}-title`}>
    <header><div><p className="statistics-eyebrow">לפי תקופת הגרף · {period}</p><h2 id={`${controlId}-title`}>ממוצע לחודש בתקופה</h2><p>כמה נכנס, כמה הוצא וכמה נשאר בחודש ממוצע בחודשים שנכללו בחישוב.</p></div></header>
    {statistics && <fieldset className="dashboard-statistics-switch">
      <legend>אילו חודשים לכלול?</legend>
      <label><input type="radio" name={`${controlId}-population`} value="observed" checked={populationKey === "observed"} onChange={() => setPopulationKey("observed")} /><span>כל החודשים עם נתונים<small>כולל חודשים חלקיים</small></span></label>
      <label><input type="radio" name={`${controlId}-population`} value="complete" checked={populationKey === "complete"} onChange={() => setPopulationKey("complete")} /><span>חודשים מלאים בלבד<small>לאחר השלמת בדיקות השירות</small></span></label>
    </fieldset>}
    {population && <div className="statistics-coverage" aria-live="polite">
      <p className="dashboard-period-statistics-count"><strong>{countLabel(population.sample_count)} בחישוב</strong>{population.excluded_months.length > 0 && <> · {countLabel(population.excluded_months.length)} מחוץ לחישוב</>}</p>
      {partialMonths.length > 0 && <p className="dashboard-period-statistics-warning">{populationKey === "observed"
        ? `כולל ${countLabel(partialMonths.length)} עם נתונים חלקיים. הממוצעים זמניים ועשויים להשתנות.`
        : `${countLabel(partialMonths.length)} עם נתונים חלקיים ${partialMonths.length === 1 ? "לא נכלל" : "לא נכללו"} בחישוב.`}</p>}
      {missingMonths.length > 0 && <p>{countLabel(missingMonths.length)} ללא נתונים או כיסוי מאומת {missingMonths.length === 1 ? "לא נכלל" : "לא נכללו"}; אין לחשב חודשים אלה כאפס.</p>}
    </div>}
    {!population ? <div className="dashboard-empty">הסיכום לתקופה אינו זמין מהשירות. אפשר לנסות לטעון מחדש את הדוח.</div>
      : population.sample_count === 0 ? <div className="dashboard-empty"><strong>{populationKey === "observed" ? "אין חודשים עם נתונים לחישוב" : "עדיין אין חודשים מלאים לחישוב"}</strong><p>{populationKey === "observed" ? "לא נמצאו פעילות או כיסוי מאומת בתקופה. אין להסיק שהסכומים הם אפס." : "אפשר לכלול חודשים עם נתונים חלקיים כדי לראות סיכום זמני, או להשלים את בדיקות הנתונים."}</p><Link className="dashboard-link-button" href="/data-quality">בדיקת ייבוא ואיכות הנתונים</Link></div>
        : <>
          <div className="statistics-summary-grid">{metricRows.map(([key, label, explanation]) => <article key={key} className="statistics-summary-card">
            <h3>{label}</h3><strong className="statistics-money">{formatStatisticAmount(population.metrics[key].mean, currency)}</strong>
            <p>{explanation}</p><p className="statistics-median">חציון לחודש <span>{formatStatisticAmount(population.metrics[key].median, currency)}</span></p>
          </article>)}</div>
          {population.sample_count === 1 && <p className="statistics-sample-note">החישוב מבוסס על חודש אחד בלבד, ולכן הממוצע והחציון זהים. עדיין אין כאן דפוס של כמה חודשים.</p>}
        </>}
    {population && <details className="statistics-details"><summary>אילו חודשים נכללו בחישוב?</summary><p>חודש עם פעילות או כיסוי תקופה מאומת יכול להיכלל. חודש עם כיסוי מאומת וללא פעילות יכול להופיע עם סכום אפס. השלמת חודש לפי השירות אינה מוכיחה שכל חשבונות המשפחה יובאו.</p>
      <div className="statistics-month-groups"><div><h3>בחישוב · {population.included_months.length}</h3>{population.included_months.length ? <ul>{population.included_months.map((month) => <li key={month}>{formatHebrewMonth(month)}<span>{partialMonths.includes(month) ? "נתונים חלקיים" : "מלא לפי בדיקות השירות"}</span></li>)}</ul> : <p>אין חודשים בחישוב הזה.</p>}</div>
        {population.excluded_months.length > 0 && <div><h3>מחוץ לחישוב · {population.excluded_months.length}</h3><ul>{population.excluded_months.map((month) => <li key={month}>{formatHebrewMonth(month)}<span>{partialMonths.includes(month) ? "נתונים חלקיים" : "ללא נתונים או כיסוי מאומת"}</span></li>)}</ul></div>}
      </div></details>}
    {population && population.sample_count > 0 && <details className="statistics-details"><summary>חציון, אחוזונים ואופן החישוב</summary>
      <p>כל חודש בחישוב מקבל משקל שווה. הממוצע הוא סכום הסכומים החודשיים חלקי מספר החודשים. החציון הוא הערך האמצעי לאחר מיון הסכומים, ופחות מושפע מחודש חריג.</p>
      <p>אחוזונים 25 ו־75 מסמנים את גבולות החצי האמצעי של הסכומים החודשיים. הגבולות מחושבים בין ערכים סמוכים, ולכן אינם בהכרח סכום של חודש מסוים. בכרטיסים הסכומים מעוגלים לשתי ספרות אחרי הנקודה; כאן נשמר הדיוק שהתקבל מהשירות.</p>
      <div className="dashboard-period-statistics-scroll" role="region" aria-label="טבלת סטטיסטיקה חודשית" tabIndex={0}><table className="dashboard-data-table dashboard-period-statistics-table"><caption className="sr-only">סטטיסטיקה חודשית במטבע {currency} לתקופה {period}</caption>
        <thead><tr><th scope="col">מדד</th>{statisticColumns.map((column) => <th scope="col" key={column.key}>{column.label}</th>)}</tr></thead><tbody>{metricRows.map(([key, label]) => <tr key={key}><th scope="row">{label}</th>{statisticColumns.map((column) => <td className="amount" key={column.key}>{formatAmount(population.metrics[key][column.key], currency)}</td>)}</tr>)}</tbody>
      </table></div></details>}
  </section>;
}
