import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PeriodStatistics } from "@/features/dashboard/period-statistics";
import { MonthComparisons } from "@/features/dashboard/month-statistics";
import { formatStatisticAmount } from "@/features/dashboard/statistics-format";
import type { DashboardOverview, StatisticsPopulation } from "@/features/dashboard/types";

const metric = { mean: "1234.5678", median: "1100.1250", p25: "1050.0000", p75: "1300.0000" };
const population: StatisticsPopulation = { included_months: ["2026-07-01", "2026-08-01"], partial_months: ["2026-08-01"], excluded_months: ["2026-09-01"], sample_count: 2, metrics: { gross_income: metric, net_consumption: metric, operating_surplus_or_deficit: metric } };
const filters = { start_month: "2026-07-01", end_month: "2026-09-01", currency: "ILS" };

// Currency formatter keeps isolate characters; strip them only in test assertions.
const textMoney = (value: string) => value.replace(/[\u2066-\u2069]/g, "");
describe("monthly statistics presentation", () => {
  it.each([
    ["9007199254740993123456.9950", "9,007,199,254,740,993,123,457.00 ש״ח"],
    ["-1.2350", "-1.24 ש״ח"], ["-0.0049", "0.00 ש״ח"], ["0", "0.00 ש״ח"], [null, "לא זמין"],
  ])("rounds presentation exactly for %s", (value, expected) => {
    expect(textMoney(formatStatisticAmount(value, "ILS"))).toBe(expected);
  });

  it("separates missing and excluded partial months without turning them into zeroes", () => {
    render(<PeriodStatistics statistics={{ observed: population, complete: { ...population, included_months: ["2026-07-01"], partial_months: [], excluded_months: ["2026-08-01", "2026-09-01"], sample_count: 1 } }} filters={filters} currency="ILS" />);
    expect(screen.getByText(/1 חודש ללא נתונים או כיסוי מאומת לא נכלל/)).toBeVisible();
    expect(screen.getByText(/כולל 1 חודש עם נתונים חלקיים/)).toBeVisible();
    const raw = screen.getByText("חציון, אחוזונים ואופן החישוב").closest("details")!;
    expect(raw).not.toHaveAttribute("open");
    expect(screen.getAllByText(/1,234.57/).length).toBe(3);
    fireEvent.click(screen.getByRole("radio", { name: /חודשים מלאים בלבד/ }));
    expect(screen.getByText(/1 חודש בחישוב/)).toBeVisible();
    expect(screen.getByText(/2 חודשים מחוץ לחישוב/)).toBeVisible();
    fireEvent.click(screen.getByText("אילו חודשים נכללו בחישוב?"));
    const months = screen.getByText("אילו חודשים נכללו בחישוב?").closest("details")!;
    expect(within(months).getByText("אוגוסט 2026").closest("li")).toHaveTextContent("נתונים חלקיים");
    expect(within(months).getByText("ספטמבר 2026").closest("li")).toHaveTextContent("ללא נתונים או כיסוי מאומת");
    fireEvent.click(screen.getByText("חציון, אחוזונים ואופן החישוב"));
    expect(screen.getAllByText(/1,234.5678/).length).toBeGreaterThan(0);
  });

  it("distinguishes no complete months from unavailable service data", () => {
    const { rerender } = render(<PeriodStatistics statistics={{ observed: population, complete: { ...population, sample_count: 0, included_months: [], excluded_months: [...population.included_months, ...population.excluded_months], partial_months: [] } }} filters={filters} currency="ILS" />);
    fireEvent.click(screen.getByRole("radio", { name: /חודשים מלאים בלבד/ }));
    expect(screen.getByText("עדיין אין חודשים מלאים לחישוב")).toBeVisible();
    expect(screen.queryByText(/0.00/)).not.toBeInTheDocument();
    rerender(<PeriodStatistics filters={filters} currency="ILS" />);
    expect(screen.getByText(/הסיכום לתקופה אינו זמין מהשירות/)).toBeVisible();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });

  it("shows one monthly warning rather than repeating unavailable comparisons", () => {
    const data = { selected_month: { complete: false, metrics: { accepted_transaction_count: 1 } }, comparisons: [] } as unknown as DashboardOverview;
    render(<MonthComparisons data={data} month="2026-09" currency="ILS" />);
    expect(screen.getAllByText("ההשוואות יופיעו לאחר השלמת בדיקות החודש")).toHaveLength(1);
    expect(screen.getByText(/לפי חודש הסקירה · ספטמבר 2026/)).toBeVisible();
    expect(screen.queryByText("לעומת חודש קודם")).not.toBeInTheDocument();
  });

  it("keeps a valid delta separate from an unavailable prior-year comparison", () => {
    const data = { selected_month: { complete: true, metrics: { accepted_transaction_count: 1 } }, comparisons: [
      { metric: "gross_income", available: true, current: "1200", previous: "1000", delta: "200", reason: null },
      ...["gross_income", "net_consumption", "operating_surplus_or_deficit"].map((metric) => ({ metric: `${metric}:yoy`, available: false, reason: "No prior year", current: null, previous: null, delta: null })),
    ] } as unknown as DashboardOverview;
    render(<MonthComparisons data={data} month="2026-09" currency="ILS" />);
    expect(screen.getByText(/200.00/)).toBeVisible();
    expect(screen.getByText("אין נתונים לתקופה הקודמת.")).toBeVisible();
    expect(screen.getByText("אוגוסט 2026")).toBeVisible();
    expect(screen.getByText("ספטמבר 2025")).toBeVisible();
  });
});
