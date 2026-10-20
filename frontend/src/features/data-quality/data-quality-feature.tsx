"use client";

import Link from "next/link";
import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAppAuth } from "@/components/app-provider";
import { ErrorState, LoadingState, ReconnectState } from "@/components/ui/async-state";
import { Card } from "@/components/ui/card";
import { ResponsiveDataTable, TableColumn } from "@/components/ui/responsive-data-table";
import { formatAmount as money, currencyLabel, importStatusLabel, issueLabel, formatHebrewMonth } from "@/lib/display";
import { coverageLabel, formatDate } from "@/features/dashboard/format";
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

function StatCard({ label, value }: { label: string; value: string | number }) {
  return <Card className="quality-metric"><div className="quality-metric-label">{label}</div><strong className="quality-metric-value">{value}</strong></Card>;
}

function renderStats(stats: ImportStatistics) {
  return `חדשות: ${stats.inserted} · ללא שינוי: ${stats.unchanged} · עודכנו: ${stats.updated} · ממתינות להתאמה: ${stats.unresolved}`;
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
  const [history, setHistory] = useState<ImportHistoryItem[] | null>(null);
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
  const [actionArea, setActionArea] = useState<"import" | "cases" | "history">("import");
  const [commitOutcomeUnknown, setCommitOutcomeUnknown] = useState(false);
  const [choices, setChoices] = useState<Record<string, Resolution>>({});
  const [resolutionAttempts, setResolutionAttempts] = useState<Record<string, ResolutionAttempt>>({});
  const fileInput = useRef<HTMLInputElement>(null);
  const loadVersion = useRef(0);

  const loadData = useCallback(async () => {
    if (!online) return;
    const version = ++loadVersion.current;
    setLoading(true);
    setRefreshError(null);
    try {
      const [qualityResponse, historyResponse, casesResponse] = await Promise.all([
        apiRequest<DataQualitySummary>("/dashboard/quality"),
        apiRequest<CollectionPage<ImportHistoryItem>>("/imports/history?limit=50"),
        apiRequest<CollectionPage<ReconciliationCase>>("/reconciliation/cases?limit=50"),
      ]);
      if (version !== loadVersion.current) return;
      setQuality(qualityResponse.data);
      setHistory(historyResponse.data.items);
      setHistoryCursor(historyResponse.meta?.next_cursor || null);
      setCases(casesResponse.data.items);
      setCasesCursor(casesResponse.meta?.next_cursor || null);
    } catch (error) {
      if (version === loadVersion.current) setRefreshError(errorDescription(error, "לא ניתן לעדכן את נתוני איכות הנתונים והייבוא."));
    } finally {
      if (version === loadVersion.current) setLoading(false);
    }
  }, [online]);

  useEffect(() => {
    if (online) {
      void loadData();
    } else {
      setQuality(null);
      setHistory(null);
      setHistoryCursor(null);
      setCases([]);
      setCasesCursor(null);
      setPreview(null);
      setLoading(false);
    }
    return () => { loadVersion.current += 1; };
  }, [online, loadData]);

  async function loadMore(collection: "history" | "cases") {
    const cursor = collection === "history" ? historyCursor : casesCursor;
    if (!cursor || !online || busy) return;
    setActionArea(collection);
    setNotice("");
    setBusy(`more-${collection}`);
    setActionError(null);
    try {
      const query = new URLSearchParams({ limit: "50", cursor });
      if (collection === "history") {
        const response = await apiRequest<CollectionPage<ImportHistoryItem>>(`/imports/history?${query}`);
        setHistory((current) => [...(current ?? []), ...response.data.items]);
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
    setActionArea("import");
    setFile(event.target.files?.[0] ?? null);
    setPreview(null);
    setActionError(null);
    setNotice("");
    setCommitOutcomeUnknown(false);
  }

  async function previewFile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || !online || busy) return;
    setActionArea("import");
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
    setActionArea("import");
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
      setNotice(response.data.statistics.duplicate_file ? "הקובץ כבר יובא. לא נוספו עסקאות כפולות." : `הייבוא ${importStatusLabel(response.data.status)}. ${renderStats(response.data.statistics)}. פרטי הייבוא זמינים בהיסטוריה.`);
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
    const decision = attempt?.unknown ? attempt.decision : choices[caseItem.id];
    if (!decision) return;
    const key = attempt?.key ?? crypto.randomUUID();
    setActionArea("cases");
    setNotice("");
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
    { key: "status", label: "מצב", render: (row) => importStatusLabel(row.status) },
    { key: "period", label: "תקופת מקור", render: (row) => <bdi dir="ltr">{formatDate(row.report_start)} – {formatDate(row.report_end)}</bdi> },
    { key: "rows", label: "רשומות", render: (row) => row.statistics.total_records, align: "end" },
    { key: "results", label: "תוצאות", render: (row) => renderStats(row.statistics) },
    { key: "details", label: "פרטי ייבוא", render: (row) => <details><summary>פרטים ובדיקות</summary><p>{row.issue_codes.map(issueLabel).join(" · ") || "לא דווחו בעיות בייבוא זה."}</p><span>מזהה אצווה: <bdi dir="ltr">{row.id}</bdi></span><p>קודי בדיקה: <bdi dir="ltr">{row.issue_codes.join(" · ") || "אין"}</bdi></p></details> },
  ], []);

  const firstImport = Boolean(quality && quality.accepted_rows === 0 && !quality.latest_import);
  const checks = quality?.monthly_checks ?? [];
  const sourceGaps = checks.filter((month) => !month.source_period_complete);
  const incomplete = checks.filter((month) => !month.complete);

  const feedback = <>{notice && <div className="quality-status" role="status">{notice}</div>}{actionError && <div className="quality-error" role="alert">{actionError.message}{actionError.requestId && <details><summary>פרטי פנייה לתמיכה</summary><bdi dir="ltr">{actionError.requestId}</bdi></details>}</div>}</>;

  function monthCheck(month: NonNullable<DataQualitySummary["monthly_checks"]>[number]) {
    return <li key={month.month} className="quality-month">
      <strong>{formatHebrewMonth(month.month)}</strong>
      <div className="quality-month-reasons">
        {!month.source_period_complete && <p>תקופת המקור חלקית או שטרם אומתה. <a className="quality-link" href="#familybiz-import">ייבוא דוח שמכסה את כל החודש</a></p>}
        {!month.classification_complete && <p>{month.unclassified_transaction_count === 1 ? "עסקה אחת ללא סיווג." : `${month.unclassified_transaction_count} עסקאות ללא סיווג.`} <Link className="quality-link" href={`/classification?month=${month.month.slice(0, 7)}&currency=ILS`}>מעבר לתור הסיווג</Link></p>}
        {month.open_reconciliation_count > 0 && <p>{month.open_reconciliation_count === 1 ? "התאמה אחת פתוחה." : `${month.open_reconciliation_count} התאמות פתוחות.`} <a className="quality-link" href="#reconciliation-cases">בדיקת ההתאמות</a></p>}
        {month.complete && <p>תקופת המקור, הסיווג וההתאמות עברו את הבדיקות.</p>}
      </div>
    </li>;
  }

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
      <div className="quality-section-heading"><div><h2>{quality.accepted_rows ? "מה עוד צריך להשלים?" : "מתחילים מהנתונים שלכם"}</h2><p>{firstImport ? "העלו את הדוח הראשון. לאחר הייבוא נציג בדיקות לפי חודש ואת הפעולות להשלמת הנתונים." : checks.length ? <>נבדקים {formatHebrewMonth(checks[0].month)} עד {formatHebrewMonth(checks[checks.length - 1].month)}. סיווג וסכומים נבדקים בש״ח.</> : "לא ניתן עדיין לקבוע שהנתונים מלאים. העלו דוח ראשון ובדקו אילו תקופות הוא מכסה."}</p></div><a className="quality-button primary quality-cta" href="#familybiz-import">ייבוא דוח FamilyBiz</a></div>
      {firstImport ? <Card className="quality-detail"><h2>הדוח הראשון הוא נקודת ההתחלה</h2><p>בחרו ב־FamilyBiz את החשבונות ואת התקופה שברצונכם לייבא. נציג את השינויים לבדיקה לפני שתאשרו שמירה.</p><p>עד לייבוא אין בסיס לקבוע שהנתונים מלאים. גם לאחר בדיקת התקופה, כיסוי כל חשבונות המשפחה אינו מאומת אוטומטית.</p></Card> : <>
      <div className="quality-grid quality-checks" aria-label="בדיקות איכות נתונים">
        <Card className="quality-detail"><span className="quality-kicker">01 · תקופת המקור</span><h3>{checks.length ? sourceGaps.length ? sourceGaps.length === 1 ? "חודש אחד ללא כיסוי תקופה מלא" : `${sourceGaps.length} חודשים ללא כיסוי תקופה מלא` : "התקופות שנבדקו מכוסות" : "כיסוי התקופות טרם נבדק"}</h3><p>דוח צריך לכסות את החודש כולו, עם עדכניות מספקת בסוף התקופה. חודש חסר אינו חודש ללא פעילות.</p><a className="quality-link" href="#month-checks">בדיקת החודשים</a></Card>
        <Card className="quality-detail"><span className="quality-kicker">02 · סיווג העסקאות</span><h3>{quality.unclassified_transaction_count ? quality.unclassified_transaction_count === 1 ? "עסקה אחת ממתינה לסיווג" : `${quality.unclassified_transaction_count} עסקאות ממתינות לסיווג` : quality.accepted_rows ? "אין עסקאות הממתינות לסיווג בש״ח" : "הסיווג ייבדק לאחר הייבוא"}</h3><p>{quality.unclassified_transaction_count > 0 ? <>סכום מוחלט לבדיקה: <span className="quality-money">{money(quality.unclassified_absolute_amount)}</span>. סיווג העסקאות קובע כיצד הן נכללות בהכנסות ובהוצאות.</> : "הבדיקה מתייחסת לעסקאות בש״ח שנקלטו בתקופה, ואינה מעידה על כיסוי כל החשבונות."}</p><Link className="quality-link" href="/classification">מעבר לתור הסיווג</Link></Card>
        <Card className="quality-detail"><span className="quality-kicker">03 · התאמת עסקאות</span><h3>{quality.open_reconciliation_cases ? quality.open_reconciliation_cases === 1 ? "התאמה אחת פתוחה בתקופה" : `${quality.open_reconciliation_cases} התאמות פתוחות בתקופה` : "אין התאמות פתוחות בתקופה"}</h3><p>כשעסקה חדשה דומה לעסקה קיימת, נדרשת החלטה לפני הוספה או קישור. כך נמנעת ספירה כפולה.</p><a className="quality-link" href="#reconciliation-cases">בדיקת ההתאמות</a></Card>
      </div>
      <Card className="quality-detail" id="month-checks">
        <h2>חודשים שדורשים השלמה</h2>
        <p>כל חודש נבדק בנפרד: תקופת מקור, סיווג והתאמות. הסכומים בדוחות עשויים להיות חלקיים עד להשלמת הבדיקות.</p>
        {incomplete.length ? <ul className="quality-list">{incomplete.map(monthCheck)}</ul> : checks.length ? <p>כל החודשים בטווח עברו את שלוש הבדיקות.</p> : quality.incomplete_months.length ? <ul className="quality-list">{quality.incomplete_months.map((month) => <li key={month}>{formatHebrewMonth(month)} · סיבת החוסר אינה זמינה. עדכנו את הנתונים כדי לבדוק.</li>)}</ul> : <p>אין עדיין תוצאות בדיקה לפי חודש.</p>}
        {checks.some((month) => month.complete) && <details className="quality-disclosure"><summary>כל החודשים בטווח ({checks.length})</summary><ul className="quality-list">{checks.map(monthCheck)}</ul></details>}
        <div className="quality-scope-note"><strong>האם כל החשבונות של המשפחה כלולים?</strong><p>כיסוי חשבונות המשפחה: {coverageLabel(quality.source_coverage)}. מעבר בדיקות החודשים אינו מאשר שכל חשבונות הבנק והכרטיסים נכללו בייצוא. בדקו אותם מול המקור ב־FamilyBiz.</p></div>
      </Card>
      </>}

    </>}

    <Card className="quality-detail" id="familybiz-import">
      <h2>העלאת קובץ FamilyBiz</h2>
      <p>ייצאו מ־FamilyBiz דוח XLSX שכולל את החשבונות ואת מלוא התקופה שברצונכם להשלים. לקצה החודש דרוש גם מידע עדכני מספיק.</p>
      <ol className="quality-steps"><li>בחירת קובץ</li><li>בדיקת השינויים</li><li>אישור וייבוא</li></ol>
      <p>התצוגה המקדימה אינה משנה נתונים. לאחר הבדיקה תוכלו לאשר את הייבוא.</p>
      {actionArea === "import" && feedback}
      {commitOutcomeUnknown && <div className="quality-notice" role="alert">רעננו את היסטוריית הייבוא. אל תשלחו שוב את אותה תצוגה; אחרי בדיקת המצב, צרו תצוגה מקדימה חדשה כדי להחליט אם לפעול.</div>}
      <form onSubmit={(event) => void previewFile(event)}>
        <div className="form-field"><label className="form-label" htmlFor="quality-familybiz-file">קובץ XLSX של FamilyBiz <span aria-hidden="true">*</span></label>
          <div className="quality-file-picker"><input id="quality-familybiz-file" className="quality-native-file" ref={fileInput} tabIndex={-1} type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={onFileChange} disabled={Boolean(busy)} aria-label="קובץ XLSX של FamilyBiz" aria-describedby="quality-file-hint" /><button className="quality-button" type="button" onClick={() => fileInput.current?.click()} disabled={Boolean(busy)}>בחירת קובץ XLSX</button><bdi>{file?.name || "לא נבחר קובץ"}</bdi></div>
          <span className="field-hint" id="quality-file-hint">גודל הקובץ המרבי: 25 MiB. הקובץ נבדק לפני הייבוא.</span>
        </div>
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
        <h3>בדיקת השינויים לפני הייבוא</h3>
        <p>תקופת המקור המוצהרת בקובץ: <bdi dir="ltr">{formatDate(preview.inspection.report_start)} – {formatDate(preview.inspection.report_end)}</bdi></p>
        <details><summary>פרטים טכניים של הבדיקה</summary><dl className="quality-summary">
          <div><dt>טביעת אצבע לתכנית</dt><dd><bdi>{preview.decision_plan_fingerprint}</bdi></dd></div>
          <div><dt>ייבוא בסיס</dt><dd><bdi>{preview.baseline_batch_id || "אין"}</bdi></dd></div>
          <div><dt>גרסת מנתח / התאמה / תכנית</dt><dd><bdi>{preview.parser_version} · {preview.matcher_version} · {preview.decision_plan_version}</bdi></dd></div>
        </dl></details>
        {preview.predicted_statistics && <p>{renderStats(preview.predicted_statistics)}</p>}
        {preview.predicted_statistics?.duplicate_file && <div className="quality-notice">הקובץ הזה כבר יובא. אישור יתעד קובץ כפול ללא הוספת עסקאות.</div>}
        {(preview.warning_count > 0 || preview.rejected_count > 0) && <div className="quality-notice"><strong>נמצאו פריטים לבדיקה</strong><p>רשומות שנדחו לא ייקלטו. אזהרות עשויות לדרוש סיווג או בדיקה מול המקור גם לאחר הייבוא.</p><ul>{Object.entries(preview.issue_counts).map(([code, count]) => <li key={code}>{issueLabel(code)} · {count}</li>)}</ul></div>}
        {Boolean(preview.predicted_statistics?.unresolved) && <p>עסקאות שממתינות להתאמה לא יתווספו עד להחלטה. לאחר הייבוא בדקו את ההתאמות למטה.</p>}
        <div className="quality-actions">
          <button className="quality-button" type="button" onClick={() => downloadDecisionPlan(preview)} disabled={Boolean(busy)}>הורדת תכנית החלטות מלאה</button>
          <button className="quality-button primary" type="button" onClick={() => void commitImport()} disabled={Boolean(busy) || commitOutcomeUnknown}>{busy === "commit" ? "שומרים…" : "אישור וייבוא"}</button>
        </div>
        <details><summary>פירוט בדיקה, בסיס התאמה ודוגמאות</summary>
          <p>מטבעות: {Object.entries(preview.inspection.currencies).map(([currency, count]) => `${currencyLabel(currency)}: ${count}`).join(" · ") || "אין"}</p>
          <p>ספירות בעיות: {Object.entries(preview.issue_counts).map(([code, count]) => `${code}: ${count}`).join(" · ") || "אין"}</p>
          <h3>בסיס התאמה</h3><pre>{preview.matching_baseline_json}</pre>
          <h3>דוגמאות מהקובץ</h3><pre>{JSON.stringify(preview.preview_rows.slice(0, 10), null, 2)}</pre>
        </details>
      </div>}
    </Card>

    <Card className="quality-detail"><details className="quality-history">
      <summary id="import-history"><strong>היסטוריית ייבוא</strong><span>{history?.length ? `ייבוא אחרון: ${formatDate(history[0].created_at)} · ${importStatusLabel(history[0].status)}` : history === null ? loading ? "טוענים היסטוריה…" : "ההיסטוריה אינה זמינה" : refreshError ? "העדכון נכשל - מוצגת הטעינה הקודמת" : "טרם בוצע ייבוא"}</span></summary>
      {actionArea === "history" && feedback}
      {history === null ? <p role="status">{loading ? "טוענים את היסטוריית הייבוא…" : "היסטוריית הייבוא אינה זמינה כרגע. לא ניתן לקבוע אם קיימים ייבואים. נסו לעדכן את ההיסטוריה."}</p> : <>
        {refreshError && <p className="quality-notice" role="status">עדכון ההיסטוריה נכשל. מוצגות תוצאות מהטעינה הקודמת; ייתכן שהייבוא השתנה מאז. עדכנו את ההיסטוריה לפני החלטה על פעולה נוספת.</p>}
        <ResponsiveDataTable caption="היסטוריית ייבוא" rows={history} getRowKey={(row) => row.id} columns={historyColumns} emptyTitle={refreshError ? "לא נמצאו ייבואים בטעינה הקודמת" : "אין ייבואים להצגה"} emptyDescription={refreshError ? "לא ניתן לקבוע אם נוספו ייבואים מאז הטעינה הקודמת." : "היסטוריה תופיע לאחר השלמת ייבוא."} />
      </>}
      {historyCursor && <div className="quality-pagination"><button className="quality-button" type="button" disabled={Boolean(busy)} onClick={() => void loadMore("history")}>{busy === "more-history" ? "טוענים…" : "טעינת ייבואים נוספים"}</button></div>}
    </details></Card>

    <Card className="quality-detail">
      <h2 id="reconciliation-cases">התאמות פתוחות</h2>
      {actionArea === "cases" && feedback}
      <p>זו רשימת ההתאמות הפתוחות מכל התקופות. בדקו את פרטי המקור ואת העסקאות המועמדות לפני בחירת החלטה.</p>
      {!quality ? <p>{loading ? "טוענים התאמות…" : "ההתאמות אינן זמינות כרגע. נסו לעדכן את הנתונים."}</p> : !cases.length ? <p>אין תיקי התאמה פתוחים.</p> : <div className="quality-cases">{cases.map((item) => {
        const attempt = resolutionAttempts[item.id];
        const selected = choices[item.id];
        const lockedDecision = attempt?.unknown ? attempt.decision : null;
        return <section className="quality-case" key={item.id} aria-label={`תיק התאמה ${item.id}`}>
          <h3>{item.source?.description || "עסקה שנדרשת עבורה התאמה"}</h3>
          {item.source && <dl className="quality-summary"><div><dt>תאריך העסקה</dt><dd>{formatDate(item.source.booking_date)}</dd></div><div><dt>סכום במקור</dt><dd className="quality-money">{money(item.source.amount, item.source.currency)}</dd></div></dl>}
          <p>{item.reason === "Plausible non-exact candidate transactions" ? "נמצאו עסקאות דומות, אך אין התאמה ודאית. בדקו אם זו עסקה חדשה או אותה עסקה שכבר נקלטה." : "הייבוא לא הצליח לקבוע התאמה ודאית. בדקו את המקור ואת העסקאות הקיימות."}</p>
          <p>קבלה כחדשה מוסיפה עסקה; קישור מעדכן עסקה קיימת לפי המקור; דחייה משאירה את הרשומה מחוץ לעסקאות.</p>
          <details><summary>מזהים וסיבת הבדיקה המקורית</summary><bdi dir="ltr">{item.id} · {item.reason}</bdi></details>
          {item.candidates.length > 0 && <div><h3>עסקאות קיימות שאולי מתאימות</h3><ul className="quality-list">{item.candidates.map((candidate) => <li key={candidate.id}><span>{candidate.description}<br /><small>{formatDate(candidate.booking_date)} · {candidate.account}</small></span><span className="quality-money">{money(candidate.amount, candidate.currency)}</span></li>)}</ul></div>}
          <details><summary>הצגת הרשומה והמועמדות</summary><pre>{JSON.stringify({ source: item.source, candidates: item.candidates }, null, 2)}</pre></details>
          {attempt?.unknown ? <div className="quality-notice" role="status">התוצאה לא ידועה. הניסיון הבא ישלח אותה החלטה עם אותו מפתח.</div> : <>
            <label>החלטה
              <select value={selected?.resolution ?? ""} onChange={(event) => setResolution(item.id, { resolution: event.target.value as Resolution["resolution"] })} disabled={Boolean(busy)}>
                <option value="" disabled>בחרו החלטה לאחר בדיקה</option>
                <option value="accept_as_new">קבלת הרשומה כעסקה חדשה</option>
                <option value="dismiss">דחיית הרשומה</option>
                {item.candidates.length > 0 && <option value="link_existing">קישור לעסקה קיימת</option>}
              </select>
            </label>
            {selected?.resolution === "link_existing" && item.candidates.length > 0 && <label>עסקה מועמדת
              <select value={selected.transaction_id ?? ""} onChange={(event) => setResolution(item.id, { resolution: "link_existing", transaction_id: Number(event.target.value) })} disabled={Boolean(busy)}>
                <option value="" disabled>בחרו עסקה</option>
                {item.candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{formatDate(candidate.booking_date)} · {candidate.description} · {money(candidate.amount, candidate.currency)} · מזהה {candidate.id}</option>)}
              </select>
            </label>}
          </>}
          <div className="quality-actions">
            <button className="quality-button primary" type="button" disabled={Boolean(busy) || (!attempt?.unknown && (!selected || (selected.resolution === "link_existing" && !selected.transaction_id)))} onClick={() => void resolveCase(item)}>{busy === `resolve-${item.id}` ? "שומרים…" : attempt?.unknown ? "שליחה חוזרת של אותה החלטה" : "שמירת החלטה"}</button>
            {lockedDecision && <span className="field-hint">{lockedDecision.resolution === "link_existing" ? `קישור לעסקה ${lockedDecision.transaction_id}` : lockedDecision.resolution === "dismiss" ? "דחייה" : "קבלה כחדשה"}</span>}
          </div>
        </section>;
      })}</div>}
      {casesCursor && <div className="quality-pagination"><button className="quality-button" type="button" disabled={Boolean(busy)} onClick={() => void loadMore("cases")}>{busy === "more-cases" ? "טוענים…" : "טעינת התאמות נוספות"}</button></div>}
    </Card>
    {quality && <Card className="quality-detail"><details><summary>פרטי הנתונים והבדיקות</summary><dl className="quality-summary"><div><dt>טווח תאריכי העסקאות שנקלטו</dt><dd><bdi dir="ltr">{formatDate(quality.covered_start)} – {formatDate(quality.covered_end)}</bdi></dd></div><div><dt>תאריך העסקה האחרונה במקור</dt><dd>{formatDate(quality.freshness_date)}</dd></div><div><dt>עסקאות לפי מטבע</dt><dd>{Object.entries(quality.currencies).map(([currency, count]) => `${currencyLabel(currency)}: ${count}`).join(" · ") || "אין נתונים"}</dd></div><div><dt>שורות שהתקבלו בתקופה</dt><dd>{quality.accepted_rows}</dd></div></dl><p>טווח תאריכי העסקאות אינו אישור לכיסוי רציף של התקופה. ספירת הבדיקות עשויה לכלול כמה בעיות לאותה עסקה, וגם הערות מקור שנשארות לאחר תיקון הסיווג.</p><ul className="quality-list">{Object.entries(quality.issue_counts).map(([code, count]) => <li key={code}><span>{issueLabel(code)}<details><summary>קוד בדיקה</summary><bdi dir="ltr">{code}</bdi></details></span><strong>{count}</strong></li>)}</ul>{quality.latest_import && <p>גרסת מנתח הקובץ: <bdi dir="ltr">{quality.latest_import.parser_version}</bdi></p>}</details></Card>}
  </div>;
}
