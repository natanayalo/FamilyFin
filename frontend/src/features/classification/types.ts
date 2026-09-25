export type ClassificationSource = "override" | "reusable_rule" | "builtin_rule" | "unclassified";
export type EconomicClass =
  | "income"
  | "consumption"
  | "refund"
  | "internal_transfer"
  | "savings_transfer"
  | "credit_card_settlement"
  | "debt_principal"
  | "unclassified";
export type ExpenseBehavior = "fixed" | "variable" | "unknown" | "not_applicable";

export type ClassificationIssue = { code: string; message: string; severity: string };
export type ClassificationResult = {
  transaction_id: number;
  booking_date: string;
  amount: string;
  currency: string;
  account_kind: string;
  source_category: string;
  source_movement_type?: string | null;
  economic_class: EconomicClass;
  expense_behavior: ExpenseBehavior;
  analysis_category?: string | null;
  source: ClassificationSource;
  policy_version: string;
  explanation: string;
  issues: ClassificationIssue[];
  rule_id?: number | null;
  override_ids: number[];
};

export type ReviewItem = {
  transaction_id: number;
  booking_date: string;
  amount: string;
  currency: string;
  description: string;
  account_kind: string;
  source_category: string;
  source_movement_type?: string | null;
  effective_classification: ClassificationResult;
  source_fields: Record<string, unknown>;
  issues: ClassificationIssue[];
  expected_override_version: number;
  expected_classification_state: string;
};

export type Coverage = {
  month?: string | null;
  currency?: string | null;
  total_accepted: number;
  classified_count: number;
  unclassified_count: number;
  review_required_count: number;
  classification_coverage_percent: string | null;
  by_economic_class: Record<EconomicClass, number>;
  by_source: Record<ClassificationSource, number>;
  issue_counts: Record<string, number>;
};

export type ClassificationRule = {
  id: number;
  account_kind: string;
  direction: "debit" | "credit" | "zero";
  source_category: string;
  source_movement_type: string;
  currency: string;
  economic_class: EconomicClass;
  analysis_category?: string | null;
  expense_behavior: ExpenseBehavior;
  is_active: boolean;
  is_tombstone: boolean;
  revision: number;
  supersedes_rule_id?: number | null;
  reason: string;
  created_at?: string | null;
  is_current: boolean;
  effective_active: boolean;
};

export type PageMeta = { request_id?: string; next_cursor?: string | null; limit?: number };
export type ApiEnvelope<T> = { data: T; meta?: PageMeta };
export type RuleDraft = {
  account_kind: string;
  direction: "debit" | "credit" | "zero";
  source_category: string;
  source_movement_type: string | null;
  currency: string;
  economic_class: EconomicClass;
  analysis_category: string | null;
  expense_behavior: ExpenseBehavior | null;
  reason: string;
};
export type RulePreview = { count: number; rule: Omit<ClassificationRule, "id" | "is_current" | "effective_active">; expected_current_rule_id: number | null };
