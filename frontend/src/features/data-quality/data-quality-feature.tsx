"use client";

import Link from "next/link";
import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAppAuth } from "@/components/app-provider";
import { ErrorState, LoadingState, ReconnectState } from "@/components/ui/async-state";
import { Card } from "@/components/ui/card";
import { ResponsiveDataTable, TableColumn } from "@/components/ui/responsive-data-table";
import { ApiRequestError, apiRequest } from "@/lib/api";
import type {
  CollectionPage,
  DataQualitySummary,
  FamilyBizPreview,
  ImportHistoryItem,
  ImportStatistics,
  ReconciliationCase,
} from "./types";
import "./data-quality.css";

type ImportResult = {
  batch_id: string;
  status: string;
  statistics: ImportStatistics;
  issues: Array<{ code: string; message: string; severity: string }>;
};

type Resolution = { resolution: "accept_as_new" | "dismiss" | "link_existing"; transaction_id?: number };
type ResolutionAttempt = { key: string; decision: Resolution; unknown: boolean };
type FeatureError = { message: string; requestId?: string };

function errorDescription(error: unknown, fallback: string): FeatureError {
  if (!(error instanceof ApiRequestError)) return { message: fallback };
  if (error.status === 0 || error.status >= 500) return { message: fallback, requestId: error.apiError?.request_id };
  switch (error.apiError?.code) {
    case "REQUEST_TOO_LARGE": return { message: "הקובץ חורג ממגבלת הגודל המותרת. בחרו קובץ קטן יותר.", requestId: error.apiError.request_id };
    case "INVALID_FAMILYBIZ_WORKBOOK": return { message: "לא ניתן לקרוא את הקובץ כייצוא XLSX תקין של FamilyBiz.", requestId: error.apiError.request_id };
    case "PREVIEW_STALE": return { message: "התצוגה המקדימה כבר אינה תואמת לקובץ או למצב הנתונים. צרו תצוגה חדשה.", requestId: error.apiError.request_id };
    case "RECONCILIATION_CONFLICT": return { message: "תיק ההתאמה נסגר או שהעסקה שנבחרה כבר אינה מועמדת.", requestId: error.apiError.request_id };
    default: return { message: error.apiError?.message || fallback, requestId: error.apiError?.request_id };
  }
}

function formatDate(value: string | null | undefined) {
  if (!value) return "לא זמין";
  return value.slice(0, 10);
}

function money(value: string, currency = "ILS") {
  return `${value} ${currency}`;
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return <Card className="quality-metric"><div className="quality-metric-label">{label}</div><strong className="quality-metric-value">{value}</strong></Card>;
}

function renderStats(stats: ImportStatistics) {
  return `${stats.inserted} נוספו · ${stats.unchanged} ללא שינוי · ${stats.updated} עודכנו · ${stats.unresolved} ממתינים להתאמה`;
}

