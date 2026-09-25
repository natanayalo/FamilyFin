"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ApiRequestError, apiRequest, setCsrfToken, subscribeApiHealth, type Session } from "@/lib/api";

type AuthState =
  | { status: "loading" }
  | { status: "offline" }
  | { status: "signed-out"; error?: string }
  | { status: "signed-in"; session: Session };

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

  const refreshSession = useCallback(async () => {
    if (typeof navigator !== "undefined" && !navigator.onLine) {
      setCsrfToken(undefined);
      setOnline(false);
      setAuth({ status: "offline" });
      return;
    }
    setAuth({ status: "loading" });
    try {
      const result = await apiRequest<unknown>("/auth/session");
      if (!isSession(result.data)) {
        setAuth({ status: "signed-out" });
        return;
      }
      setAuth({ status: "signed-in", session: result.data });
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 401) setAuth({ status: "signed-out" });
      else if (error instanceof ApiRequestError && (error.status === 0 || error.status === 503)) setAuth({ status: "offline" });
      else setAuth({ status: "signed-out", error: error instanceof Error ? error.message : "לא ניתן לבדוק את ההתחברות." });
    }
  }, []);

  useEffect(() => {
    const unsubscribeHealth = subscribeApiHealth((health) => {
      if (health === "unreachable") {
        setCsrfToken(undefined);
        setOnline(false);
        setAuth({ status: "offline" });
      } else if (health === "unauthorized") {
        setOnline(true);
        setAuth({ status: "signed-out" });
      } else {
        setOnline(true);
      }
    });
    void refreshSession();
    const goOffline = () => {
      setCsrfToken(undefined);
      setOnline(false);
      setAuth({ status: "offline" });
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
    if ("serviceWorker" in navigator) void navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => undefined);
    return () => {
      unsubscribeHealth();
      window.removeEventListener("offline", goOffline);
      window.removeEventListener("online", goOnline);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [refreshSession]);

  const signIn = useCallback(async (username: string, password: string) => {
    const result = await apiRequest<unknown>("/auth/session", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    if (!isSession(result.data)) throw new Error("התקבלה תשובת התחברות לא תקינה.");
    setAuth({ status: "signed-in", session: result.data });
  }, []);

  const signOut = useCallback(async () => {
    await apiRequest<void>("/auth/session", { method: "DELETE" });
    setCsrfToken(undefined);
    setAuth({ status: "signed-out" });
  }, []);

  const value = useMemo(() => ({ auth, online, signIn, signOut, refreshSession }), [auth, online, signIn, signOut, refreshSession]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
