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