function downloadDecisionPlan(preview: FamilyBizPreview) {
  const blob = new Blob([preview.decision_plan_json], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${preview.file_sha256}-import-plan.json`;
  anchor.rel = "noopener";
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

export function DataQualityFeature() {
  const { online } = useAppAuth();
  const [quality, setQuality] = useState<DataQualitySummary | null>(null);
  const [history, setHistory] = useState<ImportHistoryItem[]>([]);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [cases, setCases] = useState<ReconciliationCase[]>([]);
  const [casesCursor, setCasesCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshError, setRefreshError] = useState<FeatureError | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<FamilyBizPreview | null>(null);
  const [busy, setBusy] = useState<"preview" | "commit" | string | null>(null);
  const [actionError, setActionError] = useState<FeatureError | null>(null);
  const [notice, setNotice] = useState("");
  const [commitOutcomeUnknown, setCommitOutcomeUnknown] = useState(false);
  const [choices, setChoices] = useState<Record<string, Resolution>>({});
  const [resolutionAttempts, setResolutionAttempts] = useState<Record<string, ResolutionAttempt>>({});
  const fileInput = useRef<HTMLInputElement>(null);

  const loadData = useCallback(async () => {
    if (!online) return;
    setLoading(true);
    setRefreshError(null);
    try {
      const [qualityResponse, historyResponse, casesResponse] = await Promise.all([
        apiRequest<DataQualitySummary>("/dashboard/quality"),
        apiRequest<CollectionPage<ImportHistoryItem>>("/imports/history?limit=50"),
        apiRequest<CollectionPage<ReconciliationCase>>("/reconciliation/cases?limit=50"),
      ]);
      setQuality(qualityResponse.data);
      setHistory(historyResponse.data.items);
      setHistoryCursor(historyResponse.meta?.next_cursor || null);
      setCases(casesResponse.data.items);
      setCasesCursor(casesResponse.meta?.next_cursor || null);
    } catch (error) {
      setRefreshError(errorDescription(error, "לא ניתן לעדכן את נתוני איכות הנתונים והייבוא."));
    } finally {
      setLoading(false);
    }
  }, [online]);

  useEffect(() => {
    if (online) {
      void loadData();
    } else {
      setQuality(null);
      setHistory([]);
      setHistoryCursor(null);
      setCases([]);
      setCasesCursor(null);
      setPreview(null);
      setLoading(false);
    }
  }, [online, loadData]);

  async function loadMore(collection: "history" | "cases") {
    const cursor = collection === "history" ? historyCursor : casesCursor;
    if (!cursor || !online || busy) return;
    setBusy(`more-${collection}`);
    setActionError(null);
    try {
      const query = new URLSearchParams({ limit: "50", cursor });
      if (collection === "history") {
        const response = await apiRequest<CollectionPage<ImportHistoryItem>>(`/imports/history?${query}`);
        setHistory((current) => [...current, ...response.data.items]);
        setHistoryCursor(response.meta?.next_cursor || null);
      } else {
        const response = await apiRequest<CollectionPage<ReconciliationCase>>(`/reconciliation/cases?${query}`);
        setCases((current) => [...current, ...response.data.items]);
        setCasesCursor(response.meta?.next_cursor || null);
      }
    } catch (error) {
      setActionError(errorDescription(error, "לא ניתן לטעון את העמוד הבא."));
    } finally {
      setBusy(null);
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
    setPreview(null);
    setActionError(null);
    setNotice("");
    setCommitOutcomeUnknown(false);
  }

  async function previewFile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || !online || busy) return;
    setBusy("preview");
    setActionError(null);
    setNotice("");
    const form = new FormData();
    form.append("file", file, file.name);
    try {
      const response = await apiRequest<FamilyBizPreview>("/imports/familybiz/previews", { method: "POST", body: form });
      setPreview(response.data);
      setCommitOutcomeUnknown(false);
      setNotice("התצוגה המקדימה הושלמה. לא נוצרו רשומות ייבוא.");
    } catch (error) {
      setPreview(null);
      setActionError(errorDescription(error, "לא ניתן לבדוק את הקובץ. אפשר לבדוק את סוגו וגודלו ולנסות שוב."));
    } finally {
      setBusy(null);
    }
  }

  async function commitImport() {
    if (!file || !preview || !online || busy || commitOutcomeUnknown) return;
    setBusy("commit");
    setActionError(null);
    setNotice("");
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("preview_token", preview.preview_token);
    try {
      const response = await apiRequest<ImportResult>("/imports/familybiz/commits", { method: "POST", body: form });
      setPreview(null);
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      setCommitOutcomeUnknown(false);
      setNotice(`הייבוא ${response.data.status}. מזהה אצווה: ${response.data.batch_id}. ${renderStats(response.data.statistics)}.`);
      await loadData();
    } catch (error) {
      const unknown = error instanceof ApiRequestError && (error.status === 0 || error.status >= 500);
      if (unknown) {
        setPreview(null);
        setCommitOutcomeUnknown(true);
        setActionError({ message: "לא התקבלה תשובת סיום. מצב הייבוא אינו ידוע; רעננו את ההיסטוריה לפני החלטה על פעולה נוספת." });
      } else {
        if (error instanceof ApiRequestError && error.status === 409) setPreview(null);
        setActionError(errorDescription(error, "הייבוא לא אושר. רעננו את ההיסטוריה וצרו תצוגה חדשה לפני שליחה נוספת."));
      }
    } finally {
      setBusy(null);
    }
  }

  function setResolution(caseId: string, decision: Resolution) {
    setChoices((current) => ({ ...current, [caseId]: decision }));
  }

  async function resolveCase(caseItem: ReconciliationCase) {
    if (!online || busy) return;
    const attempt = resolutionAttempts[caseItem.id];
    const decision = attempt?.unknown ? attempt.decision : choices[caseItem.id] ?? { resolution: "accept_as_new" as const };
    const key = attempt?.key ?? crypto.randomUUID();
    setBusy(`resolve-${caseItem.id}`);
    setActionError(null);
    try {
      await apiRequest<ImportResult>(`/reconciliation/cases/${encodeURIComponent(caseItem.id)}/resolution`, {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify(decision),
      });
      setResolutionAttempts((current) => {
        const next = { ...current };
        delete next[caseItem.id];
        return next;
      });
      setNotice("ההתאמה נשמרה.");
      await loadData();
    } catch (error) {
      const unknown = error instanceof ApiRequestError && (error.status === 0 || error.status >= 500);
      if (unknown) {
        setResolutionAttempts((current) => ({ ...current, [caseItem.id]: { key, decision, unknown: true } }));
        setActionError({ message: "לא התקבלה תשובה. אפשר לשלוח שוב את אותה החלטה עם אותו מפתח, או לרענן את הרשימה כדי לבדוק אם התיק נסגר." });
      } else {
        setResolutionAttempts((current) => {
          const next = { ...current };
          delete next[caseItem.id];
          return next;
        });
        setActionError(errorDescription(error, "לא ניתן לשמור את החלטת ההתאמה."));
        if (error instanceof ApiRequestError && error.status === 409) await loadData();
      }
    } finally {
      setBusy(null);
    }
  }

  const historyColumns = useMemo<TableColumn<ImportHistoryItem>[]>(() => [
    { key: "date", label: "מועד", render: (row) => formatDate(row.created_at) },
    { key: "status", label: "מצב", render: (row) => row.status },
    { key: "period", label: "תקופת מקור", render: (row) => `${formatDate(row.report_start)} – ${formatDate(row.report_end)}` },
    { key: "rows", label: "רשומות", render: (row) => row.statistics.total_records, align: "end" },
    { key: "results", label: "תוצאות", render: (row) => renderStats(row.statistics) },
    { key: "issues", label: "קודי בעיה", render: (row) => <bdi>{row.issue_codes.join(" · ") || "—"}</bdi> },
    { key: "batch", label: "מזהה אצווה", render: (row) => <bdi>{row.id}</bdi> },
  ], []);

  const statCards = quality ? [
    { label: "שורות שהתקבלו", value: quality.accepted_rows },
    { label: "עדכון אחרון", value: formatDate(quality.freshness_date) },
    { label: "התאמות פתוחות", value: quality.open_reconciliation_cases },
    { label: "עסקאות לא מסווגות", value: quality.unclassified_transaction_count },
    { label: "חודשים לא שלמים", value: quality.incomplete_months.length },
    { label: "מטבעות", value: Object.keys(quality.currencies).join(", ") || "לא זמין" },
  ] : [];

  if (!online) {
    return <div className="quality-stack">
      <ReconnectState />
      {commitOutcomeUnknown && <div className="quality-notice" role="alert">מצב הייבוא עדיין אינו ידוע. ההיסטוריה והקובץ נשארים זמינים רק בזיכרון עד החיבור מחדש; רעננו היסטוריה וצרו תצוגה מקדימה חדשה לפני כל ניסיון נוסף.</div>}
      {Object.values(resolutionAttempts).some((attempt) => attempt.unknown) && <div className="quality-notice" role="alert">תוצאת החלטת התאמה אינה ידועה. לאחר החיבור, בדקו אם התיק נסגר; אם הוא עדיין פתוח, אפשר לשלוח שוב את אותה החלטה עם אותו מפתח.</div>}
    </div>;
  }

  return <div className="quality-stack">
    {loading && !quality && <LoadingState label="טוענים איכות נתונים, היסטוריית ייבוא והתאמות פתוחות…" />}
    {refreshError && <ErrorState description={refreshError.message} requestId={refreshError.requestId} onRetry={() => void loadData()} retrying={loading} />}
    {quality && <>
      <div className="quality-grid" aria-label="מדדי איכות נתונים">
        {statCards.map((item) => <StatCard key={item.label} label={item.label} value={item.value} />)}
      </div>

      <div className="quality-grid">
        <Card className="quality-detail">
          <h2>כיסוי ומקור הנתונים</h2>
          <dl className="quality-summary">
            <div><dt>תקופה מכוסה</dt><dd>{formatDate(quality.covered_start)} – {formatDate(quality.covered_end)}</dd></div>
            <div><dt>כיסוי מקור</dt><dd>{quality.source_coverage}</dd></div>
            <div><dt>שורות לפי מטבע</dt><dd>{Object.entries(quality.currencies).map(([currency, count]) => `${currency}: ${count}`).join(" · ") || "אין נתונים"}</dd></div>
            <div><dt>סכום לא מסווג</dt><dd>{money(quality.unclassified_absolute_amount)}</dd></div>
          </dl>
          {quality.unclassified_transaction_count > 0 && <p>פריטים לא מסווגים מונעים מדדים מלאים. <Link className="quality-link" href="/classification">מעבר לתור הסיווג</Link></p>}
        </Card>
        <Card className="quality-detail">
          <h2>חודשים לא שלמים</h2>
          {quality.incomplete_months.length ? <ul className="quality-list">{quality.incomplete_months.map((month) => <li key={month}><span>{month.slice(0, 7)}</span><span>דורש בדיקה</span></li>)}</ul> : <p>אין חודשים לא שלמים בטווח שנבדק.</p>}
        </Card>
      </div>

      <Card className="quality-detail">
        <h2>ספירת בעיות</h2>
        {Object.keys(quality.issue_counts).length ? <ul className="quality-list">{Object.entries(quality.issue_counts).sort(([a], [b]) => a.localeCompare(b)).map(([code, count]) => <li key={code}><span><bdi>{code}</bdi></span><strong>{count}</strong></li>)}</ul> : <p>לא דווחו בעיות בנתונים שנבדקו.</p>}
        <h3>ייבוא אחרון</h3>
        {quality.latest_import ? <dl className="quality-summary">
          <div><dt>מצב</dt><dd>{quality.latest_import.status}</dd></div>
          <div><dt>מועד</dt><dd>{formatDate(quality.latest_import.created_at)}</dd></div>
          <div><dt>רשומות</dt><dd>{quality.latest_import.statistics.total_records}</dd></div>
          <div><dt>גרסת מנתח</dt><dd><bdi>{quality.latest_import.parser_version}</bdi></dd></div>
        </dl> : <p>אין ייבוא שהושלם.</p>}
      </Card>
    </>}

    <Card className="quality-detail">
      <h2>העלאת קובץ FamilyBiz</h2>
      <p>בחרו קובץ XLSX. הבדיקה מציגה החלטות חזויות ואינה מוסיפה נתונים. הקובץ, האסימון והתצוגה נשמרים בזיכרון הדף בלבד.</p>
      {notice && <div className="quality-notice" role="status">{notice}</div>}
      {actionError && <div className="quality-error" role="alert">{actionError.message}{actionError.requestId && <div>מזהה פנייה: <bdi>{actionError.requestId}</bdi></div>}</div>}
      {commitOutcomeUnknown && <div className="quality-notice" role="alert">רעננו את היסטוריית הייבוא. אל תשלחו שוב את אותה תצוגה; אחרי בדיקת המצב, צרו תצוגה מקדימה חדשה כדי להחליט אם לפעול.</div>}
      <form onSubmit={(event) => void previewFile(event)}>
        <label className="form-field"><span className="form-label">קובץ XLSX של FamilyBiz <span aria-hidden="true">*</span></span>
          <input ref={fileInput} type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={onFileChange} disabled={Boolean(busy)} aria-label="קובץ XLSX של FamilyBiz" />
          <span className="field-hint">עד 25 MiB דחוסים; נבדקות גם מגבלת התוכן והמבנה.</span>
        </label>
        <div className="quality-actions">
          <button className="quality-button primary" type="submit" disabled={!file || Boolean(busy)}>{busy === "preview" ? "בודקים…" : commitOutcomeUnknown ? "בדיקה ותצוגה חדשה" : "בדיקה ותצוגה מקדימה"}</button>
          <button className="quality-button" type="button" disabled={!online || Boolean(busy)} onClick={() => void loadData()}>עדכון היסטוריה</button>
        </div>
      </form>

      {preview && <div className="quality-preview" aria-label="תוצאת תצוגה מקדימה">
        <div className="quality-grid">
          <StatCard label="רשומות מועמדות" value={preview.candidate_count} />
          <StatCard label="אזהרות" value={preview.warning_count} />
          <StatCard label="רשומות שנדחו" value={preview.rejected_count} />
        </div>
        <dl className="quality-summary">
          <div><dt>טביעת אצבע לתכנית</dt><dd><bdi>{preview.decision_plan_fingerprint}</bdi></dd></div>
          <div><dt>ייבוא בסיס</dt><dd><bdi>{preview.baseline_batch_id || "אין"}</bdi></dd></div>
          <div><dt>גרסת מנתח / התאמה / תכנית</dt><dd><bdi>{preview.parser_version} · {preview.matcher_version} · {preview.decision_plan_version}</bdi></dd></div>
          <div><dt>תקופת המקור</dt><dd>{formatDate(preview.inspection.report_start)} – {formatDate(preview.inspection.report_end)}</dd></div>
        </dl>
        {preview.predicted_statistics && <p>{renderStats(preview.predicted_statistics)}</p>}
        <div className="quality-actions">
          <button className="quality-button" type="button" onClick={() => downloadDecisionPlan(preview)} disabled={Boolean(busy)}>הורדת תכנית החלטות מלאה</button>
          <button className="quality-button primary" type="button" onClick={() => void commitImport()} disabled={Boolean(busy) || commitOutcomeUnknown}>{busy === "commit" ? "שומרים…" : "אישור וייבוא"}</button>
        </div>
        <details><summary>פירוט בדיקה, בסיס התאמה ודוגמאות</summary>
          <p>מטבעות: {Object.entries(preview.inspection.currencies).map(([currency, count]) => `${currency}: ${count}`).join(" · ") || "אין"}</p>
          <p>ספירות בעיות: {Object.entries(preview.issue_counts).map(([code, count]) => `${code}: ${count}`).join(" · ") || "אין"}</p>
          <h3>בסיס התאמה</h3><pre>{preview.matching_baseline_json}</pre>
          <h3>דוגמאות מהקובץ</h3><pre>{JSON.stringify(preview.preview_rows.slice(0, 10), null, 2)}</pre>
        </details>
      </div>}
    </Card>

    <Card className="quality-detail">
      <h2 id="import-history">היסטוריית ייבוא</h2>
      <ResponsiveDataTable caption="היסטוריית ייבוא" rows={history} getRowKey={(row) => row.id} columns={historyColumns} emptyTitle="אין ייבואים להצגה" emptyDescription="היסטוריה תופיע לאחר השלמת ייבוא." />
      {historyCursor && <div className="quality-pagination"><button className="quality-button" type="button" disabled={Boolean(busy)} onClick={() => void loadMore("history")}>{busy === "more-history" ? "טוענים…" : "טעינת ייבואים נוספים"}</button></div>}
    </Card>

    <Card className="quality-detail">
      <h2 id="reconciliation-cases">התאמות פתוחות</h2>
      {!cases.length ? <p>אין תיקי התאמה פתוחים.</p> : <div className="quality-cases">{cases.map((item) => {
        const attempt = resolutionAttempts[item.id];
        const selected = choices[item.id] ?? { resolution: "accept_as_new" as const };
        const lockedDecision = attempt?.unknown ? attempt.decision : null;
        return <section className="quality-case" key={item.id} aria-label={`תיק התאמה ${item.id}`}>
          <h3>תיק <bdi>{item.id}</bdi></h3>
          <p>{item.reason}</p>
          <details><summary>הצגת הרשומה והמועמדות</summary><pre>{JSON.stringify({ source: item.source, candidates: item.candidates }, null, 2)}</pre></details>
          {attempt?.unknown ? <div className="quality-notice" role="status">התוצאה לא ידועה. הניסיון הבא ישלח אותה החלטה עם אותו מפתח.</div> : <>
            <label>החלטה
              <select value={selected.resolution} onChange={(event) => setResolution(item.id, { resolution: event.target.value as Resolution["resolution"] })} disabled={Boolean(busy)}>
                <option value="accept_as_new">קבלת הרשומה כעסקה חדשה</option>
                <option value="dismiss">דחיית הרשומה</option>
                {item.candidates.length > 0 && <option value="link_existing">קישור לעסקה קיימת</option>}
              </select>
            </label>
            {selected.resolution === "link_existing" && item.candidates.length > 0 && <label>עסקה מועמדת
              <select value={selected.transaction_id ?? ""} onChange={(event) => setResolution(item.id, { resolution: "link_existing", transaction_id: Number(event.target.value) })} disabled={Boolean(busy)}>
                <option value="" disabled>בחרו עסקה</option>
                {item.candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.id} · {candidate.booking_date} · {candidate.description} · {money(candidate.amount, candidate.currency)}</option>)}
              </select>
            </label>}
          </>}
          <div className="quality-actions">
            <button className="quality-button primary" type="button" disabled={Boolean(busy) || (!attempt?.unknown && selected.resolution === "link_existing" && !selected.transaction_id)} onClick={() => void resolveCase(item)}>{busy === `resolve-${item.id}` ? "שומרים…" : attempt?.unknown ? "שליחה חוזרת של אותה החלטה" : "שמירת החלטה"}</button>
            {lockedDecision && <span className="field-hint">{lockedDecision.resolution === "link_existing" ? `קישור לעסקה ${lockedDecision.transaction_id}` : lockedDecision.resolution === "dismiss" ? "דחייה" : "קבלה כחדשה"}</span>}
          </div>
        </section>;
      })}</div>}
      {casesCursor && <div className="quality-pagination"><button className="quality-button" type="button" disabled={Boolean(busy)} onClick={() => void loadMore("cases")}>{busy === "more-cases" ? "טוענים…" : "טעינת התאמות נוספות"}</button></div>}
    </Card>
  </div>;
}
