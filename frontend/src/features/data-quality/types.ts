export type ImportStatistics = {
  total_records: number;
  inserted: number;
  unchanged: number;
  updated: number;
  rejected: number;
  ambiguous: number;
  unresolved: number;
  duplicate_file: boolean;
  non_ils_records: number;
};

export type ImportHistoryItem = {
  id: string;
  source_file_id: number | null;
  parser_version: string;
  baseline_batch_id: string | null;
  report_start: string | null;
  report_end: string | null;
  max_transaction_date: string | null;
  freshness_days: number | null;
  status: string;
  statistics: ImportStatistics;
  issue_codes: string[];
  error_code: string | null;
  created_at: string;
};

export type DataQualitySummary = {
  accepted_rows: number;
  freshness_date: string | null;
  covered_start: string | null;
  covered_end: string | null;
  currencies: Record<string, number>;
  issue_counts: Record<string, number>;
  incomplete_months: string[];
  open_reconciliation_cases: number;
  unclassified_transaction_count: number;
  unclassified_absolute_amount: string;
  source_coverage: string;
  latest_import: ImportHistoryItem | null;
};

export type FamilyBizPreview = {
  preview_token: string;
  inspection: {
    parser_version: string;
    file_sha256: string;
    filename: string | null;
    compressed_bytes: number;
    uncompressed_bytes: number;
    sheet_names: string[];
    section_count: number;
    transaction_count: number;
    report_start: string | null;
    report_end: string | null;
    min_booking_date: string | null;
    max_booking_date: string | null;
    currencies: Record<string, number>;
    account_kinds: Record<string, number>;
    issue_counts: Record<string, number>;
    freshness_as_of: string;
    preview_rows: Array<Record<string, unknown>>;
  };
  parser_version: string;
  file_sha256: string;
  baseline_batch_id: string | null;
  baseline_fingerprint: string;
  matching_baseline_json: string;
  matcher_version: string;
  decision_plan_version: string;
  decision_plan_fingerprint: string;
  decision_plan_json: string;
  candidate_count: number;
  warning_count: number;
  rejected_count: number;
  issue_counts: Record<string, number>;
  preview_rows: Array<Record<string, unknown>>;
  predicted_statistics: ImportStatistics | null;
};

export type ReconciliationSource = {
  booking_date: string;
  allocation_date: string;
  amount: string;
  currency: string;
  original_currency: string | null;
  original_amount: string | null;
  description: string;
  movement_type: string | null;
  category: string;
};

export type ReconciliationCandidate = ReconciliationSource & {
  id: number;
  account: string;
};

export type ReconciliationCase = {
  id: string;
  import_batch_id: string;
  source_record_id: number;
  reason: string;
  created_at: string;
  source: ReconciliationSource | null;
  candidates: ReconciliationCandidate[];
};

export type CollectionPage<T> = {
  items: T[];
};
