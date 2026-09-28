"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiRequestError } from "@/lib/api";
import { getSessions, getSettings, revokeSession, saveAppPreferences, type SettingsOverview, type UserSession } from "./api";
import "./settings.css";

function dateLabel(value: string | null) {
  if (!value) return "אין עדיין נתונים";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString("he-IL");
}

function warningLabel(code: string) {
  const labels: Record<string, string> = {
    AUTOMATION_BACKUP_NOT_CONFIGURED: "לא הוגדר יעד לגיבוי לפני ריצת אוטומציה.",
    LATEST_BACKUP_VERIFICATION_FAILED: "אימות הגיבוי האחרון נכשל.",
    AUTOMATION_BACKUP_DESTINATION_UNAVAILABLE: "יעד הגיבוי אינו זמין.",
    FAMILYBIZ_DATA_STALE: "ייבוא הנתונים האחרון מ־FamilyBiz ישן מ־31 יום.",
  };
  return labels[code] ?? code.replaceAll("_", " ").toLowerCase();
}

function backupLabel(value: string) {
  const labels: Record<string, string> = {
    not_configured: "לא הוגדר", not_created: "ייווצר בריצה הראשונה",
    no_verified_backup: "אין עדיין גיבוי מאומת", verified: "הגיבוי האחרון אומת",
    verification_failed: "אימות הגיבוי האחרון נכשל", unavailable: "לא זמין",
  };
  return labels[value] ?? value;
}

