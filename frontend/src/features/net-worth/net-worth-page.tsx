"use client";

import { useEffect, useRef, useState } from "react";
import { ApiRequestError, apiRequest } from "@/lib/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/async-state";
import { Button } from "@/components/ui/button";
import {
  getAccountHistory,
  getAccounts,
  getRevisions,
  getSummary,
  getSnapshots,
  getTrend,
  postCsvPreview,
} from "./api";
import type {
  AccountHistoryItem,
  CsvPreview,
  NetWorthAccount,
  NetWorthSummary,
  SnapshotBalance,
  SnapshotRevision,
  SnapshotSummary,
  TrendPoint,
} from "./types";
import styles from "./net-worth.module.css";

type AccountDraft = {
  mode: "create" | "edit";
  account_key: string;
  display_name: string;
  side: "asset" | "liability";
  category: string;
  liquidity: string;
  owner_label: string;
  active_from: string;
  active_to: string;
  stale_after_days: string;
};
type EditorAccount = Pick<NetWorthAccount, "account_key" | "display_name" | "side" | "category" | "liquidity" | "owner_label" | "stale_after_days">;
type BalanceDraft = Record<string, { amount_ils: string; valuation_date: string; notes: string }>;

const assetCategories = ["cash", "savings", "investment", "pension", "training_fund", "property", "other"];
const liabilityCategories = ["mortgage", "loan", "credit", "other"];
const liquidityOptions = ["liquid", "restricted", "illiquid"];
const categoryLabels: Record<string, string> = {
  cash: "מזומן", savings: "חיסכון", investment: "השקעות", pension: "פנסיה",
  training_fund: "קרן השתלמות", property: "נדל״ן", other: "אחר", mortgage: "משכנתה",
  loan: "הלוואה", credit: "אשראי", liquid: "נזיל", restricted: "מוגבל", illiquid: "לא נזיל",
};
const issueLabels: Record<string, string> = {
  CSV_HEADERS_INVALID: "כותרות העמודות אינן תואמות לתבנית.",
  CSV_NOT_UTF8: "הקובץ אינו בקידוד UTF-8.",
  CSV_TOO_LARGE: "הקובץ חורג ממגבלת הגודל.",
  CSV_ROW_LIMIT_EXCEEDED: "הקובץ מכיל יותר מדי שורות.",
  CSV_MISSING_ACTIVE_ACCOUNT: "חסרים חשבונות פעילים לתאריך התמונה.",
  CSV_DUPLICATE_ACCOUNT: "חשבון מופיע יותר מפעם אחת.",
  CSV_MULTIPLE_SNAPSHOT_DATES: "הקובץ מכיל יותר מתאריך תמונה אחד.",
  CSV_FOREIGN_OR_INACTIVE_ACCOUNT: "הקובץ כולל חשבון שאינו פעיל בתאריך שנבחר.",
  CSV_FOREIGN_CURRENCY: "הסכום חייב להיות בשקלים בלבד.",
};

