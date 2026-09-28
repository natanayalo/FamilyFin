"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiRequestError } from "@/lib/api";
import {
  commitAttentionFile, getAttentionFiles, getAutomationRuns, getAutomationStatus,
  preflightAttentionFile, startAutomation, type AttentionFile, type AttentionPreflight,
  type AutomationRun, type AutomationStatus,
} from "./api";
import { InsightPreferencesFeature } from "@/features/insight-preferences/insight-preferences-feature";
import "./operations.css";

function timeLabel(value: string | null | undefined) {
  if (!value) return "אין עדיין ריצה";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("he-IL");
}

function runLabel(value: string) {
  const labels: Record<string, string> = {
    completed: "הושלמה", completed_with_warnings: "הושלמה עם אזהרות", dry_run: "בדיקה ללא שינויים",
    blocked_audit: "נחסמה בביקורת", blocked_backup: "נחסמה בגיבוי", failed_audit: "הביקורת לאחר הייבוא נכשלה",
    busy: "תהליך אחר פעיל", failed: "נכשלה", running: "פועלת",
  };
  return labels[value] ?? value;
}

function backupLabel(value: string) {
  const labels: Record<string, string> = {
    not_configured: "לא הוגדר יעד גיבוי", not_created: "היעד ייווצר בריצה הראשונה",
    no_verified_backup: "עדיין אין גיבוי מאומת", verified: "הגיבוי האחרון אומת",
    verification_failed: "אימות הגיבוי האחרון נכשל", unavailable: "יעד הגיבוי אינו זמין",
  };
  return labels[value] ?? value;
}

function issueLabel(value: string) {
  const labels: Record<string, string> = {
    AUTOMATION_BACKUP_NOT_CONFIGURED: "לא הוגדר יעד לגיבוי לפני ייבוא",
    AUTOMATION_BACKUP_DESTINATION_UNAVAILABLE: "יעד הגיבוי אינו זמין",
    SQLITE_INTEGRITY_ERROR: "בדיקת תקינות SQLite נכשלה",
    ARCHIVE_MISSING: "ארכיון מקור חסר",
    ARCHIVE_HASH_MISMATCH: "חתימת ארכיון מקור אינה תואמת",
    FAMILYBIZ_DATA_STALE: "ייבוא FamilyBiz האחרון ישן מ־31 יום",
  };
  return labels[value] ?? value.replaceAll("_", " ").toLowerCase();
}

function RunRow({ run }: { run: AutomationRun }) {
  const total = Object.values(run.counts).reduce((sum, count) => sum + count, 0);
  return <li className="operations-run-row">
    <div><strong>{runLabel(run.status)}</strong><span>{timeLabel(run.started_at)}{run.dry_run ? " · ללא שינויים" : ""}</span></div>
    <span>{total} קבצים</span>
    {run.issue_codes.length > 0 && <span className="operations-issue-list">{run.issue_codes.map(issueLabel).join(" · ")}</span>}
  </li>;
}

