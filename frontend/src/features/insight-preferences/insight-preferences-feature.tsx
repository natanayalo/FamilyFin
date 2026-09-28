"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiRequestError } from "@/lib/api";
import {
  getInsightAlerts,
  getInsightPreferenceOptions,
  getInsightPreferences,
  getMonthlySummaries,
  saveInsightPreferences,
  transitionInsightAlert,
  type InsightAlert,
  type InsightPreferenceOptions,
  type InsightPreferences,
  type MonthlySummary,
} from "./api";

const emptyPreferences: InsightPreferences = {
  planning_scenario_id: null, planning_revision_id: null, forecast_id: null,
  forecast_revision_id: null, forecast_role: null, apartment_study_id: null,
  apartment_revision_id: null, apartment_alternative_name: null, updated_at: null,
};

function alertTypeLabel(value: string) {
  const labels: Record<string, string> = {
    stale_import: "ייבוא ישן", incomplete_month: "חודש חלקי", unclassified_rows: "עסקאות ללא סיווג",
    income_drop: "ירידה בהכנסה", operating_deficit: "גירעון תפעולי",
    primary_plan_category_variance: "חריגה מתכנון", preference_missing_alternative: "חלופת דירה חסרה",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

const selectClass = "insight-select";

export function InsightPreferencesFeature() {
  const [preferences, setPreferences] = useState<InsightPreferences>(emptyPreferences);
  const [options, setOptions] = useState<InsightPreferenceOptions>();
  const [alerts, setAlerts] = useState<InsightAlert[]>([]);
  const [summaries, setSummaries] = useState<MonthlySummary[]>([]);
  const [filter, setFilter] = useState<"all" | InsightAlert["state"]>("all");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const loadAll = useCallback(async () => {
    setError("");
    try {
      const [prefs, choices, alertList, summaryList] = await Promise.all([
        getInsightPreferences(), getInsightPreferenceOptions(),
        getInsightAlerts(filter === "all" ? undefined : filter), getMonthlySummaries(),
      ]);
      setPreferences(prefs.data);
      setOptions(choices.data);
      setAlerts(alertList.data.items);
      setSummaries(summaryList.data.items);
    } catch (reason) {
      setError(reason instanceof ApiRequestError ? reason.message : "לא ניתן לטעון את התובנות.");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { void loadAll(); }, [loadAll]);

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await saveInsightPreferences({
        planning_scenario_id: preferences.planning_scenario_id || null,
        planning_revision_id: null,
        forecast_id: preferences.forecast_id || null,
        forecast_revision_id: null,
        forecast_role: preferences.forecast_id ? preferences.forecast_role || "baseline" : null,
        apartment_study_id: preferences.apartment_study_id || null,
        apartment_revision_id: null,
        apartment_alternative_name: preferences.apartment_study_id ? preferences.apartment_alternative_name : null,
      });
      setPreferences(response.data);
      setMessage("העדפות התובנות נשמרו.");
    } catch (reason) {
      setError(reason instanceof ApiRequestError ? reason.message : "לא ניתן לשמור את ההעדפות.");
    } finally { setBusy(false); }
  }

  async function review(alert: InsightAlert, action: "acknowledge" | "resolve") {
    setBusy(true); setError(""); setMessage("");
    try {
      await transitionInsightAlert(alert.id, action);
      setMessage(action === "acknowledge" ? "התובנה סומנה לבדיקה." : "התובנה סומנה כטופלה.");
      await loadAll();
    } catch (reason) {
      setError(reason instanceof ApiRequestError ? reason.message : "לא ניתן לעדכן את התובנה.");
    } finally { setBusy(false); }
  }

  return <section className="surface operations-panel operations-insights" aria-labelledby="insights-heading">
    <div className="operations-heading"><div><h2 id="insights-heading">תובנות והעדפות</h2><p>התובנות נשמרות כתוצאות שרת וניתנות לאישור או לסגירה.</p></div><Button variant="outline" onClick={() => void loadAll()} disabled={busy}>רענון</Button></div>
    {error && <p className="operations-error" role="alert">{error}</p>}
    {message && <p className="operations-success" role="status">{message}</p>}
    {loading ? <p className="operations-muted" role="status">טוענים העדפות ותוצאות…</p> : <>
      <form className="insight-preferences-form" onSubmit={save}>
        <h3>בחירת מקורות לתובנות</h3>
        <p className="operations-muted">הבחירות נשמרות כהעדפות משותפות למשק הבית, לפי הגרסה העדכנית בעת השמירה.</p>
        <label>תרחיש תכנון ראשי
          <select className={selectClass} value={preferences.planning_scenario_id ?? ""} onChange={(event) => setPreferences({ ...preferences, planning_scenario_id: event.target.value || null })}>
            <option value="">ללא תרחיש</option>{options?.planning_scenarios.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.currency} · גרסה {item.revision_number}</option>)}
          </select>
        </label>
        <label>תחזית חיסכון
          <select className={selectClass} value={preferences.forecast_id ?? ""} onChange={(event) => setPreferences({ ...preferences, forecast_id: event.target.value || null })}>
            <option value="">ללא תחזית</option>{options?.forecasts.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.currency} · גרסה {item.revision_number}</option>)}
          </select>
        </label>
        {preferences.forecast_id && <label>תפקיד התחזית
          <select className={selectClass} value={preferences.forecast_role ?? "baseline"} onChange={(event) => setPreferences({ ...preferences, forecast_role: event.target.value })}>
            <option value="baseline">בסיס</option><option value="conservative">שמרני</option><option value="optimistic">אופטימי</option>
          </select>
        </label>}
        <label>תכנון רכישת דירה
          <select className={selectClass} value={preferences.apartment_study_id ?? ""} onChange={(event) => setPreferences({ ...preferences, apartment_study_id: event.target.value || null, apartment_alternative_name: null })}>
            <option value="">ללא תכנון</option>{options?.apartment_studies.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.currency} · גרסה {item.revision_number}</option>)}
          </select>
        </label>
        {preferences.apartment_study_id && <label>שם החלופה המועדפת
          <input className={selectClass} maxLength={100} value={preferences.apartment_alternative_name ?? ""} onChange={(event) => setPreferences({ ...preferences, apartment_alternative_name: event.target.value })} />
        </label>}
        <div className="form-actions"><Button type="submit" disabled={busy}>{busy ? "שומרים…" : "שמירת העדפות"}</Button></div>
      </form>

      <div className="insights-review-block">
        <div className="insights-subheading"><h3>התראות</h3><label>מצב
          <select className={selectClass} value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)}>
            <option value="all">הכול</option><option value="open">פתוחות</option><option value="acknowledged">בבדיקה</option><option value="resolved">טופלו</option>
          </select>
        </label></div>
        {alerts.length ? <ul className="insight-alert-list">{alerts.map((alert) => <li key={alert.id}>
          <div className="insight-alert-copy"><strong>{alertTypeLabel(alert.condition_type)}</strong><span>{alert.subject_identity} · {alert.evidence_period} · {alert.occurrence_count} פעמים</span><span>מצב: {alert.state === "open" ? "פתוחה" : alert.state === "acknowledged" ? "בבדיקה" : "טופלה"}</span>
            <details><summary>ראיות</summary><pre>{JSON.stringify(alert.evidence, null, 2)}</pre></details>
          </div>
          <div className="insight-alert-actions">{alert.state === "open" && <Button variant="outline" size="sm" disabled={busy} onClick={() => void review(alert, "acknowledge")}>סימון לבדיקה</Button>}{alert.state !== "resolved" && <Button variant="secondary" size="sm" disabled={busy} onClick={() => void review(alert, "resolve")}>סימון כטופל</Button>}</div>
        </li>)}</ul> : <p className="operations-muted">אין תובנות במצב שנבחר.</p>}
      </div>

      <div className="insights-review-block">
        <h3>סיכומים חודשיים שמורים</h3>
        {summaries.length ? <div className="insight-summary-list">{summaries.map((summary: MonthlySummary) => <details key={summary.id}>
          <summary>{summary.month.slice(0, 7)} · {summary.currency} · גרסה {summary.revision_number}</summary>
          <pre>{summary.markdown}</pre>
        </details>)}</div> : <p className="operations-muted">עדיין לא נשמרו סיכומים חודשיים.</p>}
      </div>
    </>}
  </section>;
}
