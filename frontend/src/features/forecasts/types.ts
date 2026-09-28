export type ForecastRole = "conservative" | "baseline" | "optimistic";
export type ForecastPoolType = "cash" | "investment";
export type ForecastEventType = "income" | "expense" | "contribution" | "withdrawal";
export type ForecastTargetType = "line" | "category";
export type ForecastAdjustmentOperation = "replacement" | "fixed_delta" | "percentage_change";

export type ForecastPool = {
  name: string;
  pool_type: ForecastPoolType;
  opening_balance: string;
  as_of_date: string;
  net_worth_account_key?: string | null;
  net_worth_snapshot_revision_id?: string | null;
  source_valuation_date?: string | null;
  source_stale?: boolean;
  source_quality_acknowledged?: boolean;
};

export type ForecastRoute = { source_item_id: string; pool_name: string };
export type ForecastAdjustment = {
  target_type: ForecastTargetType;
  target: string;
  operation: ForecastAdjustmentOperation;
  value: string;
  start_month: number;
  end_month: number | null;
};
export type ForecastEvent = {
  event_type: ForecastEventType;
  month: number;
  amount: string;
  label: string;
  pool_name: string | null;
};
export type ForecastCase = {
  role: ForecastRole;
  annual_return_rate: string;
  routes: ForecastRoute[];
  sweep_enabled: boolean;
  sweep_pool_name: string | null;
  adjustments: ForecastAdjustment[];
  events: ForecastEvent[];
  confirmed: boolean;
};

export type ForecastSnapshot = {
  forecast_id: string | null;
  revision_id: string | null;
  revision_number: number;
  assumption_hash: string;
  created_at: string | null;
  scenario_id: string;
  source_revision_id: string;
  source_revision_number: number;
  currency: string;
  horizon_months: number;
  policy_version: string;
  provisional_acknowledged: boolean;
  net_worth_snapshot_revision_id: string | null;
  starting_pools: ForecastPool[];
  cases: ForecastCase[];
  notes: string;
};

export type ForecastSummary = {
  forecast_id: string;
  name: string;
  scenario_id: string;
  source_revision_id: string;
  source_revision_number: number;
  currency: string;
  horizon_months: number;
  current_revision_number: number;
  archived: boolean;
  clone_of_forecast_id: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type ForecastRevisionSummary = {
  revision_id: string;
  forecast_id: string;
  revision_number: number;
  source_revision_id: string;
  source_revision_number: number;
  policy_version: string;
  assumption_hash: string;
  created_at: string | null;
  notes: string;
};

export type MonthlyPoolResult = {
  month_number: number;
  month: string;
  pool_id: string;
  pool_name: string;
  pool_type: ForecastPoolType;
  opening_balance: string;
  estimated_return: string;
  contributions: string;
  swept_surplus: string;
  requested_withdrawal: string;
  fulfilled_withdrawal: string;
  unmet_funding_gap: string;
  requested_capital_draw: string;
  fulfilled_capital_draw: string;
  closing_balance: string;
};

export type ForecastMonth = {
  month_number: number;
  month: string;
  income: string;
  expenses: string;
  contributions: string;
  requested_withdrawals: string;
  fulfilled_withdrawals: string;
  unmet_funding_gap: string;
  swept_surplus: string;
  estimated_returns: string;
  cash_before_sweep: string;
  cash_after_sweep: string;
  ending_balance: string;
  requested_capital_draws: string;
  fulfilled_capital_draws: string;
  pools: MonthlyPoolResult[];
};

export type ForecastProjection = {
  forecast_id: string | null;
  scenario_id: string;
  source_revision_id: string;
  source_revision_number: number;
  currency: string;
  months: ForecastMonth[];
  provisional: boolean;
  issue_codes: string[];
  first_shortfall_month: number | null;
  assumption_hash: string;
  methodology: {
    policy_version: string;
    source_plan_revision_id: string;
    source_plan_revision_number: number;
    calculation_order: string[];
    projection_disclaimer: string;
  } | null;
};

export type ForecastComparisonCheckpoint = {
  horizon_month: number;
  ending_balance: string;
  contributions: string;
  swept_surplus: string;
  withdrawals: string;
  estimated_returns: string;
  funding_gap: string;
};

export type ForecastDraft = {
  projections: Record<ForecastRole, ForecastProjection>;
  comparison: { currency: string; checkpoints: Record<ForecastRole, ForecastComparisonCheckpoint[]> } | null;
  assumption_hash: string;
  validation_errors: string[];
  source_verification?: {
    at_creation: SourceVerification;
    current: SourceVerification;
  };
};

export type SourceVerification = {
  scenario_id: string;
  revision_id: string;
  revision_number: number;
  provisional: boolean;
  issue_codes: string[];
};

export type ForecastRevisionProjection = {
  snapshot: ForecastSnapshot;
  draft: ForecastDraft;
  source_verification: { at_creation: SourceVerification; current: SourceVerification };
};

export type ForecastNetWorthSeed = {
  name: string;
  pool_type: ForecastPoolType;
  opening_balance: string;
  as_of_date: string;
  account_key: string;
  snapshot_revision_id: string;
  valuation_date: string;
  stale: boolean;
  source_quality_acknowledged: boolean;
};

export type ForecastInputPayload = {
  scenario_id: string;
  source_revision_number: number;
  starting_pools: ForecastPool[];
  cases: ForecastCase[];
  notes: string;
  provisional_acknowledged: boolean;
};

export type ForecastActualComparison = {
  forecast_id: string;
  forecast_revision_id: string;
  forecast_revision_number: number;
  role: ForecastRole;
  observed_snapshot_revision_id: string;
  observed_snapshot_date: string;
  projected_month: string;
  account_deltas: Record<string, string>;
  projected_by_account: Record<string, string>;
  observed_by_account: Record<string, string>;
  projected_total: string;
  observed_total: string;
  aggregate_delta: string;
  timing_warning: string | null;
  valuation_date_warning: string | null;
};
