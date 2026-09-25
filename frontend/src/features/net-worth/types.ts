export type NetWorthAccount = {
  id: string;
  account_key: string;
  display_name: string;
  side: "asset" | "liability";
  category: string;
  liquidity: "liquid" | "restricted" | "illiquid" | null;
  owner_label: string | null;
  active_from: string;
  active_to: string | null;
  stale_after_days: number;
  created_at: string | null;
  updated_at: string | null;
};

export type SnapshotSummary = {
  snapshot_id: string;
  snapshot_date: string;
  current_revision_number: number;
  archived: boolean;
  created_at: string | null;
  updated_at: string | null;
};

export type SnapshotBalance = {
  account_key: string;
  amount_ils: string;
  valuation_date: string;
  notes: string;
  account_name: string;
  side: "asset" | "liability";
  category: string;
  liquidity: "liquid" | "restricted" | "illiquid" | null;
  owner_label: string | null;
  stale_after_days: number;
  snapshot_date: string;
  stale: boolean;
};

export type SnapshotRevision = {
  snapshot_id: string;
  revision_id: string;
  revision_number: number;
  snapshot_date: string;
  origin: "manual" | "csv" | "restored";
  notes: string;
  quality_issues: string[];
  quality_acknowledged: boolean;
  content_hash: string;
  active_account_keys: string[];
  source_file_id: number | null;
  balances: SnapshotBalance[];
  created_at: string | null;
  stale_account_keys: string[];
  complete: boolean;
};

export type NetWorthSummary = {
  revision_id: string;
  snapshot_id: string;
  snapshot_date: string;
  revision_number: number;
  total_assets: string;
  total_liabilities: string;
  net_worth: string;
  liquid_assets: string;
  restricted_assets: string;
  illiquid_assets: string;
  stale_account_keys: string[];
  snapshot_freshness_days: number | null;
  by_category: Record<string, string>;
  by_liquidity: Record<string, string>;
  by_owner: Record<string, string>;
  by_account: Record<string, string>;
};

export type TrendPoint = {
  snapshot_date: string;
  revision_id: string;
  total_assets: string;
  total_liabilities: string;
  net_worth: string;
  liquid_assets: string;
  restricted_assets: string;
  illiquid_assets: string;
};

export type AccountHistoryItem = {
  snapshot_date: string;
  revision_number: number;
  revision_id: string;
  account_key: string;
  account_name: string;
  side: string;
  category: string;
  amount_ils: string;
  valuation_date: string;
  notes: string;
};

export type CsvPreview = {
  preview_token: string;
  file_sha256: string;
  snapshot_date: string | null;
  filename: string | null;
  row_count: number;
  rows: Array<Record<string, string | null>>;
  issues: string[];
  warnings: string[];
  duplicate_file: boolean;
  existing_snapshot_id: string | null;
  existing_revision_id: string | null;
  registry_hash: string;
  valid: boolean;
};
