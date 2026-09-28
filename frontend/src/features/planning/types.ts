export type PlanningKind = "income" | "expense" | "savings_contribution" | "savings_withdrawal";
export type PlanningFrequency = "monthly" | "one_time";

export type PlanningItem = {
  id: string;
  kind: PlanningKind;
  label: string;
  category: string | null;
  amount: string;
  frequency: PlanningFrequency;
  start_month: string | null;
  end_month: string | null;
  occurrence_month: string | null;
  origin: string;
  source_range: string | null;
  source_row: number | null;
  policy_version: string;
  completeness_codes: string[];
  contributor_transaction_ids: number[];
  provenance: Record<string, unknown>;
  notes: Array<Record<string, unknown>>;
};
export type PlanningScenario = {
  scenario_id: string;
  name: string;
  currency: string;
  start_month: string;
  end_month: string;
  current_revision_number: number;
  archived: boolean;
  clone_of_scenario_id: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type PlanningRevision = {
  revision_id: string;
  scenario_id: string;
  revision_number: number;
  items: PlanningItem[];
  notes: string;
  created_at: string | null;
  provisional: boolean;
  issue_codes: string[];
  completeness_snapshot: Array<Record<string, unknown>>;
  expense_notes: Array<Record<string, unknown>>;
};

export type MonthlyPlan = {
  month: string;
  currency: string;
  income: string;
  expenses: string;
  savings_contributions: string;
  savings_withdrawals: string;
  operating_surplus: string;
  net_planned_savings: string;
  cash_remaining_after_savings: string;
  expenses_by_category: Record<string, string>;
  income_by_category: Record<string, string>;
  contributor_item_ids: Record<string, string[]>;
  unmapped_expense_categories: string[];
};

export type PlanningProjection = {
  scenario_id: string;
  revision_number: number;
  currency: string;
  months: MonthlyPlan[];
  provisional: boolean;
  issue_codes: string[];
};

export type PlanningSeedPreview = {
  preview_token: string;
  origin: "historical" | "csv";
  scenario_name: string;
  currency: string;
  start_month: string;
  end_month: string;
  items: Array<PlanningItem | Omit<PlanningItem, "id" | "origin" | "source_range" | "source_row" | "policy_version" | "completeness_codes" | "contributor_transaction_ids" | "provenance" | "notes">>;
  control_checks: Record<string, unknown>;
  ignored_sections: string[];
  mappings: Array<{
    csv_category: string;
    suggested_analysis_categories: string[];
    exact_match: boolean;
    requires_confirmation: boolean;
    status: string;
  }>;
  warnings: string[];
  issue_codes: string[];
  provisional: boolean;
  completeness_snapshot: Array<Record<string, unknown>>;
  file_sha256: string | null;
  filename: string | null;
  duplicate_scenario_id: string | null;
  expense_notes: Array<Record<string, unknown>>;
  expense_target_count: number;
  recurring_income_count: number;
  savings_summary_count: number;
};

export type ScenarioComparison = {
  currency: string;
  months: string[];
  scenarios: Array<{
    scenario_id: string;
    name: string;
    months: Array<MonthlyPlan | null>;
  }>;
};

export type ActualPlanComparison = {
  scenario_id: string;
  revision_number: number;
  currency: string;
  months: Array<{
    month: string;
    complete: boolean;
    issue_codes: string[];
    planned: MonthlyPlan;
    actual_income: string | null;
    actual_expenses: string | null;
    actual_surplus: string | null;
    actual_net_savings: string | null;
    expense_variances: Record<string, string> | null;
    category_variance_unavailable: string[];
    income_variance: string | null;
    surplus_variance: string | null;
    savings_variance: string | null;
  }>;
};
