"use client";

import { Fragment, createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { ApiRequestError, apiRequest, setCsrfToken, subscribeApiHealth, type Session } from "@/lib/api";
import { resetDashboardFilters } from "@/features/dashboard/filter-state";
import { configureServiceWorker } from "@/lib/service-worker";

type AuthState =
  | { status: "loading"; session?: Session }
  | { status: "offline"; session?: Session }
  | { status: "signed-out"; error?: string }
  | { status: "signed-in"; session: Session };

function sessionFrom(state: AuthState): Session | undefined {
  return "session" in state ? state.session : undefined;
}

function offlineState(state: AuthState): AuthState {
  const session = sessionFrom(state);
  return session ? { status: "offline", session: { user: session.user } } : { status: "offline" };
}

type AuthContextValue = {
  auth: AuthState;
  online: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  refreshSession: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAppAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAppAuth must be used within AppProvider");
  return value;
}

function isSession(value: unknown): value is Session {
  return Boolean(value && typeof value === "object" && "user" in value &&
    typeof (value as { user?: { id?: unknown; display_name?: unknown } }).user?.id === "string" &&
    typeof (value as { user?: { display_name?: unknown } }).user?.display_name === "string");
}

export function AppProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [online, setOnline] = useState(false);
  const [auth, setAuth] = useState<AuthState>({ status: "loading" });

  const accountId = useRef<string | undefined>(undefined);
  const publishAuth = useCallback((next: AuthState) => {
    const nextAccountId = sessionFrom(next)?.user.id;
    if (nextAccountId !== accountId.current || next.status === "signed-out") {
      resetDashboardFilters();
    }
    accountId.current = nextAccountId;
    setAuth(next);
  }, []);

  const refreshSession = useCallback(async () => {
    setAuth((previous) => {
      // A background check must not unmount the workspace and discard local drafts.
      if (previous.status === "signed-in") return previous;
      const session = sessionFrom(previous);
      return session ? { status: "loading", session } : { status: "loading" };
    });
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    try {
      const result = await apiRequest<unknown>("/auth/session", { signal: controller.signal });
      if (!isSession(result.data)) {
        publishAuth({ status: "signed-out" });
        return;
      }
      publishAuth({ status: "signed-in", session: result.data });
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 401) publishAuth({ status: "signed-out" });
      else if (error instanceof ApiRequestError && (error.status === 0 || error.status >= 500)) setAuth((previous) => offlineState(previous));
      else publishAuth({ status: "signed-out", error: error instanceof Error ? error.message : "לא ניתן לבדוק את ההתחברות." });
    } finally {
      window.clearTimeout(timeout);
    }
  }, [publishAuth]);

  useEffect(() => {
    const unsubscribeHealth = subscribeApiHealth((health) => {
      if (health === "unreachable") {
        setCsrfToken(undefined);
        setOnline(false);
        setAuth((previous) => offlineState(previous));
      } else if (health === "unauthorized") {
        setOnline(true);
        publishAuth({ status: "signed-out" });
      } else {
        setOnline(true);
      }
    });
    void refreshSession();
    const goOffline = () => {
      void refreshSession();
    };
    const goOnline = () => {
      void refreshSession();
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void refreshSession();
    };
    window.addEventListener("offline", goOffline);
    window.addEventListener("online", goOnline);
    document.addEventListener("visibilitychange", onVisibilityChange);
    void configureServiceWorker(process.env.NODE_ENV === "development").catch(() => undefined);
    return () => {
      unsubscribeHealth();
      window.removeEventListener("offline", goOffline);
      window.removeEventListener("online", goOnline);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [refreshSession, publishAuth]);

  const signIn = useCallback(async (username: string, password: string) => {
    const result = await apiRequest<unknown>("/auth/session", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    if (!isSession(result.data)) throw new Error("התקבלה תשובת התחברות לא תקינה.");
    publishAuth({ status: "signed-in", session: result.data });
  }, [publishAuth]);

  const signOut = useCallback(async () => {
    await apiRequest<void>("/auth/session", { method: "DELETE" });
    setCsrfToken(undefined);
    publishAuth({ status: "signed-out" });
  }, [publishAuth]);

  const value = useMemo(() => ({ auth, online, signIn, signOut, refreshSession }), [auth, online, signIn, signOut, refreshSession]);
  return <AuthContext.Provider value={value}><Fragment key={sessionFrom(auth)?.user.id ?? "signed-out"}>{children}</Fragment></AuthContext.Provider>;
}
