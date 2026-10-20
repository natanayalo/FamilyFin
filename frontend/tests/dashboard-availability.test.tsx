import { render, screen } from "@testing-library/react";
import { SeriesChart } from "@/features/dashboard/shared";
import { describe, expect, it } from "vitest";
import { hasMonthData, latestAverage, shiftMonth } from "@/features/dashboard/availability";
import type { MonthlySeriesPoint } from "@/features/dashboard/types";

function point(month: string, complete = true, count = 0, averages: string | null = "0"): MonthlySeriesPoint {
  return { month, complete, currency: "ILS", issue_codes: [], metrics: {
    month, currency: "ILS", data_freshness_date: null,
    gross_income: "0", gross_consumption: "0", refunds: "0", net_consumption: "0",
    operating_surplus_or_deficit: "0", savings_rate: null, savings_contributions: "0",
    savings_withdrawals: "0", net_observed_savings_transfers: "0", fixed_consumption: "0",
    variable_consumption: "0", unknown_behavior_consumption: "0", spending_by_category: {},
    month_over_month_changes: {}, year_over_year_changes: {},
    accepted_transaction_count: count,
    source_period_completeness: { source_period_complete: complete, complete, classification_complete: true, source_coverage: "unknown", issues: [] },
    completeness: { complete, classification_complete: true, source_coverage: "unknown", open_reconciliation_count: 0, unclassified_transaction_count: 0, unclassified_absolute_amount: "0", issues: [] }, breakdowns: {},
    rolling_three_month_averages: { gross_income: averages, net_consumption: averages, operating_surplus_or_deficit: averages },
    rolling_six_month_averages: { gross_income: averages, net_consumption: averages, operating_surplus_or_deficit: averages },
  } };
}

describe("dashboard availability", () => {
  it("preserves covered zero and activity outside financial breakdowns", () => {
    expect(hasMonthData(point("2026-02", true))).toBe(true);
    expect(hasMonthData(point("2026-02", false, 1))).toBe(true);
    expect(hasMonthData(point("2026-02", false, 0))).toBe(false);
  });
  it("uses the latest service-calculated consecutive window, preserves zero, and excludes future months", () => {
    const series = [point("2026-06"), point("2026-07", false, 1, null), point("2026-08", false, 1, null), point("2026-09")];
    expect(latestAverage(series, "2026-08", 3)?.month).toBe("2026-06");
    expect(latestAverage(series, "2026-08", 6)?.month).toBe("2026-06");
    expect(latestAverage([point("2026-08", false, 1, null)], "2026-08", 3)).toBeUndefined();
    expect(shiftMonth("2026-02", -2)).toBe("2025-12");
  });
});

it("keeps the zero-activity chart scale nonnegative and identifies its currency", () => {
  render(<SeriesChart points={[point("2026-02")]} title="בדיקת אפס" lines={[{ key: "income", label: "הכנסה", value: () => "0" }]} />);
  const chart = screen.getByRole("img", { name: "בדיקת אפס" });
  const labels = Array.from(chart.querySelectorAll("text")).map((item) => item.textContent);
  expect(labels).toContain("ש״ח · סכום חודשי");
  expect(labels).toContain("0");
  expect(labels.some((label) => label?.startsWith("-"))).toBe(false);
});
