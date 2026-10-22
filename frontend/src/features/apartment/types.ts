import type { ForecastRole, ForecastRevisionSummary, ForecastSnapshot, ForecastSummary, SourceVerification } from "@/features/forecasts/types";
import type { PlanningItem } from "@/features/planning/types";

export type ApartmentGuardrails = {
  minimum_remaining_liquidity: string | null;
  maximum_housing_cost_to_income_ratio: string | null;
};

export type ApartmentAlternative = {
  name: string;
  forecast_role: ForecastRole;
  purchase_month: number;
  property_price: string;
  family_gift: string;
  purchase_costs: Array<{ label: string; amount: string }>;
  equity_requirement: { mode: "percentage" | "amount"; value: string };
  mortgage: { principal: string; annual_nominal_rate: string; term_months: number };
  pool_draws: Array<{ pool_name: string; amount: string }>;
  stopped_housing_line_ids: string[];
  housing_costs: Array<{ label: string; amount: string }>;
  confirmed: boolean;
};

export type ApartmentInput = {
  forecast_id: string;
  forecast_revision_number: number;
  guardrails: ApartmentGuardrails;
  alternatives: ApartmentAlternative[];
  notes: string;
  source_quality_acknowledged: boolean;
};

export type ApartmentStudy = {
  study_id: string;
  name: string;
  forecast_id: string;
  forecast_revision_id: string;
  forecast_revision_number: number;
  forecast_assumption_hash: string;
  currency: string;
  current_revision_number: number;
  archived: boolean;
  clone_of_study_id: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type ApartmentRevision = {
  revision_id: string;
  study_id: string;
  revision_number: number;
  forecast_id: string;
  forecast_revision_id: string;
  forecast_revision_number: number;
  forecast_assumption_hash: string;
  policy_version: string;
  assumption_hash: string;
  created_at: string | null;
  notes: string;
};

export type ApartmentSnapshot = ApartmentInput & {
  study_id: string | null;
  revision_id: string | null;
  revision_number: number;
  assumption_hash: string;
  created_at: string | null;
  currency: string;
  policy_version: string;
  forecast_revision_id: string;
  forecast_assumption_hash: string;
};

export type ApartmentReadiness = {
  equity_requirement_met: boolean;
  sources_cover_uses: boolean;
  mortgage_within_required_equity: boolean;
  minimum_liquidity_met: boolean;
  housing_ratio_guardrail_met: boolean;
  ready: boolean;
  failures: string[];
};

export type MortgageScheduleRow = {
  period: number;
  payment_month: number | null;
  payment: string;
  interest: string;
  principal: string;
  remaining_principal: string;
};

export type ApartmentMonthlyResult = {
  month_number: number;
  month: string;
  income: string;
  expenses: string;
  housing_cost: string;
  removed_housing_costs: string;
  net_cash_flow_change: string;
  cash_after_sweep: string;
  ending_balance: string;
  pools: Record<string, string>;
};

export type ApartmentProjection = {
  alternative_name: string;
  forecast_role: ForecastRole;
  purchase_month: number;
  purchase_price: string;
  purchase_costs: string;
  total_uses: string;
  proposed_equity: string;
  required_equity: string;
  mortgage_principal: string;
  family_gift: string;
  requested_pool_draws: string;
  fulfilled_pool_draws: string;
  total_sources: string;
  funding_gap: string;
  available_pool_balances: Record<string, string>;
  remaining_liquidity_by_pool: Record<string, string>;
  remaining_liquidity: string;
  mortgage_schedule: MortgageScheduleRow[];
  total_interest: string;
  total_repayment: string;
  monthly: ApartmentMonthlyResult[];
  readiness: ApartmentReadiness;
  maximum_housing_ratio: string | null;
  worst_monthly_cash_flow: string;
  month_36_balance: string;
};

export type ApartmentComparisonRow = {
  alternative_name: string;
  purchase_month: number;
  purchase_price: string;
  forecast_role: ForecastRole;
  mortgage_payment: string;
  total_interest: string;
  closing_gap: string;
  remaining_liquidity: string;
  maximum_housing_ratio: string | null;
  worst_monthly_cash_flow: string;
  month_36_balance: string;
};

export type ApartmentDraft = {
  projections: ApartmentProjection[];
  comparison: { currency: string; alternatives: ApartmentComparisonRow[] } | null;
  assumption_hash: string;
  source_quality_warning: boolean;
};

export type ApartmentSourceOptions = {
  forecast: ForecastSummary;
  forecast_revision: ForecastSnapshot;
  planning_source: { at_creation: SourceVerification; current: SourceVerification };
  expense_lines: PlanningItem[];
};

export type ApartmentSavedProjection = {
  snapshot: ApartmentSnapshot;
  draft: ApartmentDraft;
  source_verification: { at_creation: SourceVerification; current: SourceVerification };
};

export type ApartmentForecastChoice = {
  forecast: ForecastSummary;
  revisions: ForecastRevisionSummary[];
};

export const emptyGuardrails = (): ApartmentGuardrails => ({
  minimum_remaining_liquidity: null,
  maximum_housing_cost_to_income_ratio: null,
});

export function emptyAlternative(index: number, pools: string[] = []): ApartmentAlternative {
  return {
    name: `חלופה ${index + 1}`,
    forecast_role: "baseline",
    purchase_month: 12,
    property_price: "0",
    family_gift: "0",
    purchase_costs: [{ label: "מסים ועלויות רכישה", amount: "0" }, { label: "ייעוץ ובדיקה", amount: "0" }],
    equity_requirement: { mode: "percentage", value: "0.2" },
    mortgage: { principal: "0", annual_nominal_rate: "0", term_months: 360 },
    pool_draws: pools.map((pool_name) => ({ pool_name, amount: "0" })),
    stopped_housing_line_ids: [],
    housing_costs: [{ label: "תחזוקה", amount: "0" }, { label: "ביטוח", amount: "0" }],
    confirmed: false,
  };
}
