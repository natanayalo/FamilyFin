import { apiRequest } from "@/lib/api";
import type {
  ActualPlanComparison,
  PlanningItem,
  PlanningProjection,
  PlanningRevision,
  PlanningScenario,
  PlanningSeedPreview,
  ScenarioComparison,
} from "./types";

export function getScenarios(includeArchived = true) {
  return apiRequest<PlanningScenario[]>(`/planning/scenarios?include_archived=${includeArchived}`);
}

export function getScenario(scenarioId: string) {
  return apiRequest<PlanningScenario>(`/planning/scenarios/${encodeURIComponent(scenarioId)}`);
}

export function getRevisions(scenarioId: string) {
  return apiRequest<PlanningRevision[]>(`/planning/scenarios/${encodeURIComponent(scenarioId)}/revisions`);
}

export function getRevision(scenarioId: string, revisionNumber: number) {
  return apiRequest<PlanningRevision>(`/planning/scenarios/${encodeURIComponent(scenarioId)}/revisions/${revisionNumber}`);
}

export function getProjection(scenarioId: string, revisionNumber?: number) {
  const suffix = revisionNumber === undefined ? "" : `?revision_number=${revisionNumber}`;
  return apiRequest<PlanningProjection>(`/planning/scenarios/${encodeURIComponent(scenarioId)}/projection${suffix}`);
}

export function getCategories(currency: string) {
  return apiRequest<string[]>(`/planning/categories?currency=${encodeURIComponent(currency)}`);
}

export function getSuggestedStartMonth(currency: string) {
  return apiRequest<string>(`/planning/suggested-start-month?currency=${encodeURIComponent(currency)}`);
}

export function createScenario(body: {
  name: string;
  currency: string;
  start_month: string;
  items: PlanningItem[];
  notes: string;
}) {
  return apiRequest<PlanningScenario>("/planning/scenarios", { method: "POST", body: JSON.stringify(body) });
}

export function postProjection(scenarioId: string, expectedRevisionNumber: number, items: PlanningItem[]) {
  return apiRequest<PlanningProjection>(`/planning/scenarios/${encodeURIComponent(scenarioId)}/projections`, {
    method: "POST",
    body: JSON.stringify({ expected_revision_number: expectedRevisionNumber, items }),
  });
}

export function saveRevision(scenarioId: string, body: {
  expected_revision_number: number;
  items: PlanningItem[];
  notes: string;
  acknowledge_provisional: boolean;
}) {
  return apiRequest<PlanningRevision>(`/planning/scenarios/${encodeURIComponent(scenarioId)}/revisions`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function restoreRevision(scenarioId: string, revisionNumber: number, body: {
  expected_revision_number: number;
  acknowledge_provisional: boolean;
  notes: string;
}) {
  return apiRequest<PlanningRevision>(`/planning/scenarios/${encodeURIComponent(scenarioId)}/revisions/${revisionNumber}/restore`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function cloneScenario(scenarioId: string, body: { name?: string; acknowledge_provisional: boolean }) {
  return apiRequest<PlanningScenario>(`/planning/scenarios/${encodeURIComponent(scenarioId)}/clone`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function setArchived(scenarioId: string, archived: boolean) {
  return apiRequest<PlanningScenario>(`/planning/scenarios/${encodeURIComponent(scenarioId)}/archive`, {
    method: "POST",
    body: JSON.stringify({ archived }),
  });
}

export function previewHistorySeed(body: { name: string; currency: string; start_month: string; history_months: number }) {
  return apiRequest<PlanningSeedPreview>("/planning/seeds/history/previews", { method: "POST", body: JSON.stringify(body) });
}

export function commitHistorySeed(previewToken: string, acknowledgeProvisional: boolean) {
  return apiRequest<PlanningScenario>("/planning/seeds/history/commits", {
    method: "POST",
    body: JSON.stringify({ preview_token: previewToken, acknowledge_provisional: acknowledgeProvisional }),
  });
}

export function previewCsvSeed(file: File, values: { name: string; currency: string; start_month: string }) {
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("name", values.name);
  form.append("currency", values.currency);
  form.append("start_month", values.start_month);
  return apiRequest<PlanningSeedPreview>("/planning/seeds/csv/previews", { method: "POST", body: form });
}

export function commitCsvSeed(file: File, values: {
  previewToken: string;
  mappings: Array<{ csv_category: string; analysis_category: string | null }>;
  acknowledgeProvisional: boolean;
}) {
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("preview_token", values.previewToken);
  form.append("mappings_json", JSON.stringify({ mappings: values.mappings }));
  form.append("acknowledge_provisional", String(values.acknowledgeProvisional));
  return apiRequest<PlanningScenario>("/planning/seeds/csv/commits", { method: "POST", body: form });
}

export function compareScenarios(scenarioIds: string[]) {
  return apiRequest<ScenarioComparison>("/planning/comparisons", { method: "POST", body: JSON.stringify({ scenario_ids: scenarioIds }) });
}

export function compareActual(scenarioId: string) {
  return apiRequest<ActualPlanComparison>(`/planning/scenarios/${encodeURIComponent(scenarioId)}/actual-comparison`);
}
