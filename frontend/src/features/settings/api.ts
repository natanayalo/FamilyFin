import { apiRequest } from "@/lib/api";

export type SettingsOverview = {
  preferences: { default_currency: string; default_months: number; updated_at: string | null };
  freshness: {
    familybiz: { last_import_at: string | null; latest_transaction_date: string | null; age_days: number | null };
    planning: { last_import_at: string | null; age_days: number | null };
    net_worth: { last_import_at: string | null; age_days: number | null };
  };
  operations: {
    audit: { passed: boolean; checks: { name: string; passed: boolean; issue_codes: string[] }[] };
    backup: { configured: boolean; status: string; last_verified_at: string | null };
    run_now_allowed: boolean;
    run_now_block_reason: string | null;
    warnings: string[];
  };
  operational_warnings: string[];
  household: { member_count: number; members: string[]; permissions: "equal" };
};
export type UserSession = { id: string; created_at: string; expires_at: string; current: boolean };

export function getSettings() {
  return apiRequest<SettingsOverview>("/settings");
}

export function saveAppPreferences(value: { default_currency: string; default_months: number }) {
  return apiRequest<SettingsOverview["preferences"]>("/settings/preferences", {
    method: "PUT",
    body: JSON.stringify(value),
  });
}

export function getSessions() {
  return apiRequest<{ items: UserSession[] }>("/settings/sessions");
}

export function revokeSession(id: string) {
  return apiRequest<void>(`/settings/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
}
