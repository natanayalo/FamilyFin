export type ApiEnvelope<T> = {
  data: T;
  meta?: { request_id?: string; next_cursor?: string | null; limit?: number };
};

export type ApiError = {
  code: string;
  message: string;
  fields?: Record<string, string[]>;
  issue_codes?: string[];
  request_id?: string;
};

export class ApiRequestError extends Error {
  public readonly status: number;
  public readonly apiError?: ApiError;

  constructor(message: string, status: number, apiError?: ApiError) {
    super(message);
    this.status = status;
    this.apiError = apiError;
    this.name = "ApiRequestError";
  }
}

export type Session = { user: { id: string; display_name: string }; csrf_token?: string };
export type ApiHealth = "reachable" | "unreachable" | "unauthorized";
let csrfToken: string | undefined;
const healthListeners = new Set<(health: ApiHealth) => void>();

function publishApiHealth(health: ApiHealth) {
  for (const listener of healthListeners) listener(health);
}

export function subscribeApiHealth(listener: (health: ApiHealth) => void) {
  healthListeners.add(listener);
  return () => healthListeners.delete(listener);
}

export function setCsrfToken(token: unknown) {
  csrfToken = typeof token === "string" && token.length > 0 ? token : undefined;
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<ApiEnvelope<T>> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json; charset=utf-8");
  headers.set("Accept", "application/json");
  const method = (init.method || "GET").toUpperCase();
  if (!(method === "GET" || method === "HEAD" || method === "OPTIONS") && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...init,
      headers,
      credentials: "same-origin",
      cache: "no-store",
      referrerPolicy: "no-referrer",
    });
  } catch {
    publishApiHealth("unreachable");
    throw new ApiRequestError("לא ניתן להתחבר לשירות. בדקו את החיבור ונסו שוב.", 0);
  }

  if (response.status === 401) {
    setCsrfToken(undefined);
    publishApiHealth("unauthorized");
  }
  else if (response.status >= 500) publishApiHealth("unreachable");
  else publishApiHealth("reachable");

  if (response.status === 204) return { data: undefined as T };
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiRequestError("התקבלה תשובה לא תקינה מהשירות.", response.status);
  }
  if (!response.ok) {
    const error = (body as { error?: ApiError })?.error;
    throw new ApiRequestError(error?.message || "הבקשה לא הושלמה.", response.status, error);
  }
  const data = (body as ApiEnvelope<unknown>)?.data;
  if (path === "/auth/session" && data && typeof data === "object" && "csrf_token" in data) {
    setCsrfToken((data as { csrf_token?: unknown }).csrf_token);
  }
  return body as ApiEnvelope<T>;
}
