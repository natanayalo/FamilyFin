"use client";

import Link from "next/link";
import { formatHebrewMonth, issueLabel } from "@/lib/display";
import { comparisonReason } from "./format";
import { hasMonthData, latestAverage, shiftMonth } from "./availability";
import { formatStatisticAmount } from "./statistics-format";
import type { DashboardOverview, MonthlySeriesPoint } from "./types";

const rows = [["הכנסה", "gross_income"], ["הוצאות נטו", "net_consumption"], ["עודף או גירעון", "operating_surplus_or_deficit"]] as const;

export function MonthComparisons({ data, month, currency }: { data: DashboardOverview; month: string; currency: string }) {
  const selected = data.selected_month;
  const available = hasMonthData(selected);
  return <section className="dashboard-panel statistics-comparisons" aria-label="השוואת חודש הסקירה">
    <header><div><p className="statistics-eyebrow">לפי חודש הסקירה · {formatHebrewMonth(month)}</p><h2>מה השתנה בחודש הזה?</h2><p>משווים את חודש הסקירה לחודש הקודם ולחודש המקביל בשנה הקודמת, כשהנתונים מלאים.</p></div></header>
    {!available || !selected?.complete ? <div className="statistics-unavailable"><strong>{available ? "ההשוואות יופיעו לאחר השלמת בדיקות החודש" : "אין נתונים לחודש הסקירה כדי להשוות"}</strong><p>{available ? "הסכומים לחודש הזה עדיין זמניים. אין לחשב מהם שינוי מאומת מול תקופות קודמות." : "חודש ללא נתונים אינו חודש עם סכומים אפסיים."}</p><Link className="dashboard-link-button" href="/data-quality">לבדיקת הנתונים</Link></div>
      : <div className="statistics-comparison-grid">{([false, true] as const).map((year) => {
        const comparisons = rows.map(([, key]) => data.comparisons.find((item) => item.metric === `${key}${year ? ":yoy" : ""}`));
        return <section className="statistics-comparison-card" key={String(year)} aria-label={year ? "לעומת שנה קודמת" : "לעומת חודש קודם"}>
          <h3>{year ? "לעומת שנה קודמת" : "לעומת חודש קודם"}</h3><p>{formatHebrewMonth(shiftMonth(month, year ? -12 : -1))}</p>
          {comparisons.every((item) => !item?.available) ? <p className="statistics-unavailable-reason">{[...new Set(comparisons.map((item) => comparisonReason(item?.reason ?? null)))].join(" ")}</p>
            : <dl>{rows.map(([label, key], index) => { const comparison = comparisons[index]; return <div key={key}><dt>{label}</dt><dd>{comparison?.available ? <><strong className="statistics-delta">הפרש {formatStatisticAmount(comparison.delta, currency)}</strong><small>בחודש ההשוואה: {formatStatisticAmount(comparison.previous, currency)}</small></> : <span>{comparisonReason(comparison?.reason ?? null)}</span>}</dd></div>; })}</dl>}
        </section>;
      })}</div>}
    <p>ההפרש הוא סכום חודש הסקירה פחות סכום חודש ההשוואה. חיובי מציין עלייה ושלילי מציין ירידה.</p>
  </section>;
}

export function RollingAverages({ points, month, currency }: { points: MonthlySeriesPoint[]; month: string; currency: string }) {
  const windows = ([3, 6] as const).map((count) => ({ count, point: latestAverage(points, month, count) }));
  const incomplete = points.filter((point) => !point.complete);
  return <section className="dashboard-panel statistics-rolling">
    <header><div><p className="statistics-eyebrow">עד חודש הסקירה · {formatHebrewMonth(month)}</p><h2>ממוצע ברצף חודשים מלאים</h2><p>הממוצע האחרון הזמין ל־3 או ל־6 חודשים רצופים. חודש חלקי עוצר את הרצף ואינו מדולג.</p></div></header>
    <div className="statistics-comparison-grid">{windows.map(({ count, point }) => <article className="statistics-comparison-card" key={count}><h3>{count} חודשים ברצף</h3>
      {point ? <><p className="statistics-window-period">{formatHebrewMonth(shiftMonth(point.month, 1 - count))} עד {formatHebrewMonth(point.month)}</p>{point.month.slice(0, 7) !== month.slice(0, 7) && <p className="statistics-sample-note">הרצף האחרון הזמין מסתיים לפני חודש הסקירה.</p>}<dl>{rows.map(([label, key]) => <div key={key}><dt>{label} לחודש</dt><dd className="statistics-delta">{formatStatisticAmount(point.metrics[count === 3 ? "rolling_three_month_averages" : "rolling_six_month_averages"][key], currency)}</dd></div>)}</dl></>
        : <div className="statistics-unavailable-reason">אין רצף מלא של {count} חודשים בחלונות שנבדקו. לא מוצג ממוצע זמני במקומו.</div>}
    </article>)}</div>
    <details className="statistics-details"><summary>איך נבחר הרצף, ומה חסר?</summary><p>מחברים את הסכומים בחלון ומחלקים במספר החודשים. מחפשים את החלון המלא האחרון שמסתיים באחד מ־12 החודשים {formatHebrewMonth(shiftMonth(month, -11))} עד {formatHebrewMonth(month)}. תחילת החלון עשויה להיות מוקדמת יותר. בשונה מסיכום תקופת הגרף, כאן כל החודשים חייבים להיות מלאים ורציפים. טווח הגרף אינו משנה את החיפוש הזה.</p>
      {incomplete.length > 0 ? <><p>החודשים הבאים בחיפוש עדיין לא הושלמו:</p><ul className="statistics-incomplete-list">{incomplete.map((point) => <li key={point.month}>{formatHebrewMonth(point.month)} · {hasMonthData(point) ? [...new Set([...point.issue_codes, ...point.metrics.completeness.issues])].map(issueLabel).join("; ") || "נתונים חלקיים" : "ללא נתונים או כיסוי מאומת"}{point.metrics.completeness.unclassified_transaction_count > 0 && <Link className="dashboard-link-button" href={`/classification?${new URLSearchParams({ month: point.month.slice(0, 7), currency, economic_class: "unclassified" })}`}>סיווג עסקאות החודש</Link>}</li>)}</ul><Link className="dashboard-link-button" href="/data-quality">בדיקת הכיסוי והאיכות</Link></>
        : <p>{points.length === 0 ? "לא התקבלו נתונים לחיפוש. יש לבדוק את הייבוא." : "אם לא נמצא רצף, אין די היסטוריה מאומתת לפני החודשים המוצגים להשלמתו."}</p>}
    </details>
  </section>;
}
