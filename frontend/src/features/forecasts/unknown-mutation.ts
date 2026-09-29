export type UnknownForecastMutation = { kind: "create" | "clone"; reconciled: boolean };

const STORAGE_KEY = "familyfin.forecasts.unknown-mutation";

export function readUnknownForecastMutation(): UnknownForecastMutation | null {
  if (typeof window === "undefined") return null;
  try {
    const value: unknown = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) ?? "null");
    if (value && typeof value === "object") {
      const candidate = value as Partial<UnknownForecastMutation>;
      if ((candidate.kind === "create" || candidate.kind === "clone") && typeof candidate.reconciled === "boolean") {
        return { kind: candidate.kind, reconciled: candidate.reconciled };
      }
    }
  } catch {
    // Storage may be disabled; keep the lock in component state for this page lifetime.
  }
  return null;
}

export function storeUnknownForecastMutation(operation: UnknownForecastMutation | null) {
  if (typeof window === "undefined") return;
  try {
    if (operation) window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(operation));
    else window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage may be disabled; the in-memory lock still prevents retries until navigation.
  }
}
