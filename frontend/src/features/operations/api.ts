import { apiRequest } from "@/lib/api";

export type AuditCheck = { name: string; passed: boolean; issue_codes: string[] };
export type OperationsSnapshot = {
  audit: { passed: boolean; checks: AuditCheck[] };
  backup: { configured: boolean; status: string; last_verified_at: string | null };
  run_now_allowed: boolean;
  run_now_block_reason: string | null;
  warnings: string[];
};
export type AutomationInbox = { inbox_file_count: number; review_file_count: number };
export type AutomationRun = {
  id: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  dry_run: boolean;
  audit_passed: boolean;
  backup_created: boolean;
  counts: Record<string, number>;
  issue_codes: string[];
};
export type AutomationStatus = {
  inbox: AutomationInbox;
  operations: OperationsSnapshot;
  latest_run: AutomationRun | null;
};
export type AutomationResult = AutomationRun & {
  items: { status: string; reason_code: string | null }[];
};
export type AttentionFile = { id: string; size_bytes: number; modified_at: string };
export type AttentionPreflight = {
  file_id: string;
  file_sha256: string;
  action: string;
  duplicate_file: boolean;
  ambiguous_count: number;
  reconciliation_count: number;
  candidate_count: number;
  warning_count: number;
  rejected_count: number;
  issue_counts: Record<string, number>;
  predicted_statistics: { inserted: number; updated: number; unchanged: number } | null;
};
export type AttentionCommitResult = {
  batch_id: string;
  status: string;
  statistics: { inserted: number; updated: number; unchanged: number };
};

export function getAutomationStatus() {
  return apiRequest<AutomationStatus>("/automation/status");
}

export function getAutomationRuns() {
  return apiRequest<{ items: AutomationRun[] }>("/automation/runs?limit=20");
}

export function startAutomation(dryRun: boolean) {
  return apiRequest<AutomationResult>("/automation/runs", {
    method: "POST",
    body: JSON.stringify({ dry_run: dryRun }),
  });
}

export function getAttentionFiles() {
  return apiRequest<{ items: AttentionFile[] }>("/automation/attention-files");
}

export function preflightAttentionFile(fileId: string) {
  return apiRequest<AttentionPreflight>(`/automation/attention-files/${fileId}/preflight`, {
    method: "POST",
  });
}

export function commitAttentionFile(fileId: string, expectedSha256: string) {
  return apiRequest<AttentionCommitResult>(`/automation/attention-files/${fileId}/commit`, {
    method: "POST",
    body: JSON.stringify({ expected_sha256: expectedSha256, confirm: true }),
  });
}
