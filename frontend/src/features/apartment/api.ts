import { apiRequest } from "@/lib/api";
import type {
  ApartmentDraft,
  ApartmentInput,
  ApartmentRevision,
  ApartmentSavedProjection,
  ApartmentSourceOptions,
  ApartmentStudy,
  ApartmentSnapshot,
} from "./types";

export async function getApartmentStudies(includeArchived = true) {
  return (await apiRequest<ApartmentStudy[]>(`/apartment/studies?include_archived=${includeArchived}`)).data;
}

export async function getApartmentOptions(forecastId: string, revisionNumber: number) {
  const query = new URLSearchParams({ forecast_id: forecastId, forecast_revision_number: String(revisionNumber) });
  return (await apiRequest<ApartmentSourceOptions>(`/apartment/options?${query}`)).data;
}

export async function getApartmentPoolBalances(input: {
  forecastId: string; revisionNumber: number; role: string; purchaseMonth: number;
}) {
  const query = new URLSearchParams({
    forecast_id: input.forecastId,
    forecast_revision_number: String(input.revisionNumber),
    forecast_role: input.role,
    purchase_month: String(input.purchaseMonth),
  });
  return (await apiRequest<Record<string, string>>(`/apartment/pool-balances?${query}`)).data;
}

export async function previewApartment(input: ApartmentInput) {
  return (await apiRequest<ApartmentDraft>("/apartment/previews", { method: "POST", body: JSON.stringify(input) })).data;
}

export async function createApartmentStudy(input: ApartmentInput & { name: string }) {
  return (await apiRequest<ApartmentStudy>("/apartment/studies", { method: "POST", body: JSON.stringify(input) })).data;
}

export async function getApartmentRevisions(studyId: string) {
  return (await apiRequest<ApartmentRevision[]>(`/apartment/studies/${encodeURIComponent(studyId)}/revisions`)).data;
}

export async function getApartmentRevisionProjection(studyId: string, revisionNumber: number) {
  return (await apiRequest<ApartmentSavedProjection>(`/apartment/studies/${encodeURIComponent(studyId)}/revisions/${revisionNumber}/projection`)).data;
}

export async function saveApartmentRevision(studyId: string, body: ApartmentInput & { expected_revision_number: number }) {
  const revision = {
    expected_revision_number: body.expected_revision_number,
    guardrails: body.guardrails,
    alternatives: body.alternatives,
    notes: body.notes,
    source_quality_acknowledged: body.source_quality_acknowledged,
  };
  return (await apiRequest<ApartmentSnapshot>(`/apartment/studies/${encodeURIComponent(studyId)}/revisions`, {
    method: "POST", body: JSON.stringify(revision),
  })).data;
}

export async function restoreApartmentRevision(studyId: string, revisionNumber: number, expectedRevisionNumber: number) {
  return (await apiRequest<ApartmentSnapshot>(`/apartment/studies/${encodeURIComponent(studyId)}/revisions/${revisionNumber}/restore`, {
    method: "POST", body: JSON.stringify({ expected_revision_number: expectedRevisionNumber }),
  })).data;
}

export async function cloneApartmentStudy(studyId: string, name?: string) {
  return (await apiRequest<ApartmentStudy>(`/apartment/studies/${encodeURIComponent(studyId)}/clone`, {
    method: "POST", body: JSON.stringify(name ? { name } : {}),
  })).data;
}

export async function setApartmentArchived(studyId: string, archived: boolean) {
  return (await apiRequest<ApartmentStudy>(`/apartment/studies/${encodeURIComponent(studyId)}/archive`, {
    method: "POST", body: JSON.stringify({ archived }),
  })).data;
}
