"use client";

import { useState } from "react";
import { useAppAuth } from "@/components/app-provider";

export function LoadingState({ label = "טוענים מידע…" }: { label?: string }) {
  return <div className="async-state loading-state" role="status" aria-live="polite" aria-busy="true"><span className="spinner" aria-hidden="true" />{label}</div>;
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: React.ReactNode }) {
  return <section className="async-state empty-state"><span className="empty-state-mark" aria-hidden="true">○</span><h2>{title}</h2>{description && <p>{description}</p>}{action && <div className="async-state-action">{action}</div>}</section>;
}

export function ErrorState({ title = "לא ניתן לטעון את המידע", description, requestId, onRetry, retrying = false }: {
  title?: string;
  description?: string;
  requestId?: string;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  return <section className="async-state error-state" role="alert"><span className="error-state-mark" aria-hidden="true">!</span><h2>{title}</h2>{description && <p>{description}</p>}{requestId && <p className="request-id">מזהה פנייה: <bdi>{requestId}</bdi></p>}{onRetry && <button className="secondary-button" type="button" onClick={onRetry} disabled={retrying}>{retrying ? "בודקים…" : "לנסות שוב"}</button>}</section>;
}

export function ReconnectState() {
  const { refreshSession } = useAppAuth();
  const [retrying, setRetrying] = useState(false);
  async function retry() {
    if (retrying) return;
    setRetrying(true);
    try { await refreshSession(); } finally { setRetrying(false); }
  }
  return <ErrorState title="נדרש חיבור מאומת מחדש" description="החיבור לשירות אינו זמין. נתונים פיננסיים נשארים מוסתרים עד שהשירות יאשר את ההתחברות." onRetry={() => void retry()} retrying={retrying} />;
}
