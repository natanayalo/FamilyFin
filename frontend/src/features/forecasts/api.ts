import { apiRequest } from "@/lib/api";
import type {
  ForecastActualComparison,
  ForecastDraft,
  ForecastInputPayload,
  ForecastNetWorthSeed,
  ForecastRevisionProjection,
  ForecastRevisionSummary,
  ForecastSnapshot,
  ForecastSummary,
} from "./types";

export async function getForecasts(includeArchived = true) {
  return (await apiRequest<ForecastSummary[]>(`/forecasts?include_archived=${includeArchived}`)).data;
}

export async function getForecast(forecastId: string) {
  return (await apiRequest<ForecastSummary>(`/forecasts/${encodeURIComponent(forecastId)}`)).data;
}

export async function getForecastRevisions(forecastId: string) {
  return (await apiRequest<ForecastRevisionSummary[]>(`/forecasts/${encodeURIComponent(forecastId)}/revisions`)).data;
}

export async function getForecastRevision(forecastId: string, revisionNumber: number) {
  return (await apiRequest<ForecastSnapshot>(`/forecasts/${encodeURIComponent(forecastId)}/revisions/${revisionNumber}`)).data;
}

export async function getForecastProjection(forecastId: string, revisionNumber: number) {
  return (await apiRequest<ForecastRevisionProjection>(`/forecasts/${encodeURIComponent(forecastId)}/revisions/${revisionNumber}/projection`)).data;
}

export async function previewForecast(body: ForecastInputPayload) {
  return (await apiRequest<ForecastDraft>("/forecasts/previews", { method: "POST", body: JSON.stringify(body) })).data;
}

export async function createForecast(body: ForecastInputPayload & { name: string }) {
  return (await apiRequest<ForecastSummary>("/forecasts", { method: "POST", body: JSON.stringify(body) })).data;
}

export async function saveForecastRevision(forecastId: string, body: {
  expected_revision_number: number;
  starting_pools: ForecastInputPayload["starting_pools"];
  cases: ForecastInputPayload["cases"];
  notes: string;
  provisional_acknowledged: boolean;
}) {
  return (await apiRequest<ForecastSnapshot>(`/forecasts/${encodeURIComponent(forecastId)}/revisions`, {
    method: "POST", body: JSON.stringify(body),
  })).data;
}

export async function restoreForecastRevision(forecastId: string, revisionNumber: number, body: {
  expected_revision_number: number;
  notes?: string;
  provisional_acknowledged?: boolean;
}) {
  return (await apiRequest<ForecastSnapshot>(`/forecasts/${encodeURIComponent(forecastId)}/revisions/${revisionNumber}/restore`, {
    method: "POST", body: JSON.stringify(body),
  })).data;
}

export async function cloneForecast(forecastId: string, name?: string) {
  return (await apiRequest<ForecastSummary>(`/forecasts/${encodeURIComponent(forecastId)}/clone`, {
    method: "POST", body: JSON.stringify(name ? { name } : {}),
  })).data;
}

export async function setForecastArchived(forecastId: string, archived: boolean) {
  return (await apiRequest<ForecastSummary>(`/forecasts/${encodeURIComponent(forecastId)}/archive`, {
    method: "POST", body: JSON.stringify({ archived }),
  })).data;
}

export async function getNetWorthSeeds(snapshotRevisionId: string, accountKeys: string[], poolTypes: Record<string, string>) {
  return (await apiRequest<ForecastNetWorthSeed[]>("/forecasts/net-worth-seeds", {
    method: "POST",
    body: JSON.stringify({ snapshot_revision_id: snapshotRevisionId, account_keys: accountKeys, pool_types: poolTypes }),
  })).data;
}

export async function compareForecastActual(forecastId: string, body: {
  observed_snapshot_revision_id: string;
  forecast_revision_number: number;
  role: ForecastActualComparison["role"];
}) {
  return (await apiRequest<ForecastActualComparison>("/net-worth/forecast-comparisons", {
    method: "POST",
    body: JSON.stringify({ forecast_id: forecastId, ...body }),
  })).data;
}
