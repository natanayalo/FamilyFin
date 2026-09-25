import { apiRequest } from "@/lib/api";
import type {
  AccountHistoryItem,
  CsvPreview,
  NetWorthAccount,
  NetWorthSummary,
  SnapshotRevision,
  SnapshotSummary,
  TrendPoint,
} from "./types";

export async function getAccounts(options: { includeClosed?: boolean; asOf?: string } = {}) {
  const query = new URLSearchParams();
  if (options.includeClosed) query.set("include_closed", "true");
  if (options.asOf) query.set("as_of", options.asOf);
  const suffix = query.size ? `?${query.toString()}` : "";
  return (await apiRequest<NetWorthAccount[]>(`/net-worth/accounts${suffix}`)).data;
}

export async function getSnapshots(includeArchived = true) {
  return (await apiRequest<SnapshotSummary[]>(`/net-worth/snapshots?include_archived=${includeArchived}`)).data;
}

export async function getRevisions(snapshotId: string) {
  return (await apiRequest<SnapshotRevision[]>(`/net-worth/snapshots/${encodeURIComponent(snapshotId)}/revisions`)).data;
}

export async function getSummary(snapshotId?: string) {
  const query = snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : "";
  return (await apiRequest<NetWorthSummary>(`/net-worth/summary${query}`)).data;
}

export async function getTrend() {
  return (await apiRequest<TrendPoint[]>("/net-worth/trend")).data;
}

export async function getAccountHistory(accountKey: string) {
  return (await apiRequest<AccountHistoryItem[]>(`/net-worth/accounts/${encodeURIComponent(accountKey)}/history`)).data;
}

export async function postCsvPreview(file: File) {
  const form = new FormData();
  form.append("file", file, file.name);
  return (await apiRequest<CsvPreview>("/net-worth/csv/previews", { method: "POST", body: form })).data;
}