export function SettingsFeature() {
  const [settings, setSettings] = useState<SettingsOverview>();
  const [sessions, setSessions] = useState<UserSession[]>([]);
  const [currency, setCurrency] = useState("ILS");
  const [months, setMonths] = useState(12);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    setError("");
    try {
      const [overview, sessionList] = await Promise.all([getSettings(), getSessions()]);
      setSettings(overview.data);
      setCurrency(overview.data.preferences.default_currency);
      setMonths(overview.data.preferences.default_months);
      setSessions(sessionList.data.items);
    } catch (reason) {
      setError(reason instanceof ApiRequestError ? reason.message : "לא ניתן לטעון את ההגדרות.");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      await saveAppPreferences({ default_currency: currency, default_months: months });
      setMessage("העדפות התצוגה נשמרו לחשבון שלך.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof ApiRequestError ? reason.message : "לא ניתן לשמור את ההעדפות.");
    } finally { setBusy(false); }
  }

  async function revoke(session: UserSession) {
    setBusy(true); setError(""); setMessage("");
    try {
      await revokeSession(session.id);
      setMessage("החיבור הנבחר בוטל.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof ApiRequestError ? reason.message : "לא ניתן לבטל את החיבור.");
    } finally { setBusy(false); }
  }

  return <div className="settings-feature">
    {error && <p className="settings-error" role="alert">{error}</p>}
    {message && <p className="settings-success" role="status">{message}</p>}
    {!settings ? <section className="surface settings-panel"><p role="status">טוענים הגדרות מהשרת…</p></section> : <>
      <section className="surface settings-panel" aria-labelledby="settings-preferences-heading">
        <div className="settings-heading"><div><h2 id="settings-preferences-heading">העדפות תצוגה</h2><p>העדפות אלה נשמרות לכל חשבון בנפרד.</p></div></div>
        <form className="settings-form" onSubmit={save}>
          <label>מטבע ברירת מחדל
            <select value={currency} onChange={(event) => setCurrency(event.target.value)}>
              <option value="ILS">שקל ישראלי · ILS</option><option value="USD">דולר אמריקאי · USD</option>
              <option value="EUR">אירו · EUR</option><option value="GBP">לירה שטרלינג · GBP</option>
            </select>
          </label>
          <label>תקופת ברירת מחדל
            <select value={months} onChange={(event) => setMonths(Number(event.target.value))}>
              <option value={6}>6 חודשים</option><option value={12}>12 חודשים</option>
              <option value={24}>24 חודשים</option><option value={36}>36 חודשים</option>
            </select>
          </label>
          <div className="settings-actions"><Button type="submit" disabled={busy}>{busy ? "שומרים…" : "שמירת העדפות"}</Button></div>
        </form>
      </section>

      <section className="surface settings-panel" aria-labelledby="settings-freshness-heading">
        <div className="settings-heading"><div><h2 id="settings-freshness-heading">עדכניות נתונים</h2><p>מועדי הייבוא האחרונים, ללא הצגת שמות קבצים או נתיבי אחסון.</p></div></div>
        <div className="settings-freshness-grid">
          <article><strong>FamilyBiz</strong><span>ייבוא: {dateLabel(settings.freshness.familybiz.last_import_at)}</span><span>תאריך עסקה אחרון: {dateLabel(settings.freshness.familybiz.latest_transaction_date)}</span>{settings.freshness.familybiz.age_days !== null && <span>לפני {settings.freshness.familybiz.age_days} ימים</span>}</article>
          <article><strong>תכנון</strong><span>ייבוא: {dateLabel(settings.freshness.planning.last_import_at)}</span>{settings.freshness.planning.age_days !== null && <span>לפני {settings.freshness.planning.age_days} ימים</span>}</article>
          <article><strong>הון משפחתי</strong><span>ייבוא: {dateLabel(settings.freshness.net_worth.last_import_at)}</span>{settings.freshness.net_worth.age_days !== null && <span>לפני {settings.freshness.net_worth.age_days} ימים</span>}</article>
        </div>
      </section>

      <section className="surface settings-panel" aria-labelledby="settings-operations-heading">
        <div className="settings-heading"><div><h2 id="settings-operations-heading">בריאות המערכת</h2><p>מצב ביקורת, ארכיונים וגיבויים. פרטי מערכת הקבצים נשארים בשרת.</p></div></div>
        <div className="settings-health-row"><span>ביקורת נתונים</span><strong>{settings.operations.audit.passed ? "תקינה" : "נדרשת בדיקה"}</strong></div>
        <div className="settings-health-row"><span>גיבוי וארכיון</span><strong>{backupLabel(settings.operations.backup.status)}</strong></div>
        {settings.operations.backup.last_verified_at && <div className="settings-health-row"><span>אימות אחרון</span><strong>{settings.operations.backup.last_verified_at} UTC</strong></div>}
        {settings.operational_warnings.length > 0 ? <div className="settings-warning"><strong>אזהרות תפעוליות</strong><ul>{settings.operational_warnings.map((item) => <li key={item}>{warningLabel(item)}</li>)}</ul></div> : <p className="settings-healthy">לא נמצאו אזהרות תפעוליות.</p>}
      </section>

      <section className="surface settings-panel" aria-labelledby="settings-household-heading">
        <div className="settings-heading"><div><h2 id="settings-household-heading">חשבונות וחיבורים</h2><p>{settings.household.member_count} חשבונות ביתיים עם הרשאות שוות. כל חשבון מנהל את החיבורים שלו.</p></div></div>
        <ul className="settings-member-list">{settings.household.members.map((member) => <li key={member}>{member}</li>)}</ul>
        <h3 className="settings-sessions-title">החיבורים הפעילים שלך</h3>
        {sessions.length ? <ul className="settings-session-list">{sessions.map((session) => <li key={session.id}>
          <div><strong>{session.current ? "המכשיר הנוכחי" : "חיבור פעיל"}</strong><span>נוצר: {dateLabel(session.created_at)}</span><span>בתוקף עד: {dateLabel(session.expires_at)}</span></div>
          {!session.current && <Button variant="outline" size="sm" disabled={busy} onClick={() => void revoke(session)}>ביטול חיבור</Button>}
        </li>)}</ul> : <p className="settings-muted">לא נמצאו חיבורים פעילים.</p>}
      </section>
    </>}
  </div>;
}
