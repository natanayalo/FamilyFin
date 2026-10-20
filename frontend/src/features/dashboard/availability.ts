import type { MonthlySeriesPoint } from "./types";

export function shiftMonth(month: string, offset: number) {
  const [year, number] = month.slice(0, 7).split("-").map(Number);
  const date = new Date(Date.UTC(year, number - 1 + offset, 1));
  return date.toISOString().slice(0, 7);
}

export function hasMonthData(point?: MonthlySeriesPoint | null) {
  if (!point) return false;
  // Older API responses have contributor IDs but no explicit activity count.
  const count = point.metrics.accepted_transaction_count ??
    (new Set(Object.values(point.metrics.breakdowns).flatMap((item) => item.contributor_transaction_ids)).size + point.metrics.completeness.unclassified_transaction_count);
  return count > 0 || (point.metrics.source_period_completeness.source_period_complete ?? point.metrics.source_period_completeness.complete);
}

export function latestAverage(points: MonthlySeriesPoint[], month: string, count: 3 | 6) {
  const field = count === 3 ? "rolling_three_month_averages" : "rolling_six_month_averages";
  return [...points].filter((point) => point.month.slice(0, 7) <= month.slice(0, 7))
    .sort((a, b) => b.month.localeCompare(a.month))
    .find((point) => point.complete && ["gross_income", "net_consumption", "operating_surplus_or_deficit"].every((key) => point.metrics[field][key] != null));
}