function todayIso() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function formatIls(value: string | null | undefined) {
  if (value == null) return "—";
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [whole, fraction] = unsigned.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "−" : ""}${grouped}${fraction ? `.${fraction}` : ""} ₪`;
}

function displayError(error: unknown) {
  if (!(error instanceof ApiRequestError)) return { message: "הפעולה לא הושלמה. בדקו את הקלט ונסו שוב.", requestId: undefined };
  if (error.status === 0) return { message: "לא ידוע אם השמירה הושלמה. טענו מצב עדכני לפני ניסיון נוסף.", requestId: undefined };
  return { message: error.apiError?.message || "הפעולה לא הושלמה.", requestId: error.apiError?.request_id };
}

function emptyAccountDraft(): AccountDraft {
  return {
    mode: "create", account_key: "", display_name: "", side: "asset", category: "cash",
    liquidity: "liquid", owner_label: "", active_from: todayIso(), active_to: "", stale_after_days: "45",
  };
}

function mapBalanceDraft(balances: Array<Pick<SnapshotBalance, "account_key" | "amount_ils" | "valuation_date" | "notes">>): BalanceDraft {
  return Object.fromEntries(balances.map((item) => [item.account_key, {
    amount_ils: item.amount_ils,
    valuation_date: item.valuation_date,
    notes: item.notes || "",
  }]));
}

function isEmptySummaryError(error: unknown) {
  return error instanceof ApiRequestError && (error.status === 404 || error.apiError?.code === "NOT_FOUND");
}

export function NetWorthPage() {
  const [accounts, setAccounts] = useState<NetWorthAccount[]>([]);
  const [snapshots, setSnapshots] = useState<SnapshotSummary[]>([]);
  const [revisions, setRevisions] = useState<SnapshotRevision[]>([]);
  const [selectedSnapshotId, setSelectedSnapshotId] = useState("");
  const [selectedRevisionId, setSelectedRevisionId] = useState("");
  const [summary, setSummary] = useState<NetWorthSummary | null>(null);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [historyAccount, setHistoryAccount] = useState("");
  const [history, setHistory] = useState<AccountHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [pageError, setPageError] = useState<{ message: string; requestId?: string } | null>(null);
  const [actionError, setActionError] = useState<{ message: string; requestId?: string } | null>(null);
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [accountDraft, setAccountDraft] = useState<AccountDraft | null>(null);
  const [composer, setComposer] = useState<"new" | "revision" | null>(null);
  const [captureDate, setCaptureDate] = useState(todayIso());
  const [editorAccounts, setEditorAccounts] = useState<EditorAccount[]>([]);
  const [balanceDraft, setBalanceDraft] = useState<BalanceDraft>({});
  const [snapshotNotes, setSnapshotNotes] = useState("");
  const [qualityAcknowledged, setQualityAcknowledged] = useState(false);
  const [needsReconcile, setNeedsReconcile] = useState(false);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvPreview, setCsvPreview] = useState<CsvPreview | null>(null);
  const [csvCreateRevision, setCsvCreateRevision] = useState(false);
  const [csvQualityAcknowledged, setCsvQualityAcknowledged] = useState(false);
  const selectedSnapshotRef = useRef("");

  const selectedSnapshot = snapshots.find((item) => item.snapshot_id === selectedSnapshotId) ?? null;
  const selectedRevision = revisions.find((item) => item.revision_id === selectedRevisionId) ?? revisions.at(-1) ?? null;

  async function loadData(): Promise<boolean> {
    setLoading(true);
    setPageError(null);
    try {
      const [nextAccounts, nextSnapshots, nextTrend] = await Promise.all([
        getAccounts({ includeClosed: true }), getSnapshots(true), getTrend(),
      ]);
      setAccounts(nextAccounts);
      setSnapshots(nextSnapshots);
      setTrend(nextTrend);
      const chosen = nextSnapshots.find((item) => item.snapshot_id === selectedSnapshotRef.current) ?? nextSnapshots[0] ?? null;
      const chosenId = chosen?.snapshot_id ?? "";
      selectedSnapshotRef.current = chosenId;
      setSelectedSnapshotId(chosenId);
      if (chosenId) {
        const [nextRevisions, nextSummary] = await Promise.all([
          getRevisions(chosenId),
          getSummary(chosenId).catch((error) => {
            if (isEmptySummaryError(error)) return null;
            throw error;
          }),
        ]);
        setRevisions(nextRevisions);
        setSelectedRevisionId(nextRevisions.at(-1)?.revision_id ?? "");
        setSummary(nextSummary);
      } else {
        setRevisions([]);
        setSelectedRevisionId("");
        setSummary(null);
      }
      setLoaded(true);
      return true;
    } catch (error) {
      setPageError(displayError(error));
      return false;
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadData(); }, []);

  useEffect(() => {
    if (composer !== "new") return;
    let current = true;
    void getAccounts({ asOf: captureDate }).then((items) => {
      if (!current) return;
      setEditorAccounts(items);
      setBalanceDraft((previous) => Object.fromEntries(items.map((item) => [item.account_key, previous[item.account_key] ?? {
        amount_ils: "", valuation_date: captureDate, notes: "",
      }])));
    }).catch((error) => { if (current) setActionError(displayError(error)); });
    return () => { current = false; };
  }, [composer, captureDate]);

  async function chooseSnapshot(snapshotId: string) {
    selectedSnapshotRef.current = snapshotId;
    setSelectedSnapshotId(snapshotId);
    setComposer(null);
    setActionError(null);
    try {
      const [nextRevisions, nextSummary] = await Promise.all([
        getRevisions(snapshotId),
        getSummary(snapshotId).catch((error) => { if (isEmptySummaryError(error)) return null; throw error; }),
      ]);
      setRevisions(nextRevisions);
      setSelectedRevisionId(nextRevisions.at(-1)?.revision_id ?? "");
      setSummary(nextSummary);
    } catch (error) { setActionError(displayError(error)); }
  }

  async function runMutation(operation: () => Promise<unknown>, success: string) {
    setSaving(true);
    setActionError(null);
    setNotice("");
    try {
      await operation();
      setNotice(success);
      setComposer(null);
      setCsvPreview(null);
      await loadData();
    } catch (error) {
      const parsed = displayError(error);
      if (error instanceof ApiRequestError && (error.status === 0 || error.status === 408 || error.status >= 500)) {
        setNeedsReconcile(true);
        setCsvPreview(null);
      }
      setActionError(parsed);
    } finally { setSaving(false); }
  }

  async function saveAccount(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accountDraft) return;
    const payload = {
      account_key: accountDraft.account_key.trim(),
      display_name: accountDraft.display_name,
      side: accountDraft.side,
      category: accountDraft.category,
      liquidity: accountDraft.side === "asset" ? accountDraft.liquidity : null,
      owner_label: accountDraft.owner_label || null,
      active_from: accountDraft.active_from,
      active_to: accountDraft.active_to || null,
      stale_after_days: Number.parseInt(accountDraft.stale_after_days, 10),
    };
    const mode = accountDraft.mode;
    await runMutation(async () => {
      if (mode === "create") await apiRequest("/net-worth/accounts", { method: "POST", body: JSON.stringify(payload) });
      else await apiRequest(`/net-worth/accounts/${encodeURIComponent(accountDraft.account_key)}`, { method: "PUT", body: JSON.stringify(payload) });
      setAccountDraft(null);
    }, mode === "create" ? "החשבון נוסף לרשימה." : "פרטי החשבון עודכנו.");
  }

  function editAccount(account?: NetWorthAccount) {
    if (!account) { setAccountDraft(emptyAccountDraft()); return; }
    setAccountDraft({
      mode: "edit", account_key: account.account_key, display_name: account.display_name,
      side: account.side, category: account.category, liquidity: account.liquidity ?? "",
      owner_label: account.owner_label ?? "", active_from: account.active_from,
      active_to: account.active_to ?? "", stale_after_days: String(account.stale_after_days),
    });
  }

  async function loadAccountHistory(accountKey: string) {
    setHistoryAccount(accountKey);
    setHistory([]);
    try { setHistory(await getAccountHistory(accountKey)); }
    catch (error) { setActionError(displayError(error)); }
  }

  function startNewSnapshot() {
    setComposer("new");
    setCaptureDate(todayIso());
    setBalanceDraft({});
    setSnapshotNotes("");
    setQualityAcknowledged(false);
    setActionError(null);
  }

  function startRevision() {
    if (!selectedRevision) return;
    setComposer("revision");
    setCaptureDate(selectedRevision.snapshot_date);
    setEditorAccounts(selectedRevision.balances.map((item) => ({
      account_key: item.account_key, display_name: item.account_name, side: item.side,
      category: item.category, liquidity: item.liquidity, owner_label: item.owner_label,
      stale_after_days: item.stale_after_days,
    })));
    setBalanceDraft(mapBalanceDraft(selectedRevision.balances));
    setSnapshotNotes(selectedRevision.notes);
    setQualityAcknowledged(false);
    setActionError(null);
  }

  async function saveSnapshot(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const missing = editorAccounts.filter((account) => !balanceDraft[account.account_key]?.amount_ils.trim());
    if (missing.length) {
      setActionError({ message: `יש להזין סכום לכל חשבון: ${missing.map((item) => item.display_name).join(", ")}` });
      return;
    }
    const balances = editorAccounts.map((account) => ({
      account_key: account.account_key,
      amount_ils: balanceDraft[account.account_key].amount_ils,
      valuation_date: balanceDraft[account.account_key].valuation_date,
      notes: balanceDraft[account.account_key].notes,
    }));
    if (composer === "new") {
      await runMutation(() => apiRequest("/net-worth/snapshots", {
        method: "POST", body: JSON.stringify({ snapshot_date: captureDate, balances, notes: snapshotNotes, quality_acknowledged: qualityAcknowledged }),
      }), "תמונת המצב נשמרה כגרסה ראשונה.");
      return;
    }
    if (!selectedSnapshot) return;
    await runMutation(() => apiRequest(`/net-worth/snapshots/${encodeURIComponent(selectedSnapshot.snapshot_id)}/revisions`, {
      method: "POST", body: JSON.stringify({
        balances, expected_revision_number: selectedSnapshot.current_revision_number,
        notes: snapshotNotes, quality_acknowledged: qualityAcknowledged,
      }),
    }), "נשמרה גרסה חדשה. הגרסאות הקודמות נשארו ללא שינוי.");
  }

  async function restoreRevision(revision: SnapshotRevision) {
    if (!selectedSnapshot) return;
    await runMutation(() => apiRequest(
      `/net-worth/snapshots/${encodeURIComponent(selectedSnapshot.snapshot_id)}/revisions/${revision.revision_number}/restore`,
      { method: "POST", body: JSON.stringify({ expected_revision_number: selectedSnapshot.current_revision_number, quality_acknowledged: revision.quality_acknowledged }) },
    ), `הגרסה ${revision.revision_number} שוחזרה כגרסה חדשה.`);
  }

  async function setArchived(snapshot: SnapshotSummary) {
    await runMutation(() => apiRequest(`/net-worth/snapshots/${encodeURIComponent(snapshot.snapshot_id)}/archive`, {
      method: "POST", body: JSON.stringify({ archived: !snapshot.archived }),
    }), snapshot.archived ? "התמונה הוחזרה לרשימה הפעילה." : "התמונה הועברה לארכיון.");
  }

  async function downloadTemplate() {
    setActionError(null);
    try {
      const response = await fetch(`/api/v1/net-worth/csv-template?snapshot_date=${encodeURIComponent(captureDate)}`, {
        credentials: "same-origin", cache: "no-store", referrerPolicy: "no-referrer",
      });
      if (!response.ok) throw new ApiRequestError("לא ניתן להוריד את התבנית.", response.status);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "net-worth-template.csv";
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) { setActionError(displayError(error)); }
  }

  async function previewCsv() {
    if (!csvFile || needsReconcile) return;
    setActionError(null);
    setCsvPreview(null);
    try {
      const result = await postCsvPreview(csvFile);
      setCsvPreview(result);
      setCsvCreateRevision(false);
      setCsvQualityAcknowledged(false);
    } catch (error) { setActionError(displayError(error)); }
  }

  async function commitCsv() {
    if (!csvFile || !csvPreview?.valid) return;
    const form = new FormData();
    form.append("file", csvFile, csvFile.name);
    form.append("preview_token", csvPreview.preview_token);
    form.append("filename", csvFile.name);
    form.append("create_new_revision", String(csvCreateRevision));
    form.append("quality_acknowledged", String(csvQualityAcknowledged));
    await runMutation(() => apiRequest("/net-worth/csv/commits", { method: "POST", body: form }), "ייבוא הקובץ נשמר כתמונת מצב וגרסה חדשה.");
  }

  if (loading && !loaded) return <LoadingState label="טוענים חשבונות ותמונות מצב…" />;
  if (pageError && !loaded) return <ErrorState description={pageError.message} requestId={pageError.requestId} onRetry={() => void loadData()} retrying={loading} />;

  return <div className={styles.page}>
    <div className={styles.toolbar}>
      <div><span className={styles.eyebrow}>יתרות שנמדדו בפועל</span><h2>הון משפחתי</h2><p>רישום חשבונות, תמונות מצב מתוארכות והיסטוריית גרסאות.</p></div>
      <Button variant="outline" disabled={loading || saving} onClick={() => void loadData()}>רענון נתונים</Button>
    </div>
    {actionError && <div className={styles.alert} role="alert"><span>{actionError.message}</span>{actionError.requestId && <small>מזהה פנייה: <bdi>{actionError.requestId}</bdi></small>}</div>}
    {needsReconcile && <div className={styles.warning} role="alert"><span>תוצאת הפעולה לא ידועה. טענו את מצב החשבונות והגרסאות העדכני לפני בחירת פעולה נוספת.</span><Button variant="outline" disabled={loading} onClick={async () => { if (await loadData()) { setNeedsReconcile(false); setActionError(null); setNotice("המידע נטען מחדש. בדקו את המצב לפני שליחה נוספת."); } }}>טעינת מצב עדכני</Button></div>}
    {pageError && loaded && <div className={styles.alert} role="alert">{pageError.message}</div>}
    {notice && <div className={styles.notice} role="status">{notice}</div>}

    <section className={styles.section} aria-labelledby="summary-heading">
      <div className={styles.sectionHeading}><div><h3 id="summary-heading">תמונת מצב נבחרת</h3><p>{summary ? `${summary.snapshot_date} · גרסה ${summary.revision_number}` : "סיכום לפי תמונת המצב האחרונה"}</p></div></div>
      {!summary ? <EmptyState title="עדיין אין תמונת מצב" description="הוסיפו חשבונות ורשמו את היתרות ליום מדידה מסוים." /> : <>
        <div className={styles.metrics}>
          <Metric label="שווי נקי" value={formatIls(summary.net_worth)} emphasis />
          <Metric label="נכסים" value={formatIls(summary.total_assets)} />
          <Metric label="התחייבויות" value={formatIls(summary.total_liabilities)} />
          <Metric label="נכסים נזילים" value={formatIls(summary.liquid_assets)} />
        </div>
        <div className={styles.summaryMeta}>
          <span>נזילות מוגבלת: <bdi>{formatIls(summary.restricted_assets)}</bdi></span>
          <span>נכסים לא נזילים: <bdi>{formatIls(summary.illiquid_assets)}</bdi></span>
          <span>גיל תמונה: {summary.snapshot_freshness_days ?? "—"} ימים</span>
        </div>
        {summary.stale_account_keys.length > 0 && <div className={styles.warning} role="status">הערכת שווי ישנה בחשבונות: {summary.stale_account_keys.map((key) => accounts.find((account) => account.account_key === key)?.display_name ?? key).join(", ")}</div>}
        <div className={styles.breakdowns}>
          <Breakdown title="לפי סוג נכס או התחייבות" values={summary.by_category} />
          <Breakdown title="לפי בעלות" values={summary.by_owner} />
          <Breakdown title="לפי נזילות" values={summary.by_liquidity} />
        </div>
      </>}
    </section>

    <section className={styles.section} aria-labelledby="accounts-heading">
      <div className={styles.sectionHeading}><div><h3 id="accounts-heading">רשימת חשבונות</h3><p>פרטי החשבון נשמרים עם כל גרסת תמונת מצב כדי לשמור על היסטוריה מדויקת.</p></div><Button onClick={() => editAccount()} disabled={saving || needsReconcile}>הוספת חשבון</Button></div>
      {accounts.length === 0 ? <EmptyState title="אין חשבונות רשומים" description="הוסיפו חשבון נכס או התחייבות לפני שמירת תמונת מצב." /> : <div className={styles.tableWrap}>
        <table><caption className={styles.srOnly}>רשימת חשבונות הון משפחתי</caption><thead><tr><th>חשבון</th><th>סוג</th><th>בעלות ונזילות</th><th>פעילות</th><th>פעולות</th></tr></thead><tbody>
          {accounts.map((account) => <tr key={account.account_key}>
            <td><strong>{account.display_name}</strong><small dir="ltr">{account.account_key}</small></td>
            <td>{account.side === "asset" ? "נכס" : "התחייבות"} · {categoryLabels[account.category] ?? account.category}</td>
            <td>{account.owner_label ?? "משותף"}{account.liquidity ? ` · ${categoryLabels[account.liquidity]}` : ""}</td>
            <td>{account.active_to ? `נסגר ${account.active_to}` : `פעיל מ־${account.active_from}`}</td>
            <td className={styles.rowActions}>
              <button type="button" onClick={() => editAccount(account)}>עריכה</button>
              <button type="button" onClick={() => void loadAccountHistory(account.account_key)}>היסטוריה</button>
              {account.active_to
                ? <button type="button" disabled={saving || needsReconcile} onClick={() => void runMutation(() => apiRequest(`/net-worth/accounts/${encodeURIComponent(account.account_key)}/reactivate`, { method: "POST", body: JSON.stringify({ active_from: todayIso() }) }), "החשבון הופעל מחדש.")}>הפעלה מחדש</button>
                : <button type="button" disabled={saving || needsReconcile} onClick={() => void runMutation(() => apiRequest(`/net-worth/accounts/${encodeURIComponent(account.account_key)}/close`, { method: "POST", body: JSON.stringify({ closed_on: todayIso() }) }), "החשבון נסגר לתאריכים עתידיים.")}>סגירה</button>}
            </td>
          </tr>)}
        </tbody></table>
      </div>}

      {accountDraft && <form className={styles.formCard} onSubmit={(event) => void saveAccount(event)}>
        <div className={styles.formHeading}><h4>{accountDraft.mode === "create" ? "חשבון חדש" : `עריכת ${accountDraft.display_name}`}</h4><button type="button" onClick={() => setAccountDraft(null)}>סגירה</button></div>
        <div className={styles.formGrid}>
          <Field label="שם החשבון"><input required maxLength={200} value={accountDraft.display_name} onChange={(event) => setAccountDraft({ ...accountDraft, display_name: event.target.value })} /></Field>
          {accountDraft.mode === "create" && <Field label="מזהה חשבון (רשות)"><input dir="ltr" maxLength={200} value={accountDraft.account_key} onChange={(event) => setAccountDraft({ ...accountDraft, account_key: event.target.value })} /></Field>}
          <Field label="צד"><select value={accountDraft.side} onChange={(event) => {
            const side = event.target.value as "asset" | "liability";
            setAccountDraft({ ...accountDraft, side, category: side === "asset" ? "cash" : "mortgage", liquidity: side === "asset" ? "liquid" : "" });
          }}><option value="asset">נכס</option><option value="liability">התחייבות</option></select></Field>
          <Field label="קטגוריה"><select value={accountDraft.category} onChange={(event) => setAccountDraft({ ...accountDraft, category: event.target.value })}>{(accountDraft.side === "asset" ? assetCategories : liabilityCategories).map((category) => <option key={category} value={category}>{categoryLabels[category] ?? category}</option>)}</select></Field>
          {accountDraft.side === "asset" && <Field label="נזילות"><select value={accountDraft.liquidity} onChange={(event) => setAccountDraft({ ...accountDraft, liquidity: event.target.value })}>{liquidityOptions.map((item) => <option key={item} value={item}>{categoryLabels[item]}</option>)}</select></Field>}
          <Field label="בעלים"><input maxLength={200} value={accountDraft.owner_label} onChange={(event) => setAccountDraft({ ...accountDraft, owner_label: event.target.value })} placeholder="משותף" /></Field>
          <Field label="פעיל מתאריך"><input type="date" required value={accountDraft.active_from} onChange={(event) => setAccountDraft({ ...accountDraft, active_from: event.target.value })} /></Field>
          <Field label="נסגר בתאריך"><input type="date" value={accountDraft.active_to} onChange={(event) => setAccountDraft({ ...accountDraft, active_to: event.target.value })} /></Field>
          <Field label="ימים עד אזהרת הערכת שווי"><input type="number" min="1" max="3650" required value={accountDraft.stale_after_days} onChange={(event) => setAccountDraft({ ...accountDraft, stale_after_days: event.target.value })} /></Field>
        </div>
        <div className={styles.formActions}><Button type="submit" disabled={saving || needsReconcile}>{saving ? "שומר…" : "שמירת חשבון"}</Button><Button type="button" variant="outline" onClick={() => setAccountDraft(null)}>ביטול</Button></div>
      </form>}
    </section>

    {historyAccount && <section className={styles.section} aria-labelledby="history-heading">
      <div className={styles.sectionHeading}><div><h3 id="history-heading">היסטוריית חשבון</h3><p>{accounts.find((item) => item.account_key === historyAccount)?.display_name ?? historyAccount}</p></div><button type="button" onClick={() => { setHistoryAccount(""); setHistory([]); }}>סגירה</button></div>
      {history.length === 0 ? <p className={styles.muted}>אין יתרות היסטוריות לחשבון הזה.</p> : <div className={styles.tableWrap}><table><thead><tr><th>תאריך תמונה</th><th>גרסה</th><th>יתרה</th><th>תאריך הערכה</th></tr></thead><tbody>{history.map((item) => <tr key={`${item.revision_id}-${item.account_key}`}><td>{item.snapshot_date}</td><td>{item.revision_number}</td><td><bdi>{formatIls(item.amount_ils)}</bdi></td><td>{item.valuation_date}</td></tr>)}</tbody></table></div>}
    </section>}

    <section className={styles.section} aria-labelledby="snapshots-heading">
      <div className={styles.sectionHeading}><div><h3 id="snapshots-heading">תמונות מצב וגרסאות</h3><p>כל יתרה היא תצפית שנמסרה במפורש; המערכת אינה מסיקה יתרות מעסקאות או מתוכניות.</p></div><Button onClick={startNewSnapshot} disabled={saving || needsReconcile || accounts.length === 0}>תמונת מצב חדשה</Button></div>
      {snapshots.length === 0 ? <EmptyState title="אין תמונות מצב שמורות" description="בחרו תאריך ומלאו יתרה לכל חשבון שהיה פעיל באותו יום." /> : <div className={styles.snapshotLayout}>
        <div className={styles.snapshotList} aria-label="בחירת תמונת מצב">
          {snapshots.map((snapshot) => <button key={snapshot.snapshot_id} type="button" className={`${styles.snapshotButton}${snapshot.snapshot_id === selectedSnapshotId ? ` ${styles.snapshotSelected}` : ""}`} onClick={() => void chooseSnapshot(snapshot.snapshot_id)}>
            <span>{snapshot.snapshot_date}{snapshot.archived && <em>ארכיון</em>}</span><small>גרסה {snapshot.current_revision_number}</small>
          </button>)}
        </div>
        {selectedSnapshot && <div className={styles.snapshotDetail}>
          <div className={styles.detailHeader}><div><h4>{selectedSnapshot.snapshot_date}</h4><p>{selectedRevision ? `גרסה ${selectedRevision.revision_number} · ${selectedRevision.origin === "csv" ? "ייבוא CSV" : selectedRevision.origin === "restored" ? "שחזור" : "ידנית"}` : "טוענים גרסאות…"}</p></div>
            <div className={styles.inlineActions}><Button size="sm" onClick={startRevision} disabled={saving || needsReconcile || selectedSnapshot.archived || !selectedRevision}>שמירת גרסה חדשה</Button><Button size="sm" variant="outline" disabled={saving || needsReconcile} onClick={() => void setArchived(selectedSnapshot)}>{selectedSnapshot.archived ? "החזרה לארכיון הפעיל" : "העברה לארכיון"}</Button></div>
          </div>
          {selectedRevision && <>
            <div className={styles.revisionMeta}><span>גיבוב תוכן</span><code dir="ltr">{selectedRevision.content_hash}</code></div>
            {selectedRevision.quality_issues.length > 0 && <div className={styles.warning}>איכות: {selectedRevision.quality_issues.join(" · ")}</div>}
            <div className={styles.tableWrap}><table><thead><tr><th>חשבון</th><th>יתרה</th><th>הערכת שווי</th><th>מצב</th></tr></thead><tbody>{selectedRevision.balances.map((balance) => <tr key={balance.account_key}><td>{balance.account_name}</td><td><bdi>{formatIls(balance.amount_ils)}</bdi></td><td>{balance.valuation_date}</td><td>{balance.stale ? "הערכה ישנה" : "עדכנית"}</td></tr>)}</tbody></table></div>
            <div className={styles.revisionList}><h5>היסטוריית גרסאות</h5>{revisions.map((revision) => <div className={styles.revisionRow} key={revision.revision_id}>
              <button type="button" className={revision.revision_id === selectedRevisionId ? styles.revisionCurrent : ""} onClick={() => setSelectedRevisionId(revision.revision_id)}>גרסה {revision.revision_number} · {revision.origin === "csv" ? "CSV" : revision.origin === "restored" ? "שוחזרה" : "ידנית"}</button>
              <span>{revision.created_at?.slice(0, 10) ?? revision.snapshot_date}</span>
              {revision.revision_number < selectedSnapshot.current_revision_number && <button type="button" disabled={saving || needsReconcile || selectedSnapshot.archived} onClick={() => void restoreRevision(revision)}>שחזור כגרסה חדשה</button>}
            </div>)}</div>
          </>}
        </div>}
      </div>}

      {composer && <form className={styles.formCard} onSubmit={(event) => void saveSnapshot(event)}>
        <div className={styles.formHeading}><h4>{composer === "new" ? "תמונת מצב חדשה" : `גרסה חדשה ל־${captureDate}`}</h4><button type="button" onClick={() => setComposer(null)}>סגירה</button></div>
        {composer === "new" && <Field label="תאריך התמונה"><input required type="date" value={captureDate} onChange={(event) => setCaptureDate(event.target.value)} /></Field>}
        {editorAccounts.length === 0 ? <p className={styles.muted}>אין חשבונות פעילים לתאריך הזה. עדכנו את תאריכי הפעילות ברשימת החשבונות.</p> : <div className={styles.tableWrap}><table><thead><tr><th>חשבון</th><th>יתרה בש״ח</th><th>תאריך הערכת שווי</th><th>הערה</th></tr></thead><tbody>
          {editorAccounts.map((account) => <tr key={account.account_key}><td>{account.display_name}<small>{account.side === "asset" ? "נכס" : "התחייבות"} · {categoryLabels[account.category] ?? account.category}</small></td>
            <td><input className={styles.tableInput} required inputMode="decimal" value={balanceDraft[account.account_key]?.amount_ils ?? ""} onChange={(event) => setBalanceDraft({ ...balanceDraft, [account.account_key]: { ...balanceDraft[account.account_key], amount_ils: event.target.value } })} placeholder="0" aria-label={`יתרה: ${account.display_name}`} /></td>
            <td><input className={styles.tableInput} required type="date" value={balanceDraft[account.account_key]?.valuation_date ?? captureDate} onChange={(event) => setBalanceDraft({ ...balanceDraft, [account.account_key]: { ...balanceDraft[account.account_key], valuation_date: event.target.value } })} aria-label={`תאריך הערכת שווי: ${account.display_name}`} /></td>
            <td><input className={styles.tableInput} maxLength={1000} value={balanceDraft[account.account_key]?.notes ?? ""} onChange={(event) => setBalanceDraft({ ...balanceDraft, [account.account_key]: { ...balanceDraft[account.account_key], notes: event.target.value } })} aria-label={`הערה: ${account.display_name}`} /></td>
          </tr>)}
        </tbody></table></div>}
        <Field label="הערות לתמונה"><textarea rows={2} maxLength={2000} value={snapshotNotes} onChange={(event) => setSnapshotNotes(event.target.value)} /></Field>
        <label className={styles.check}><input type="checkbox" checked={qualityAcknowledged} onChange={(event) => setQualityAcknowledged(event.target.checked)} /> אני מאשר/ת את אזהרות איכות הנתונים והערכת השווי, אם קיימות.</label>
        <div className={styles.formActions}><Button type="submit" disabled={saving || needsReconcile || editorAccounts.length === 0}>{saving ? "שומר…" : composer === "new" ? "שמירת תמונת מצב" : "שמירת גרסה חדשה"}</Button><Button type="button" variant="outline" onClick={() => setComposer(null)}>ביטול</Button></div>
      </form>}
    </section>

    <section className={styles.section} aria-labelledby="csv-heading">
      <div className={styles.sectionHeading}><div><h3 id="csv-heading">ייבוא יתרות מקובץ CSV</h3><p>הייבוא בודק כותרות מדויקות, תאריכים, ערכי ILS וכיסוי חשבונות לפני שמירה.</p></div></div>
      <div className={styles.csvControls}><Field label="תאריך לתבנית"><input type="date" value={captureDate} onChange={(event) => setCaptureDate(event.target.value)} /></Field><Button variant="outline" onClick={() => void downloadTemplate()}>הורדת תבנית CSV</Button></div>
      <div className={styles.csvControls}><Field label="קובץ CSV"><input type="file" accept=".csv,text/csv" onChange={(event) => { setCsvFile(event.target.files?.[0] ?? null); setCsvPreview(null); setActionError(null); }} /></Field><Button onClick={() => void previewCsv()} disabled={!csvFile || saving || needsReconcile}>בדיקת הקובץ</Button></div>
      {csvPreview && <div className={styles.preview}>
        <h4>תוצאת בדיקה · {csvPreview.snapshot_date ?? "תאריך לא תקין"}</h4>
        <p>{csvPreview.row_count} שורות · {csvPreview.valid ? "הקובץ מוכן לייבוא" : "נדרשים תיקונים"}</p>
        {csvPreview.issues.length > 0 && <ul className={styles.issueList}>{csvPreview.issues.map((issue) => <li key={issue}>{issueLabels[issue.split(":")[0]] ?? issue}</li>)}</ul>}
        {csvPreview.warnings.length > 0 && <div className={styles.warning}><strong>אזהרות הערכת שווי</strong><ul>{csvPreview.warnings.map((warning) => <li key={warning}>{warning.replace("STALE_VALUATION:", "הערכת שווי ישנה בחשבון ")}</li>)}</ul></div>}
        {csvPreview.valid && <>
          {csvPreview.existing_snapshot_id && <label className={styles.check}><input type="checkbox" checked={csvCreateRevision} onChange={(event) => setCsvCreateRevision(event.target.checked)} /> שמירה כגרסה חדשה לתאריך שכבר קיים</label>}
          {csvPreview.warnings.length > 0 && <label className={styles.check}><input type="checkbox" checked={csvQualityAcknowledged} onChange={(event) => setCsvQualityAcknowledged(event.target.checked)} /> אני מאשר/ת את אזהרות הערכת השווי</label>}
          <Button onClick={() => void commitCsv()} disabled={saving || needsReconcile || (Boolean(csvPreview.existing_snapshot_id) && !csvCreateRevision) || (csvPreview.warnings.length > 0 && !csvQualityAcknowledged)}>{saving ? "מייבא…" : "שמירת הייבוא"}</Button>
        </>}
      </div>}
    </section>

    <section className={styles.section} aria-labelledby="trend-heading">
      <div className={styles.sectionHeading}><div><h3 id="trend-heading">מגמת הון שנמדד</h3><p>כל נקודה משקפת את הגרסה הנוכחית של תמונת מצב פעילה.</p></div></div>
      {trend.length === 0 ? <EmptyState title="אין עדיין מגמת מדידה" description="שמרו יותר מתמונת מצב אחת כדי לעקוב אחר השינוי לאורך זמן." /> : <div className={styles.tableWrap}><table><thead><tr><th>תאריך</th><th>נכסים</th><th>התחייבויות</th><th>שווי נקי</th><th>נכסים נזילים</th></tr></thead><tbody>{trend.map((point) => <tr key={point.revision_id}><td>{point.snapshot_date}</td><td><bdi>{formatIls(point.total_assets)}</bdi></td><td><bdi>{formatIls(point.total_liabilities)}</bdi></td><td><bdi>{formatIls(point.net_worth)}</bdi></td><td><bdi>{formatIls(point.liquid_assets)}</bdi></td></tr>)}</tbody></table></div>}
    </section>

    <section className={`${styles.section} ${styles.deferred}`} aria-labelledby="forecast-comparison-heading">
      <div><h3 id="forecast-comparison-heading">השוואה לתחזית חיסכון</h3><p>השוואת גרסה מדודה לגרסה ותפקיד בתחזית קיימת תלויה בחוזה הקריאה של מודול התחזית. נקודת הקצה בצד השרת זמינה; בחירת תחזית והצגת ההשוואה יתחברו עם מודול התחזית.</p></div>
      <span className={styles.badge}>ממתין למודול התחזית</span>
    </section>
  </div>;
}

function Metric({ label, value, emphasis = false }: { label: string; value: string; emphasis?: boolean }) {
  return <div className={`${styles.metric}${emphasis ? ` ${styles.metricEmphasis}` : ""}`}><span>{label}</span><strong><bdi>{value}</bdi></strong></div>;
}

function Breakdown({ title, values }: { title: string; values: Record<string, string> }) {
  const rows = Object.entries(values);
  return <div className={styles.breakdown}><h4>{title}</h4>{rows.length === 0 ? <span className={styles.muted}>אין נתונים</span> : rows.map(([key, value]) => <div key={key}><span>{categoryLabels[key] ?? key}</span><bdi>{formatIls(value)}</bdi></div>)}</div>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className={styles.field}><span>{label}</span>{children}</label>;
}
