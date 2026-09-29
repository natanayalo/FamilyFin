export type UnknownApartmentMutation = {
  kind: "create" | "clone";
  reconciled: boolean;
  forecastId?: string;
  studyId?: string;
  label?: string;
};

const STORAGE_KEY = "familyfin.apartment.unknown-mutation";

export function readUnknownApartmentMutation(): UnknownApartmentMutation | null {
  if (typeof window === "undefined") return null;
  try {
    const value: unknown = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) ?? "null");
    if (value && typeof value === "object") {
      const candidate = value as Partial<UnknownApartmentMutation>;
      if ((candidate.kind === "create" || candidate.kind === "clone") && typeof candidate.reconciled === "boolean") {
        return candidate as UnknownApartmentMutation;
      }
    }
  } catch {
    // Keep the mutation lock in component state if browser storage is unavailable.
  }
  return null;
}

export function storeUnknownApartmentMutation(operation: UnknownApartmentMutation | null) {
  if (typeof window === "undefined") return;
  try {
    if (operation) window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(operation));
    else window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // The in-memory lock remains active for this page lifetime.
  }
}