function AttentionReview({ ready }: { ready: boolean }) {
  const [files, setFiles] = useState<AttentionFile[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [preview, setPreview] = useState<AttentionPreflight | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    try {
      const response = await getAttentionFiles();
      setFiles(response.data.items);
    } catch (reason) {
      setError(reason instanceof ApiRequestError ? reason.message : "לא ניתן לטעון קבצים לבדיקה.");
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const inspect = async (fileId: string) => {
    setBusy(true);
    setSelected(fileId);
    setPreview(null);
    setConfirmed(false);
    setMessage("");
    setError("");
    try {
      const response = await preflightAttentionFile(fileId);
      setPreview(response.data);
    } catch (reason) {
      setError(reason instanceof ApiRequestError ? reason.message : "בדיקת הקובץ נכשלה.");
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    if (!selected || !preview || !confirmed || !ready) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const response = await commitAttentionFile(selected, preview.file_sha256);
      setMessage(`הטיפול בקובץ הושלם. מצב הייבוא: ${response.data.status}. בדקו מקרי התאמה פתוחים לפני אישורם.`);
      setPreview(null);
      setSelected(null);
      setConfirmed(false);
      await refresh();
    } catch (reason) {
      setPreview(null);
      setConfirmed(false);
      const detail = reason instanceof ApiRequestError ? `${reason.message} ` : "";
      setError(`${detail}רעננו את הרשימה ובדקו את ההיסטוריה לפני ניסיון נוסף; ייתכן שהאישור הושלם.`);
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  return <section className="surface operations-panel" aria-labelledby="attention-heading">
    <div className="operations-heading"><div><h2 id="attention-heading">קבצים לבדיקה</h2><p>בדיקה מוקדמת אינה משנה נתונים. אישור מפעיל את שירות Python לאחר ביקורת וגיבוי מאומת חדש.</p></div><Button variant="outline" disabled={busy} onClick={() => void refresh()}>רענון קבצים</Button></div>
    {files.length === 0 ? <p className="operations-muted">אין קבצים שממתינים לבדיקה.</p> : <ul className="operations-attention-list">{files.map((file, index) => <li key={file.id}>
      <div><strong>קובץ לבדיקה {index + 1}</strong><span>{Math.ceil(file.size_bytes / 1024)} KB · {timeLabel(file.modified_at)}</span></div>
      <Button variant="outline" disabled={busy} onClick={() => void inspect(file.id)}>בדיקה מוקדמת</Button>
    </li>)}</ul>}
    {preview && selected && <div className="operations-attention-preview">
      <h3>תוצאות בדיקה מוקדמת</h3>
      <p>רשומות מועמדות: {preview.candidate_count} · התאמות לבדיקה: {preview.reconciliation_count} · אזהרות: {preview.warning_count} · נדחו: {preview.rejected_count}</p>
      <p>{preview.duplicate_file ? "הקובץ כבר יובא. אישור יתעד כפילות ללא ייבוא חוזר." : "אישור ישמור את הקובץ ויפתח מקרי התאמה לבדיקה."}</p>
      {preview.predicted_statistics && <p>חדשות: {preview.predicted_statistics.inserted} · עדכונים: {preview.predicted_statistics.updated} · ללא שינוי: {preview.predicted_statistics.unchanged}</p>}
      {Object.keys(preview.issue_counts).length > 0 && <p>סוגי בעיות: {Object.entries(preview.issue_counts).map(([code, count]) => `${issueLabel(code)} (${count})`).join(" · ")}</p>}
      <label><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /> אני מאשר/ת את תוצאות הבדיקה ואת יצירת הגיבוי לפני הייבוא.</label>
      <Button disabled={busy || !ready || !confirmed || !["needs_review", "duplicate"].includes(preview.action)} onClick={() => void commit()}>אישור קובץ לבדיקה</Button>
      {!ready && <p className="operations-note">האישור חסום עד שהביקורת ויעד הגיבוי יהיו מוכנים.</p>}
    </div>}
    {error && <p className="operations-error" role="alert">{error}</p>}
    {message && <p className="operations-success" role="status">{message}</p>}
  </section>;
}

export function OperationsFeature() {
  const [status, setStatus] = useState<AutomationStatus>();
  const [runs, setRuns] = useState<AutomationRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    setError("");
    try {
      const [statusResponse, runsResponse] = await Promise.all([getAutomationStatus(), getAutomationRuns()]);
      setStatus(statusResponse.data);
      setRuns(runsResponse.data.items);
    } catch (reason) {
      setError(reason instanceof ApiRequestError ? reason.message : "לא ניתן לטעון את מצב התהליכים.");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const run = async (dryRun: boolean) => {
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const response = await startAutomation(dryRun);
      const result = response.data;
      setMessage(dryRun
        ? `הבדיקה הסתיימה: ${Object.values(result.counts).reduce((sum, count) => sum + count, 0)} קבצים נבדקו. לא נשמרו נתונים ולא הועברו קבצים.`
        : `הריצה ${runLabel(result.status)}${result.backup_created ? " לאחר יצירת גיבוי מאומת" : ""}.`);
      await refresh();
    } catch (reason) {
      setError(reason instanceof ApiRequestError ? reason.message : "הריצה לא הושלמה.");
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  return <div className="operations-feature">
    <section className="surface operations-panel" aria-labelledby="operations-status-heading">
      <div className="operations-heading"><div><h2 id="operations-status-heading">מצב תהליכים</h2><p>הצגת מצב ותוצאות; הפעלה מתבצעת בשירות Python בלבד.</p></div><Button variant="outline" onClick={() => void refresh()} disabled={busy}>רענון</Button></div>
      {error && <p className="operations-error" role="alert">{error}</p>}
      {!status ? <p className="operations-muted" role="status">טוענים נתונים מהשרת…</p> : <>
        <div className="operations-metrics">
          <article><span>קבצים בתיבת הקלט</span><strong>{status.inbox.inbox_file_count}</strong></article>
          <article><span>קבצים לבדיקה</span><strong>{status.inbox.review_file_count}</strong></article>
          <article><span>ביקורת נתונים</span><strong>{status.operations.audit.passed ? "תקינה" : "נדרשת בדיקה"}</strong></article>
        </div>
        <div className="operations-health">
          <p><strong>יעד גיבוי:</strong> {backupLabel(status.operations.backup.status)}</p>
          {status.operations.backup.last_verified_at && <p><strong>אימות אחרון:</strong> {status.operations.backup.last_verified_at} UTC</p>}
          <p><strong>הריצה האחרונה:</strong> {status.latest_run ? `${runLabel(status.latest_run.status)} · ${timeLabel(status.latest_run.started_at)}` : "אין עדיין ריצות"}</p>
        </div>
        {status.operations.warnings.length > 0 && <div className="operations-warning" role="status"><strong>נדרשת תשומת לב</strong><ul>{status.operations.warnings.map((warning) => <li key={warning}>{issueLabel(warning)}</li>)}</ul></div>}
        <div className="operations-actions">
          <Button variant="outline" disabled={busy} onClick={() => void run(true)}>{busy ? "פועלת…" : "בדיקת תיבה ללא שינויים"}</Button>
          <Button disabled={busy || !status.operations.run_now_allowed} onClick={() => void run(false)} aria-describedby="run-now-note">הפעלה עכשיו</Button>
        </div>
        <p className="operations-note" id="run-now-note">
          {status.operations.run_now_allowed
            ? "הפעלה יוצרת ומאמתת גיבוי לכל ריצה שיש בה קבצים, לפני ייבוא או העברת קובץ."
            : status.operations.run_now_block_reason === "AUDIT_FAILED"
              ? "ההפעלה חסומה עד שכל בדיקות הביקורת יעברו."
              : status.operations.run_now_block_reason === "AUTOMATION_BACKUP_NOT_CONFIGURED"
                ? "ההפעלה חסומה עד להגדרת יעד גיבוי. הריצה תיעצר גם אם יצירת הגיבוי תיכשל."
                : "ההפעלה חסומה כי יעד הגיבוי אינו זמין. בדקו את תצורת השרת."}
        </p>
        {message && <p className="operations-success" role="status">{message}</p>}
        <details className="operations-audit"><summary>תוצאות ביקורת ותקינות ארכיון</summary>
          <ul>{status.operations.audit.checks.map((check) => <li key={check.name}><span>{check.name.replaceAll("_", " ")}</span><strong>{check.passed ? "תקין" : check.issue_codes.map(issueLabel).join(" · ")}</strong></li>)}</ul>
        </details>
      </>}
    </section>

    <AttentionReview ready={Boolean(status?.operations.run_now_allowed)} />

    <section className="surface operations-panel" aria-labelledby="automation-history-heading">
      <div className="operations-heading"><div><h2 id="automation-history-heading">היסטוריית ריצות</h2><p>היסטוריה מציגה סטטוסים, ספירות וקודי בעיה בלבד.</p></div></div>
      {runs.length ? <ul className="operations-run-list">{runs.map((item) => <RunRow key={item.id} run={item} />)}</ul> : <p className="operations-muted">אין ריצות שמורות.</p>}
    </section>

    <InsightPreferencesFeature />
  </div>;
}
