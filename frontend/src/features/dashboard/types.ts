export type DashboardFilters = {
  start_month: string;
  end_month: string;
  currency: string;
};

export type DashboardComparison = {
  metric: string;
  current: string | null;
  previous: string | null;
  delta: string | null;
  available: boolean;
  reason: string | null;
};

export type MetricBreakdown = {
  name: string;
  value: string | null;
  contributor_transaction_ids: number[];
  currency: string | null;
};

export type MonthlyMetrics = {
  month: string;
  currency: string;
  completeness: {
    complete: boolean;
    classification_complete: boolean;
    source_coverage: string;
    open_reconciliation_count: number;
    unclassified_transaction_count: number;
    unclassified_absolute_amount: string;
    issues: string[];
  };
  source_period_completeness: {
    complete: boolean;
    classification_complete: boolean;
    source_coverage: string;
    issues: string[];
  };
  data_freshness_date: string | null;
  gross_income: string;
  gross_consumption: string;
  refunds: string;
  net_consumption: string;
  operating_surplus_or_deficit: string;
  savings_rate: string | null;
  savings_contributions: string;
  savings_withdrawals: string;
  net_observed_savings_transfers: string;
  fixed_consumption: string;
  variable_consumption: string;
  unknown_behavior_consumption: string;
  spending_by_category: Record<string, string>;
  rolling_three_month_averages: Record<string, string | null>;
  rolling_six_month_averages: Record<string, string | null>;
  month_over_month_changes: Record<string, string | null>;
  year_over_year_changes: Record<string, string | null>;
  breakdowns: Record<string, MetricBreakdown>;
};

export type MonthlySeriesPoint = {
  month: string;
  currency: string;
  complete: boolean;
  issue_codes: string[];
  metrics: MonthlyMetrics;
};

export type DashboardOverview = {
  filters: DashboardFilters;
  selected_month: MonthlySeriesPoint | null;
  series: MonthlySeriesPoint[];
  headline: Record<string, string | null>;
  comparisons: DashboardComparison[];
  freshness_date: string | null;
  source_coverage: string;
  currency: string;
};

export type CategorySummary = {
  category: string;
  amount: string;
  contributor_transaction_ids: number[];
};

export type PotentialRecurringSpending = {
  label: string;
  normalized_description: string;
  analysis_category: string;
  currency: string;
  account_kind: string;
  median_amount: string;
  minimum_amount: string;
  maximum_amount: string;
  amount_range: [string, string];
  occurrence_months: string[];
  contributor_transaction_ids: number[];
};

export type UnusualCategorySpending = {
  label: string;
  month: string;
  category: string;
  currency: string;
  baseline_median: string;
  target_total: string;
  difference: string;
  direction: string;
  rule: string;
  contributor_transaction_ids: number[];
};

export type DashboardExpenses = {
  filters: DashboardFilters;
  selected_month: MonthlySeriesPoint | null;
  series: MonthlySeriesPoint[];
  categories: CategorySummary[];
  behavior_totals: Record<string, string>;
  category_comparisons: DashboardComparison[];
  potential_recurring_spending: PotentialRecurringSpending[];
  unusual_category_spending: UnusualCategorySpending[];
  currency: string;
};

export type TransactionContribution = {
  transaction_id: number;
  booking_date: string;
  description: string;
  amount: string;
  currency: string;
  source_category: string;
  movement_type: string | null;
  account_label: string;
  account_kind: string;
  effective_classification: string;
  classification_source: string;
  analysis_category: string | null;
  expense_behavior: string;
};
