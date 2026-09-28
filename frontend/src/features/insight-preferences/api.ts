import { apiRequest } from "@/lib/api";

export type InsightPreferences = {
  planning_scenario_id: string | null;
  planning_revision_id: string | null;
  forecast_id: string | null;
  forecast_revision_id: string | null;
  forecast_role: string | null;
  apartment_study_id: string | null;
  apartment_revision_id: string | null;
  apartment_alternative_name: string | null;
  updated_at: string | null;
};

export type InsightAlert = {
  id: string;
  condition_type: string;
  subject_identity: string;
  currency: string | null;
  evidence_period: string;
  state: "open" | "acknowledged" | "resolved";
  first_seen: string;
  last_seen: string;
  occurrence_count: number;
  evidence: Record<string, unknown>;
};

export type MonthlySummary = {
  id: string;
  revision_number: number;
  month: string;
  currency: string;
  content_hash: string;
  content: Record<string, unknown>;
  markdown: string;
  created_at: string;
};
export type InsightPreferenceOptions = {
  planning_scenarios: { id: string; name: string; currency: string; revision_number: number }[];
  forecasts: { id: string; name: string; currency: string; revision_number: number }[];
  apartment_studies: { id: string; name: string; currency: string; revision_number: number }[];
};

export function getInsightPreferences() {
  return apiRequest<InsightPreferences>("/insights/preferences");
}

export function getInsightPreferenceOptions() {
  return apiRequest<InsightPreferenceOptions>("/insights/preferences/options");
}

export function saveInsightPreferences(value: Omit<InsightPreferences, "updated_at">) {
  return apiRequest<InsightPreferences>("/insights/preferences", {
    method: "PUT",
    body: JSON.stringify(value),
  });
}

export function getInsightAlerts(state?: InsightAlert["state"]) {
  const query = state ? `?state=${encodeURIComponent(state)}` : "";
  return apiRequest<{ items: InsightAlert[] }>(`/insights/alerts${query}`);
}

export function transitionInsightAlert(id: string, action: "acknowledge" | "resolve") {
  return apiRequest<InsightAlert>(`/insights/alerts/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
    body: "{}",
  });
}

export function getMonthlySummaries() {
  return apiRequest<{ items: MonthlySummary[] }>("/insights/monthly-summaries?currency=ILS&limit=50");
}
