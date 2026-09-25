"use client";

import { FormEvent, useState } from "react";
import { ApiRequestError } from "@/lib/api";
import { useAppAuth } from "@/components/app-provider";
import { TextField } from "@/components/ui/form-patterns";

export function SignIn() {
  const { signIn, online, auth } = useAppAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await signIn(username.trim(), password);
      setPassword("");
    } catch (issue) {
      const status = issue instanceof ApiRequestError ? issue.status : -1;
      setError(status === 401 || status === 403 ? "פרטי ההתחברות אינם תקינים." :
        status === 0 ? "אין חיבור לשירות. בדקו את הרשת ונסו שוב." :
        issue instanceof Error ? issue.message : "ההתחברות לא הושלמה.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="sign-in-page">
      <section className="signin-aside" aria-label="FamilyFin">
        <div className="brand"><span className="brand-mark" aria-hidden="true">⌂</span><div><div className="brand-title">FamilyFin</div><div className="brand-subtitle">ניהול פיננסי משפחתי</div></div></div>
        <div className="signin-message"><div className="eyebrow">מרחב משפחתי פרטי</div><h1>תמונה ברורה יותר של הכסף בבית.</h1><p>התחברו לחשבון האישי שלכם כדי להמשיך. נתוני המשפחה זמינים רק לאחר התחברות ובחיבור פעיל.</p></div>
        <div className="signin-foot">גישה פרטית · התחברות מאובטחת</div>
      </section>
      <section className="signin-form-wrap">
        <form className="signin-form" onSubmit={submit}>
          <div className="eyebrow">ברוכים הבאים</div><h2>התחברות ל‑FamilyFin</h2><p>הזינו את פרטי החשבון שלכם.</p>
          {(error || (auth.status === "signed-out" && auth.error)) && <div className="form-error" role="alert">{error || (auth.status === "signed-out" ? auth.error : "")}</div>}
          {!online && <div className="form-error" role="status">אין חיבור לאינטרנט. התחברות מחייבת חיבור פעיל.</div>}
          <TextField id="username" label="שם משתמש" autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)} />
          <TextField id="password" label="סיסמה" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
          <button className="primary-button" type="submit" disabled={busy || !online}>{busy ? "מתחברים…" : "התחברות"}</button>
        </form>
      </section>
    </main>
  );
}
