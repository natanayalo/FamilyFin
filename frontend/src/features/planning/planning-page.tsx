"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiRequestError } from "@/lib/api";
import { ErrorState, LoadingState } from "@/components/ui/async-state";
import {
  setArchived as archiveScenario,
  cloneScenario,
  commitCsvSeed,
  commitHistorySeed,
  compareActual,
  compareScenarios,
  createScenario,
  getCategories,
  getProjection,
  getRevisions,
  getScenario,
  getScenarios,
  getSuggestedStartMonth,
  postProjection,
  previewCsvSeed,
  previewHistorySeed,
  restoreRevision,
  saveRevision,
} from "./api";
import type {
  ActualPlanComparison,
  MonthlyPlan,
  PlanningFrequency,
  PlanningItem,
  PlanningKind,
  PlanningProjection,
  PlanningRevision,
  PlanningScenario,
  PlanningSeedPreview,
  ScenarioComparison,
} from "./types";
import styles from "./planning.module.css";

type ErrorInfo = { message: string; requestId?: string; fields?: Record<string, string[]> };
type EditorMode = "create" | "edit";
type EditorStep = 1 | 2 | 3;
type ScenarioDraft = { name: string; currency: string; start_month: string };

const kindLabels: Record<PlanningKind, string> = {
  income: "הכנסה",
  expense: "הוצאה",
  savings_contribution: "חיסכון או העברה לחיסכון",
  savings_withdrawal: "משיכה או העברה מחיסכון",
};
const frequencyLabels: Record<PlanningFrequency, string> = { monthly: "חודשי", one_time: "חד־פעמי" };
const kindOptions: PlanningKind[] = ["income", "expense", "savings_contribution", "savings_withdrawal"];
const frequencyOptions: PlanningFrequency[] = ["monthly", "one_time"];

function todayMonth() {
  const today = new Date();
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
}

function addMonths(month: string, count: number) {
  const [yearText, monthText] = month.split("-");
  const target = new Date(Date.UTC(Number(yearText), Number(monthText) - 1 + count, 1));
  return `${target.getUTCFullYear()}-${String(target.getUTCMonth() + 1).padStart(2, "0")}-01`;
}

function monthDate(value: string) {
  return value.length === 7 ? `${value}-01` : value;
}

function emptyItem(startMonth: string, endMonth: string): PlanningItem {
  return {
    id: "", kind: "expense", label: "", category: null, amount: "", frequency: "monthly",
    start_month: monthDate(startMonth), end_month: monthDate(endMonth), occurrence_month: null,
    origin: "manual", source_range: null, source_row: null, policy_version: "planning-v1",
    completeness_codes: [], contributor_transaction_ids: [], provenance: {}, notes: [],
  };
}

function formatMoney(value: string | null | undefined, currency: string) {
  if (value == null) return "לא זמין";
  if (value === "") return "לא הוזן";
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [whole, fraction] = unsigned.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "−" : ""}${grouped}${fraction ? `.${fraction}` : ""} ${currency}`;
}

function humanMonth(value: string) {
  return value.slice(0, 7);
}

function issueText(error: unknown, fallback: string): ErrorInfo {
  if (!(error instanceof ApiRequestError)) return { message: fallback };
  const apiError = error.apiError;
  if (apiError?.code === "STALE_REVISION") {
    const revision = apiError.fields?.current_revision_number?.[0];
    return {
      message: revision
        ? `נשמרה גרסה ${revision} בזמן שהטיוטה הייתה פתוחה. הטיוטה נשארה ללא שינוי; טענו את הגרסה העדכנית לפני שמירה.`
        : "התרחיש השתנה בזמן שהטיוטה הייתה פתוחה. טענו את הגרסה העדכנית לפני שמירה.",
      requestId: apiError.request_id,
      fields: apiError.fields,
    };
  }
  if (apiError?.code === "QUALITY_ACKNOWLEDGEMENT_REQUIRED") {
    return { message: "יש לעיין באזהרות ובנתוני המקור ולאשר במפורש לפני ההמשך.", requestId: apiError.request_id, fields: apiError.fields };
  }
  if (apiError?.code === "DUPLICATE_SEED") {
    return { message: "הקובץ הזה כבר יצר תרחיש. פתחו אותו או שכפלו אותו כדי להתחיל תרחיש נוסף.", requestId: apiError.request_id, fields: apiError.fields };
  }
  if (apiError?.code === "PREVIEW_STALE") {
    return { message: "המקור או הנתונים השתנו מאז התצוגה המקדימה. צרו תצוגה מקדימה חדשה.", requestId: apiError.request_id };
  }
  if (error.status === 0 || error.status >= 500) {
    return { message: "לא ידוע אם הפעולה נשמרה. רעננו את התרחישים לפני ניסיון נוסף.", requestId: apiError?.request_id };
  }
  if (error.status === 422) {
    return { message: apiError?.message || "בדקו את הסכומים, תאריכי החודשים והבחירות בכל השדות.", requestId: apiError?.request_id, fields: apiError?.fields };
  }
  return { message: apiError?.message || fallback, requestId: apiError?.request_id, fields: apiError?.fields };
}

function emptyStateError(error: unknown) {
  return issueText(error, "לא ניתן לטעון את נתוני התכנון.").message;
}

function PlanError({ error }: { error: ErrorInfo | null }) {
  if (!error) return null;
  const fieldErrors = Object.entries(error.fields ?? {}).flatMap(([key, values]) => values.map((value) => `${key}: ${value}`));
  return <div className={styles.error} role="alert">
    <strong>{error.message}</strong>
    {fieldErrors.length > 0 && <ul>{fieldErrors.map((value) => <li key={value}>{value}</li>)}</ul>}
    {error.requestId && <small>מזהה פנייה: {error.requestId}</small>}
  </div>;
}

function MonthProjection({ month, currency }: { month: MonthlyPlan; currency: string }) {
  const values: Array<[string, string]> = [
    ["הכנסות", month.income], ["הוצאות", month.expenses], ["עודף תפעולי", month.operating_surplus],
    ["הפקדות לחיסכון", month.savings_contributions], ["משיכות מחיסכון", month.savings_withdrawals],
    ["נותר אחרי חיסכון", month.cash_remaining_after_savings],
  ];
  return <article className={styles.monthCard}>
    <h4>{humanMonth(month.month)}</h4>
    <div className={styles.monthValues}>{values.map(([label, amount]) => <div className={styles.monthValue} key={label}><span>{label}</span><bdi dir="ltr">{formatMoney(amount, currency)}</bdi></div>)}</div>
  </article>;
}

export function PlanningPage() {
  const [scenarios, setScenarios] = useState<PlanningScenario[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [scenario, setScenario] = useState<PlanningScenario | null>(null);
  const [revisions, setRevisions] = useState<PlanningRevision[]>([]);
  const [revision, setRevision] = useState<PlanningRevision | null>(null);
  const [projection, setProjection] = useState<PlanningProjection | null>(null);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pageError, setPageError] = useState<ErrorInfo | null>(null);
  const [actionError, setActionError] = useState<ErrorInfo | null>(null);
  const [notice, setNotice] = useState("");
  const selectedRef = useRef("");

  const [editorMode, setEditorMode] = useState<EditorMode | null>(null);
  const [editorStep, setEditorStep] = useState<EditorStep>(1);
  const [editorItems, setEditorItems] = useState<PlanningItem[]>([]);
  const [editorNotes, setEditorNotes] = useState("");
  const [scenarioDraft, setScenarioDraft] = useState<ScenarioDraft>({ name: "תרחיש משפחתי", currency: "ILS", start_month: todayMonth() });
  const [provisionalAcknowledged, setProvisionalAcknowledged] = useState(false);
  const [editorStale, setEditorStale] = useState(false);
  const [editorOutcomeUnknown, setEditorOutcomeUnknown] = useState(false);
  const [draftProjection, setDraftProjection] = useState<PlanningProjection | null>(null);
  const [draftProjectionLoading, setDraftProjectionLoading] = useState(false);
  const [validationMessage, setValidationMessage] = useState("");

  const [historyName, setHistoryName] = useState("בסיס היסטורי");
  const [historyCurrency, setHistoryCurrency] = useState("ILS");
  const [historyStart, setHistoryStart] = useState(todayMonth());
  const [historyMonths, setHistoryMonths] = useState("6");
  const [historyPreview, setHistoryPreview] = useState<PlanningSeedPreview | null>(null);
  const [historyAcknowledged, setHistoryAcknowledged] = useState(false);

  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvName, setCsvName] = useState("תקציב מיובא");
  const [csvCurrency, setCsvCurrency] = useState("ILS");
  const [csvStart, setCsvStart] = useState(todayMonth());
  const [csvPreview, setCsvPreview] = useState<PlanningSeedPreview | null>(null);
  const [csvCategories, setCsvCategories] = useState<string[]>([]);
  const [csvMappings, setCsvMappings] = useState<Record<string, string>>({});
  const [csvAcknowledged, setCsvAcknowledged] = useState(false);

  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<ScenarioComparison | null>(null);
  const [actual, setActual] = useState<ActualPlanComparison | null>(null);
  const [selectedHistoryRevision, setSelectedHistoryRevision] = useState<PlanningRevision | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<PlanningRevision | null>(null);
  const [restoreAcknowledged, setRestoreAcknowledged] = useState(false);
  const [cloneAcknowledged, setCloneAcknowledged] = useState(false);

  const activeScenario = scenarios.find((item) => item.scenario_id === selectedId) ?? scenario;
  const provisionalNeedsAck = Boolean(revision?.provisional && !provisionalAcknowledged);
  const csvNeedsAck = Boolean(csvPreview && (csvPreview.provisional || Object.values(csvMappings).some((value) => !value)));
  const sameCurrencyScenarios = scenarios.filter((item) => !activeScenario || item.currency === activeScenario.currency);

  const loadData = useCallback(async (preferredId?: string) => {
    setLoading(true);
    setPageError(null);
    try {
      const nextScenarios = (await getScenarios(true)).data;
      setScenarios(nextScenarios);
      const wantedId = preferredId ?? selectedRef.current;
      const chosen = nextScenarios.find((item) => item.scenario_id === wantedId)
        ?? nextScenarios.find((item) => !item.archived)
        ?? nextScenarios[0]
        ?? null;
      const id = chosen?.scenario_id ?? "";
      selectedRef.current = id;
      setSelectedId(id);
      setScenario(chosen);
      setActual(null);
      setComparison(null);
      setSelectedHistoryRevision(null);
      setRestoreTarget(null);
      if (chosen) {
        const [nextRevisions, nextProjection, current] = await Promise.all([
          getRevisions(id),
          getProjection(id),
          getScenario(id),
        ]);
        const currentRevision = nextRevisions.data.find((item) => item.revision_number === current.data.current_revision_number)
          ?? nextRevisions.data.at(-1) ?? null;
        setScenario(current.data);
        setRevisions(nextRevisions.data);
        setRevision(currentRevision);
        setProjection(nextProjection.data);
        if (!compareIds.includes(id) && compareIds.length === 0) setCompareIds([id]);
      } else {
        setRevisions([]);
        setRevision(null);
        setProjection(null);
      }
      setLoaded(true);
    } catch (error) {
      setPageError({ message: emptyStateError(error), requestId: error instanceof ApiRequestError ? error.apiError?.request_id : undefined });
    } finally {
      setLoading(false);
    }
  }, [compareIds]);

  useEffect(() => { void loadData(); }, [loadData]);

  function selectScenario(id: string) {
    selectedRef.current = id;
    setSelectedId(id);
    setActionError(null);
    setNotice("");
    setSelectedHistoryRevision(null);
    setRestoreTarget(null);
    void loadData(id);
  }

  async function startCreate() {
    setPageError(null);
    setActionError(null);
    setNotice("");
    let start = todayMonth();
    try { start = (await getSuggestedStartMonth("ILS")).data.slice(0, 7); } catch { /* the service month is a useful local fallback */ }
    setScenarioDraft({ name: "תרחיש משפחתי", currency: "ILS", start_month: start });
    setEditorItems([emptyItem(start, addMonths(start, 11))]);
    setEditorNotes("");
    setEditorMode("create");
    setEditorStep(1);
    setEditorStale(false);
    setEditorOutcomeUnknown(false);
    setProvisionalAcknowledged(false);
    setDraftProjection(null);
    setValidationMessage("");
  }

  function startEdit() {
    if (!revision || !scenario) return;
    setEditorMode("edit");
    setEditorStep(1);
    setEditorItems(revision.items.map((item) => ({ ...item, provenance: { ...item.provenance }, notes: [...item.notes] })));
    setEditorNotes(revision.notes);
    setScenarioDraft({ name: scenario.name, currency: scenario.currency, start_month: scenario.start_month.slice(0, 7) });
    setProvisionalAcknowledged(false);
    setEditorStale(false);
    setEditorOutcomeUnknown(false);
    setDraftProjection(null);
    setValidationMessage("");
    setActionError(null);
    setNotice("");
  }

  function discardEditor() {
    setEditorMode(null);
    setEditorItems([]);
    setEditorStep(1);
    setDraftProjection(null);
    setValidationMessage("");
    setActionError(null);
    setEditorStale(false);
    setEditorOutcomeUnknown(false);
  }

  function updateItem(index: number, changes: Partial<PlanningItem>) {
    setEditorItems((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, ...changes } : item));
    setDraftProjection(null);
  }

  function updateFrequency(index: number, frequency: PlanningFrequency) {
    const start = editorMode === "edit" ? scenario?.start_month ?? monthDate(scenarioDraft.start_month) : monthDate(scenarioDraft.start_month);
    const end = editorMode === "edit" ? scenario?.end_month ?? addMonths(scenarioDraft.start_month, 11) : addMonths(scenarioDraft.start_month, 11);
    const item = editorItems[index];
    if (frequency === "monthly") {
      updateItem(index, { frequency, start_month: item.start_month ?? start, end_month: item.end_month ?? end, occurrence_month: null });
    } else {
      updateItem(index, { frequency, start_month: null, end_month: null, occurrence_month: item.occurrence_month ?? start });
    }
  }

  function validateStepOne() {
    if (editorMode === "create") {
      if (!scenarioDraft.name.trim()) return "הוסיפו שם לתרחיש.";
      if (!/^[A-Za-z]{3,12}$/.test(scenarioDraft.currency.trim())) return "קוד המטבע צריך להכיל 3–12 אותיות, למשל ILS או USD.";
      if (!/^\d{4}-\d{2}$/.test(scenarioDraft.start_month)) return "בחרו חודש התחלה תקין.";
    }
    if (editorItems.length === 0) return "הוסיפו לפחות הנחה אחת לתרחיש.";
    for (const [index, item] of editorItems.entries()) {
      if (!item.label.trim()) return `הוסיפו שם להנחה ${index + 1}.`;
      if (!/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(item.amount)) return `הסכום בהנחה ${index + 1} חייב להיות מספר עשרוני לא שלילי.`;
    }
    return "";
  }

  function validateStepTwo() {
    const start = editorMode === "edit" ? scenario?.start_month ?? "" : monthDate(scenarioDraft.start_month);
    const end = editorMode === "edit" ? scenario?.end_month ?? "" : addMonths(scenarioDraft.start_month, 11);
    for (const [index, item] of editorItems.entries()) {
      if (item.frequency === "monthly") {
        if (!item.start_month || !item.end_month) return `בחרו טווח חודשים חודשי להנחה ${index + 1}.`;
        if (item.start_month > item.end_month || item.start_month < start || item.end_month > end) return `טווח החודשים בהנחה ${index + 1} צריך להיכלל ב־12 חודשי התרחיש.`;
      } else if (!item.occurrence_month || item.occurrence_month < start || item.occurrence_month > end) {
        return `החודש של ההנחה החד־פעמית ${index + 1} צריך להיכלל בתרחיש.`;
      }
    }
    return "";
  }

  async function advanceStep() {
    setValidationMessage("");
    setActionError(null);
    if (editorStep === 1) {
      const issue = validateStepOne();
      if (issue) { setValidationMessage(issue); return; }
      setEditorStep(2);
      return;
    }
    if (editorStep === 2) {
      const issue = validateStepTwo();
      if (issue) { setValidationMessage(issue); return; }
      setEditorStep(3);
      if (editorMode === "edit" && scenario && revision) {
        setDraftProjectionLoading(true);
        try {
          const result = await postProjection(scenario.scenario_id, revision.revision_number, editorItems);
          setDraftProjection(result.data);
        } catch (error) {
          setActionError(issueText(error, "לא ניתן לחשב את טיוטת התרחיש."));
        } finally {
          setDraftProjectionLoading(false);
        }
      }
    }
  }

  async function saveEditor() {
    if (editorStale) return;
    setSaving(true);
    setActionError(null);
    setNotice("");
    try {
      if (editorMode === "create") {
        const result = await createScenario({
          name: scenarioDraft.name.trim(), currency: scenarioDraft.currency.trim().toUpperCase(),
          start_month: monthDate(scenarioDraft.start_month), items: editorItems, notes: editorNotes,
        });
        setNotice("התרחיש נוצר.");
        setEditorMode(null);
        await loadData(result.data.scenario_id);
      } else if (scenario && revision) {
        if (revision.provisional && !provisionalAcknowledged) {
          setActionError({ message: "יש לאשר שעיינתם במצב הזמני ובמקורות לפני השמירה." });
          return;
        }
        await saveRevision(scenario.scenario_id, {
          expected_revision_number: revision.revision_number,
          items: editorItems,
          notes: editorNotes,
          acknowledge_provisional: provisionalAcknowledged,
        });
        setNotice("הגרסה נשמרה ונוספה להיסטוריה.");
        setEditorMode(null);
        await loadData(scenario.scenario_id);
      }
    } catch (error) {
      const parsed = issueText(error, "לא ניתן לשמור את התרחיש.");
      setActionError(parsed);
      if (error instanceof ApiRequestError && error.apiError?.code === "STALE_REVISION" && scenario) {
        setEditorStale(true);
        await loadData(scenario.scenario_id);
      } else if (error instanceof ApiRequestError && (error.status === 0 || error.status >= 500)) {
        setEditorOutcomeUnknown(true);
        await loadData(scenario?.scenario_id);
      }
    } finally {
      setSaving(false);
    }
  }

  async function doHistoryPreview(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setActionError(null); setNotice(""); setHistoryPreview(null); setHistoryAcknowledged(false); setSaving(true);
    try {
      const result = await previewHistorySeed({ name: historyName.trim(), currency: historyCurrency.trim().toUpperCase(), start_month: monthDate(historyStart), history_months: Number(historyMonths) });
      setHistoryPreview(result.data);
    } catch (error) { setActionError(issueText(error, "לא ניתן ליצור תצוגה מקדימה של ההיסטוריה.")); }
    finally { setSaving(false); }
  }

  async function doHistoryCommit() {
    if (!historyPreview) return;
    setSaving(true); setActionError(null); setNotice("");
    try {
      const result = await commitHistorySeed(historyPreview.preview_token, historyAcknowledged);
      setHistoryPreview(null); setNotice("התרחיש ההיסטורי נשמר."); await loadData(result.data.scenario_id);
    } catch (error) {
      setActionError(issueText(error, "לא ניתן לשמור את התרחיש ההיסטורי."));
      if (error instanceof ApiRequestError && (error.status === 0 || error.status >= 500)) {
        setHistoryPreview(null);
        setHistoryAcknowledged(false);
        await loadData();
      }
    } finally { setSaving(false); }
  }

  async function doCsvPreview(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!csvFile) { setActionError({ message: "בחרו קובץ CSV לפני יצירת התצוגה המקדימה." }); return; }
    setActionError(null); setNotice(""); setCsvPreview(null); setCsvMappings({}); setCsvAcknowledged(false); setSaving(true);
    try {
      const result = await previewCsvSeed(csvFile, { name: csvName.trim(), currency: csvCurrency.trim().toUpperCase(), start_month: monthDate(csvStart) });
      setCsvPreview(result.data);
      const categories = (await getCategories(result.data.currency)).data;
      setCsvCategories(categories);
      setCsvMappings(Object.fromEntries(result.data.mappings.map((mapping) => [mapping.csv_category, ""])));
    } catch (error) { setActionError(issueText(error, "לא ניתן לקרוא את קובץ התכנון.")); }
    finally { setSaving(false); }
  }

  async function doCsvCommit() {
    if (!csvFile || !csvPreview) return;
    const mappings = csvPreview.mappings.map((item) => ({ csv_category: item.csv_category, analysis_category: csvMappings[item.csv_category] || null }));
    if (mappings.some((item) => !item.analysis_category) && !csvAcknowledged) {
      setActionError({ message: "אשרו במפורש את הקטגוריות שנותרו ללא מיפוי לפני השמירה." }); return;
    }
    if ((csvPreview.provisional || mappings.some((item) => !item.analysis_category)) && !csvAcknowledged) {
      setActionError({ message: "עיינו באזהרות ובמקור הזמני ואשרו לפני השמירה." }); return;
    }
    setSaving(true); setActionError(null); setNotice("");
    try {
      const result = await commitCsvSeed(csvFile, { previewToken: csvPreview.preview_token, mappings, acknowledgeProvisional: csvAcknowledged });
      setCsvPreview(null); setCsvFile(null); setNotice("תרחיש ה־CSV נשמר."); await loadData(result.data.scenario_id);
    } catch (error) {
      setActionError(issueText(error, "לא ניתן לשמור את תרחיש ה־CSV."));
      if (error instanceof ApiRequestError && (error.status === 0 || error.status >= 500)) {
        setCsvPreview(null);
        setCsvAcknowledged(false);
        await loadData();
      }
    } finally { setSaving(false); }
  }

  async function doClone() {
    if (!scenario) return;
    if (revision?.provisional && !cloneAcknowledged) { setActionError({ message: "עיינו באזהרת המקור ואשרו אותה לפני שכפול התרחיש." }); return; }
    setSaving(true); setActionError(null); setNotice("");
    try {
      const result = await cloneScenario(scenario.scenario_id, { acknowledge_provisional: cloneAcknowledged });
      setCloneAcknowledged(false); setNotice("נוצר עותק עצמאי של התרחיש."); await loadData(result.data.scenario_id);
    } catch (error) { setActionError(issueText(error, "לא ניתן לשכפל את התרחיש.")); }
    finally { setSaving(false); }
  }

  async function toggleArchive() {
    if (!scenario) return;
    setSaving(true); setActionError(null); setNotice("");
    try {
      await archiveScenario(scenario.scenario_id, !scenario.archived);
      setNotice(scenario.archived ? "התרחיש הוחזר לרשימה הפעילה." : "התרחיש הועבר לארכיון.");
      await loadData(scenario.scenario_id);
    } catch (error) { setActionError(issueText(error, "לא ניתן לעדכן את מצב התרחיש.")); }
    finally { setSaving(false); }
  }

  async function doCompare() {
    if (compareIds.length < 2 || compareIds.length > 4) return;
    setSaving(true); setActionError(null); setComparison(null);
    try { setComparison((await compareScenarios(compareIds)).data); }
    catch (error) { setActionError(issueText(error, "לא ניתן להשוות בין התרחישים שנבחרו.")); }
    finally { setSaving(false); }
  }

  async function doActualCompare() {
    if (!scenario) return;
    setSaving(true); setActionError(null); setActual(null);
    try { setActual((await compareActual(scenario.scenario_id)).data); }
    catch (error) { setActionError(issueText(error, "לא ניתן לטעון את ההשוואה לביצוע.")); }
    finally { setSaving(false); }
  }

  async function doRestore() {
    if (!scenario || !revision || !restoreTarget) return;
    const needsAck = revision.provisional || restoreTarget.provisional;
    if (needsAck && !restoreAcknowledged) { setActionError({ message: "עיינו באזהרה הזמנית ואשרו לפני שחזור הגרסה." }); return; }
    setSaving(true); setActionError(null); setNotice("");
    try {
      await restoreRevision(scenario.scenario_id, restoreTarget.revision_number, {
        expected_revision_number: revision.revision_number,
        acknowledge_provisional: restoreAcknowledged,
        notes: `Restored revision ${restoreTarget.revision_number}`,
      });
      setRestoreTarget(null); setRestoreAcknowledged(false); setNotice("הגרסה שוחזרה כגרסה חדשה. ההיסטוריה הקודמת נשמרה."); await loadData(scenario.scenario_id);
    } catch (error) {
      setActionError(issueText(error, "לא ניתן לשחזר את הגרסה."));
      if (error instanceof ApiRequestError && error.apiError?.code === "STALE_REVISION") await loadData(scenario.scenario_id);
    } finally { setSaving(false); }
  }

  if (loading && !loaded) return <LoadingState label="טוענים את תרחישי התכנון…" />;
  if (pageError && !loaded) return <ErrorState title="לא ניתן לטעון תכנון" description={pageError.message} requestId={pageError.requestId} onRetry={() => { void loadData(); }} retrying={loading} />;

  return <div className={styles.page}>
    <div className={styles.toolbar}>
      <div><div className="eyebrow">תכנון משפחתי · הנחות ל־12 חודשים</div><h2>תרחישים ותקציב</h2><p>הנחות נשמרות בגרסאות. חישובי החודשים מבוצעים בשירות התכנון.</p></div>
      <div className={styles.actions}>
        <button className={styles.button} onClick={() => void startCreate()}>תרחיש חדש</button>
      </div>
    </div>

    {notice && <div className={styles.notice} role="status">{notice}</div>}
    {pageError && <PlanError error={pageError} />}
    <PlanError error={actionError} />

    {editorMode && <section className={styles.section} aria-labelledby="planning-editor-title">
      <div className={styles.sectionHeading}><div><h3 id="planning-editor-title">{editorMode === "create" ? "יצירת תרחיש" : "עריכת טיוטת גרסה"}</h3><p>{editorMode === "edit" ? `הטיוטה מבוססת על גרסה ${revision?.revision_number ?? "—"}. השמירה תיצור גרסה בלתי־ניתנת לשינוי.` : "הוסיפו הנחות, בדקו את הסקירה ושמרו את התרחיש."}</p></div>
        <button className={styles.subtleButton} onClick={discardEditor} disabled={saving}>ביטול וזריקת טיוטה</button></div>
      <div className={styles.steps} aria-label="שלבי העריכה">
        {["הנחות", "תזמון", "סקירה ושמירה"].map((label, index) => <div key={label} className={`${styles.step} ${editorStep === index + 1 ? styles.stepActive : ""}`} aria-current={editorStep === index + 1 ? "step" : undefined}><b>{index + 1}</b><span>{label}</span></div>)}
      </div>
      {validationMessage && <div className={styles.error} role="alert">{validationMessage}</div>}
      {editorStep === 1 && <div className={styles.stepBody}>
        {editorMode === "create" && <div className={styles.fieldGrid}>
          <label className={styles.field}>שם התרחיש<input value={scenarioDraft.name} onChange={(event) => setScenarioDraft({ ...scenarioDraft, name: event.target.value })} maxLength={200} /></label>
          <label className={styles.field}>מטבע<input value={scenarioDraft.currency} onChange={(event) => setScenarioDraft({ ...scenarioDraft, currency: event.target.value.toUpperCase() })} maxLength={12} dir="ltr" /></label>
          <label className={styles.field}>חודש התחלה<input type="month" value={scenarioDraft.start_month} onChange={(event) => {
            const start = event.target.value;
            setScenarioDraft({ ...scenarioDraft, start_month: start });
            if (start) setEditorItems((items) => items.map((item) => item.frequency === "monthly" ? { ...item, start_month: monthDate(start), end_month: addMonths(start, 11) } : { ...item, occurrence_month: monthDate(start) }));
          }} /></label>
          <div className={styles.field}><span>אופק התרחיש</span><div className={styles.fieldHint}>{scenarioDraft.start_month || "—"} עד {scenarioDraft.start_month ? addMonths(scenarioDraft.start_month, 11).slice(0, 7) : "—"} · 12 חודשים</div></div>
        </div>}
        {editorMode === "edit" && <div className={styles.notice}>תרחיש: {scenario?.name} · {scenario?.currency} · {scenario?.start_month.slice(0, 7)} עד {scenario?.end_month.slice(0, 7)}</div>}
        <div className={styles.sectionHeading}><div><h3>הנחות</h3><p>הסכומים הם ערכים חיוביים. סוג ההנחה קובע כיצד השירות מחשב את היתרה.</p></div><button className={styles.subtleButton} onClick={() => setEditorItems([...editorItems, emptyItem(editorMode === "edit" ? scenario?.start_month ?? monthDate(scenarioDraft.start_month) : monthDate(scenarioDraft.start_month), editorMode === "edit" ? scenario?.end_month ?? addMonths(scenarioDraft.start_month, 11) : addMonths(scenarioDraft.start_month, 11))])}>הוספת הנחה</button></div>
        {editorItems.length === 0 && <div className={styles.empty}>אין עדיין הנחות. אפשר לשמור תרחיש ריק, או להוסיף הכנסה, הוצאה, חיסכון או העברה.</div>}
        <div className={styles.itemList}>{editorItems.map((item, index) => <article className={styles.itemCard} key={item.id || `new-${index}`}>
          <div className={styles.cardTop}><h4>הנחה {index + 1}</h4><button type="button" className={styles.dangerButton} onClick={() => setEditorItems(editorItems.filter((_, itemIndex) => itemIndex !== index))}>הסרה</button></div>
          <div className={styles.fieldGrid}>
            <label className={styles.field}>סוג<select value={item.kind} onChange={(event) => updateItem(index, { kind: event.target.value as PlanningKind })}>{kindOptions.map((kind) => <option key={kind} value={kind}>{kindLabels[kind]}</option>)}</select></label>
            <label className={styles.field}>שם ההנחה<input value={item.label} onChange={(event) => updateItem(index, { label: event.target.value })} maxLength={500} placeholder="למשל: משכורת, שכירות" /></label>
            <label className={styles.field}>קטגוריה<input value={item.category ?? ""} onChange={(event) => updateItem(index, { category: event.target.value || null })} maxLength={200} placeholder="אופציונלי" /></label>
            <label className={styles.field}>סכום במטבע התרחיש<input inputMode="decimal" value={item.amount} onChange={(event) => updateItem(index, { amount: event.target.value })} placeholder="0.00" dir="ltr" /><span className={styles.fieldHint}>הסכום נשמר כמחרוזת עשרונית מדויקת.</span></label>
          </div>
        </article>)}</div>
      </div>}
      {editorStep === 2 && <div className={styles.stepBody}>
        <div className={styles.notice}>קבעו לכל הנחה אם היא חוזרת מדי חודש או מתרחשת פעם אחת. כל תאריך חייב להיות בתוך אופק התרחיש.</div>
        <div className={styles.itemList}>{editorItems.map((item, index) => <article className={styles.itemCard} key={item.id || `new-${index}`}>
          <div className={styles.cardTop}><div><h4>{item.label || `הנחה ${index + 1}`}</h4><div className={styles.itemMeta}><span>{kindLabels[item.kind]}</span><span>{formatMoney(item.amount, scenario?.currency ?? scenarioDraft.currency)}</span></div></div></div>
          <div className={styles.fieldGrid}>
            <label className={styles.field}>תדירות<select value={item.frequency} onChange={(event) => updateFrequency(index, event.target.value as PlanningFrequency)}>{frequencyOptions.map((frequency) => <option value={frequency} key={frequency}>{frequencyLabels[frequency]}</option>)}</select></label>
            {item.frequency === "monthly" ? <>
              <label className={styles.field}>מחודש<input type="month" value={item.start_month?.slice(0, 7) ?? ""} min={(scenario?.start_month ?? monthDate(scenarioDraft.start_month)).slice(0, 7)} max={(scenario?.end_month ?? addMonths(scenarioDraft.start_month, 11)).slice(0, 7)} onChange={(event) => updateItem(index, { start_month: event.target.value ? monthDate(event.target.value) : null })} /></label>
              <label className={styles.field}>עד חודש<input type="month" value={item.end_month?.slice(0, 7) ?? ""} min={(scenario?.start_month ?? monthDate(scenarioDraft.start_month)).slice(0, 7)} max={(scenario?.end_month ?? addMonths(scenarioDraft.start_month, 11)).slice(0, 7)} onChange={(event) => updateItem(index, { end_month: event.target.value ? monthDate(event.target.value) : null })} /></label>
            </> : <label className={styles.field}>חודש ההתרחשות<input type="month" value={item.occurrence_month?.slice(0, 7) ?? ""} min={(scenario?.start_month ?? monthDate(scenarioDraft.start_month)).slice(0, 7)} max={(scenario?.end_month ?? addMonths(scenarioDraft.start_month, 11)).slice(0, 7)} onChange={(event) => updateItem(index, { occurrence_month: event.target.value ? monthDate(event.target.value) : null })} /></label>}
          </div>
        </article>)}</div>
      </div>}
      {editorStep === 3 && <div className={styles.stepBody}>
        <div className={styles.sectionHeading}><div><h3>סקירת הנחות לפני שמירה</h3><p>בדקו את הסוג, התזמון והסכום של כל שורה. הערכים המספריים של הטיוטה מגיעים משירות התכנון.</p></div></div>
        <div className={styles.reviewList}>{editorItems.map((item, index) => <div className={styles.reviewRow} key={item.id || `review-${index}`}><div><strong>{item.label}</strong><small>{kindLabels[item.kind]} · {frequencyLabels[item.frequency]} · {item.frequency === "monthly" ? `${item.start_month?.slice(0, 7)}–${item.end_month?.slice(0, 7)}` : item.occurrence_month?.slice(0, 7)}{item.category ? ` · ${item.category}` : ""}</small></div><bdi dir="ltr">{formatMoney(item.amount, scenario?.currency ?? scenarioDraft.currency)}</bdi></div>)}</div>
        {editorMode === "edit" && <>
          {revision?.provisional && <div className={styles.warning}><strong>הגרסה הנוכחית מבוססת על מקור זמני.</strong><ul>{(revision.issue_codes.length ? revision.issue_codes : ["חלק מחודשי המקור אינם מלאים"]).map((code) => <li key={code}>{code}</li>)}</ul><p>נתוני הכיסוי והשלמות נשמרו בגרסה ויישארו מסומנים כזמניים גם לאחר העריכה.</p><label className={styles.check}><input type="checkbox" checked={provisionalAcknowledged} onChange={(event) => setProvisionalAcknowledged(event.target.checked)} /><span>עיינתי באזהרות ובתיעוד המקור, ואני מאשר/ת לשמור טיוטה המבוססת על מקור זמני.</span></label></div>}
          <div className={styles.sectionHeading}><div><h3>חישוב הטיוטה</h3><p>החישוב מחושב בשרת ומשקף את אותה גרסה זמנית ואת אותה עדות כיסוי.</p></div></div>
          {draftProjectionLoading ? <LoadingState label="מחשבים את הטיוטה בשירות התכנון…" /> : draftProjection ? <div className={styles.monthlyGrid}>{draftProjection.months.map((month) => <MonthProjection key={month.month} month={month} currency={draftProjection.currency} />)}</div> : <div className={styles.muted}>לא ניתן להציג תחזית לטיוטה זו. בדקו את הודעת השגיאה או חזרו לתזמון.</div>}
        </>}
        <label className={styles.field}>הערות לגרסה<textarea value={editorNotes} onChange={(event) => setEditorNotes(event.target.value)} maxLength={2000} placeholder="מה השתנה ולמה?" /></label>
        {editorStale && <div className={styles.error} role="alert">הטיוטה מבוססת על גרסה ישנה ונעולה. הגרסה העדכנית נטענה; השליכו את הטיוטה ופתחו עריכה חדשה כדי לשמור שינויים.</div>}
        {editorOutcomeUnknown && <div className={styles.error} role="alert">תוצאת השמירה אינה ידועה. הטיוטה נעולה ולא תישלח שוב אוטומטית. בדקו את התרחישים והגרסה העדכנית לפני שתפתחו טיוטה חדשה.</div>}
      </div>}
      <div className={styles.stepFooter}>
        <div className={styles.actions}>{editorStep > 1 && <button className={styles.subtleButton} onClick={() => { setEditorStep((step) => (step - 1) as EditorStep); setValidationMessage(""); }}>חזרה</button>}<button className={styles.subtleButton} onClick={discardEditor} disabled={saving}>ביטול</button></div>
        {editorStep < 3 ? <button className={styles.button} onClick={() => void advanceStep()}>המשך</button> : <button className={styles.button} onClick={() => void saveEditor()} disabled={saving || editorStale || editorOutcomeUnknown || provisionalNeedsAck || (editorMode === "edit" && !draftProjection)}>{saving ? "שומרים…" : editorMode === "create" ? "יצירת תרחיש" : "שמירת גרסה"}</button>}
      </div>
    </section>}

    {!editorMode && <>
      <section className={styles.section} aria-labelledby="planning-scenarios-title">
        <div className={styles.sectionHeading}><div><h3 id="planning-scenarios-title">כל התרחישים</h3><p>מטבעות נשארים בהיקפים נפרדים. תרחישים בארכיון נשארים זמינים לשחזור.</p></div><button className={styles.subtleButton} onClick={() => void loadData()} disabled={loading}>רענון</button></div>
        {scenarios.length ? <div className={styles.scenarioList}>{scenarios.map((item) => <div key={item.scenario_id}>
          <button className={`${styles.scenarioCard} ${selectedId === item.scenario_id ? styles.selected : ""}`} onClick={() => selectScenario(item.scenario_id)} aria-pressed={selectedId === item.scenario_id}>
            <div className={styles.scenarioTitle}><strong>{item.name}</strong>{item.archived ? <span>בארכיון</span> : <span>{item.currency}</span>}</div>
            <div className={styles.scenarioMeta}><span>גרסה {item.current_revision_number}</span><span>{item.start_month.slice(0, 7)}–{item.end_month.slice(0, 7)}</span>{item.clone_of_scenario_id && <span>עותק מתרחיש אחר</span>}</div>
          </button>
        </div>)}</div> : <div className={styles.empty}>עדיין אין תרחישים. התחילו בתרחיש ידני או צרו בסיס מהיסטוריה או מקובץ CSV.</div>}
      </section>

      <section className={styles.section} aria-label="יצירת תרחיש ממקור">
        <div className={styles.sectionHeading}><div><h3>יצירה ממקור קיים</h3><p>התצוגה המקדימה אינה שומרת שינויים. בדקו את המקור ואת העדות לפני יצירת התרחיש.</p></div></div>
        <div className={styles.fieldGrid}>
          <details className={styles.itemCard}><summary><strong>בסיס מהיסטוריית עסקאות</strong></summary>
            <form className={styles.stepBody} onSubmit={(event) => void doHistoryPreview(event)}>
              <div className={styles.fieldGrid}>
                <label className={styles.field}>שם התרחיש<input value={historyName} onChange={(event) => setHistoryName(event.target.value)} maxLength={200} required /></label>
                <label className={styles.field}>מטבע<input value={historyCurrency} onChange={(event) => setHistoryCurrency(event.target.value.toUpperCase())} maxLength={12} dir="ltr" /></label>
                <label className={styles.field}>חודש התחלה<input type="month" value={historyStart} onChange={(event) => setHistoryStart(event.target.value)} required /></label>
                <label className={styles.field}>חודשי היסטוריה<input type="number" min="1" max="120" value={historyMonths} onChange={(event) => setHistoryMonths(event.target.value)} required /></label>
              </div>
              <div className={styles.actions}><button className={styles.subtleButton} disabled={saving}>תצוגה מקדימה</button></div>
              {historyPreview && <div className={styles.itemCard}>
                <div className={styles.cardTop}><h4>{historyPreview.scenario_name}</h4><span className={styles.pill}>{historyPreview.currency} · {historyPreview.items.length} הנחות</span></div>
                {historyPreview.provisional && <div className={styles.warning}><strong>חלק מחודשי המקור אינם מלאים.</strong><p>העדות נשמרה לצד הגרסה ותישאר זמינה בהיסטוריה.</p><ul>{historyPreview.issue_codes.map((code) => <li key={code}>{code}</li>)}</ul><label className={styles.check}><input type="checkbox" checked={historyAcknowledged} onChange={(event) => setHistoryAcknowledged(event.target.checked)} /><span>עיינתי באזהרות ובהשלמות החודשיות ואני מאשר/ת לשמור את הבסיס הזמני.</span></label></div>}
                <div className={styles.reviewList}>{historyPreview.items.map((item, index) => <div className={styles.reviewRow} key={`${item.label}-${index}`}><div><strong>{item.label}</strong><small>{kindLabels[item.kind]} · {frequencyLabels[item.frequency]}</small></div><bdi dir="ltr">{formatMoney(item.amount, historyPreview.currency)}</bdi></div>)}</div>
                <div className={styles.historyDetail}><strong>צילום שלמות וכיסוי שנשמר עם התצוגה:</strong><pre>{JSON.stringify(historyPreview.completeness_snapshot, null, 2)}</pre></div>
                <div className={styles.actions}><button className={styles.button} type="button" disabled={saving || (historyPreview.provisional && !historyAcknowledged)} onClick={() => void doHistoryCommit()}>שמירת תרחיש היסטורי</button><button className={styles.subtleButton} type="button" onClick={() => { setHistoryPreview(null); setHistoryAcknowledged(false); }}>ביטול תצוגה</button></div>
              </div>}
            </form>
          </details>
          <details className={styles.itemCard}><summary><strong>ייבוא מקובץ תכנון CSV</strong></summary>
            <form className={styles.stepBody} onSubmit={(event) => void doCsvPreview(event)}>
              <div className={styles.fieldGrid}>
                <label className={styles.field}>שם התרחיש<input value={csvName} onChange={(event) => setCsvName(event.target.value)} maxLength={200} required /></label>
                <label className={styles.field}>מטבע<input value={csvCurrency} onChange={(event) => setCsvCurrency(event.target.value.toUpperCase())} maxLength={12} dir="ltr" /></label>
                <label className={styles.field}>חודש התחלה<input type="month" value={csvStart} onChange={(event) => setCsvStart(event.target.value)} required /></label>
              </div>
              <label className={styles.field}>קובץ תכנון<input className={styles.fileInput} type="file" accept=".csv,text/csv" onChange={(event) => { setCsvFile(event.target.files?.[0] ?? null); setCsvPreview(null); setCsvMappings({}); }} /></label>
              <div className={styles.actions}><button className={styles.subtleButton} disabled={saving || !csvFile}>תצוגה מקדימה</button></div>
              {csvPreview && <div className={styles.itemCard}>
                <div className={styles.cardTop}><h4>{csvPreview.filename ?? csvPreview.scenario_name}</h4><span className={styles.pill}>{csvPreview.expense_target_count} יעדי הוצאה · {csvPreview.recurring_income_count} הכנסות</span></div>
                <div className={styles.historyDetail}><strong>בדיקות בקרה</strong><pre>{JSON.stringify(csvPreview.control_checks, null, 2)}</pre><strong>מקטעים שלא יובאו</strong><pre>{JSON.stringify(csvPreview.ignored_sections, null, 2)}</pre></div>
                {csvPreview.warnings.length > 0 && <div className={styles.warning}><strong>אזהרות המקור</strong><ul>{csvPreview.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
                {csvPreview.duplicate_scenario_id && <div className={styles.notice}>הקובץ כבר מקושר לתרחיש. פתחו אותו מהרשימה או שכפלו אותו במפורש.</div>}
                <div className={styles.itemList}><h4>מיפוי קטגוריות</h4><p className={styles.muted}>בחרו קטגוריה לכל מקור, או בחרו ״ללא מיפוי״. הצעה אינה נשמרת בלי אישור מפורש.</p>
                  {csvPreview.mappings.map((mapping) => <label className={styles.field} key={mapping.csv_category}>{mapping.csv_category}<select value={csvMappings[mapping.csv_category] ?? ""} onChange={(event) => setCsvMappings({ ...csvMappings, [mapping.csv_category]: event.target.value })}><option value="">ללא מיפוי</option>{csvCategories.map((category) => <option key={category} value={category}>{category}</option>)}</select>{mapping.suggested_analysis_categories.length > 0 && <span className={styles.fieldHint}>הצעה לבדיקה: {mapping.suggested_analysis_categories.join(", ")}</span>}</label>)}
                </div>
                {csvPreview.provisional && <div className={styles.warning}><strong>מקור ה־CSV מסומן כזמני.</strong><p>קוד הקובץ נשמר לשם איתור, ואזהרות ואי־מיפויים יישמרו בגרסה.</p><label className={styles.check}><input type="checkbox" checked={csvAcknowledged} onChange={(event) => setCsvAcknowledged(event.target.checked)} /><span>עיינתי בבדיקות ובקטגוריות ואני מאשר/ת להמשיך עם מקור זה.</span></label></div>}
                <div className={styles.actions}><button className={styles.button} type="button" disabled={saving || Boolean(csvPreview.duplicate_scenario_id) || (csvNeedsAck && !csvAcknowledged) || csvPreview.mappings.some((item) => !(item.csv_category in csvMappings))} onClick={() => void doCsvCommit()}>שמירת תרחיש מה־CSV</button><button className={styles.subtleButton} type="button" onClick={() => { setCsvPreview(null); setCsvAcknowledged(false); }}>ביטול תצוגה</button></div>
              </div>}
            </form>
          </details>
        </div>
      </section>

      {scenario && revision && <>
        <section className={styles.section} aria-labelledby="planning-detail-title">
          <div className={styles.sectionHeading}><div><h3 id="planning-detail-title">{scenario.name}</h3><p>{scenario.currency} · {scenario.start_month.slice(0, 7)} עד {scenario.end_month.slice(0, 7)} · גרסה עדכנית {revision.revision_number}</p></div>
            <div className={styles.actions}><button className={styles.subtleButton} onClick={startEdit} disabled={scenario.archived}>עריכת תרחיש</button><button className={styles.subtleButton} onClick={() => void doClone()} disabled={saving}>שכפול</button><button className={scenario.archived ? styles.button : styles.dangerButton} onClick={() => void toggleArchive()} disabled={saving}>{scenario.archived ? "החזרה לארכיון" : "העברה לארכיון"}</button></div></div>
          {revision.provisional && <div className={styles.warning}><strong>הגרסה הזמנית מציגה מקור או כיסוי חלקי.</strong><ul>{(revision.issue_codes.length ? revision.issue_codes : ["PROVISIONAL_SOURCE"]).map((code) => <li key={code}>{code}</li>)}</ul><p>מקור הכיסוי נשמר עם הגרסה ואינו הופך למלא בעקבות עריכה.</p></div>}
          {revision.provisional && <label className={styles.check}><input type="checkbox" checked={cloneAcknowledged} onChange={(event) => setCloneAcknowledged(event.target.checked)} /><span>עיינתי באזהרת המקור ומאשר/ת לשכפל את התרחיש הזמני.</span></label>}
          <div className={styles.metricGrid}>
            <div className={styles.metric}><span>הכנסה חודשית ממוצעת לפי החודש הראשון</span><strong dir="ltr">{formatMoney(projection?.months[0]?.income, scenario.currency)}</strong></div>
            <div className={styles.metric}><span>הוצאות בחודש הראשון</span><strong dir="ltr">{formatMoney(projection?.months[0]?.expenses, scenario.currency)}</strong></div>
            <div className={styles.metric}><span>עודף תפעולי בחודש הראשון</span><strong dir="ltr">{formatMoney(projection?.months[0]?.operating_surplus, scenario.currency)}</strong></div>
            <div className={styles.metric}><span>הנחות פעילות בגרסה</span><strong>{revision.items.length}</strong></div>
          </div>
          <div className={styles.itemList}><h4>הנחות שמורות</h4>{revision.items.length ? revision.items.map((item) => <div className={styles.reviewRow} key={item.id}><div><strong>{item.label}</strong><small>{kindLabels[item.kind]} · {frequencyLabels[item.frequency]} · מקור: {item.origin}{item.category ? ` · ${item.category}` : ""}</small></div><bdi dir="ltr">{formatMoney(item.amount, scenario.currency)}</bdi></div>) : <div className={styles.empty}>הגרסה עדיין אינה כוללת הנחות.</div>}</div>
          {revision.completeness_snapshot.length > 0 && <details className={styles.historyDetail}><summary>עדות שלמות וכיסוי שמורה ({revision.completeness_snapshot.length} חודשים)</summary><pre>{JSON.stringify(revision.completeness_snapshot, null, 2)}</pre></details>}
        </section>

        <section className={styles.section} aria-label="תחזית חודשית">
          <div className={styles.sectionHeading}><div><h3>תכנון חודשי</h3><p>ההכנסות, ההוצאות והחיסכון חושבו על ידי Python על בסיס הגרסה השמורה.</p></div><button className={styles.subtleButton} onClick={() => void loadData(scenario.scenario_id)} disabled={loading}>רענון חישוב</button></div>
          {projection?.provisional && <div className={styles.pill + " " + styles.pillWarn}>תחזית זמנית · {projection.issue_codes.join(", ") || "כיסוי המקור חלקי"}</div>}
          <div className={styles.monthlyGrid}>{projection?.months.map((month) => <MonthProjection key={month.month} month={month} currency={projection.currency} />)}</div>
        </section>

        <section className={styles.section} aria-labelledby="planning-history-title">
          <div className={styles.sectionHeading}><div><h3 id="planning-history-title">היסטוריית גרסאות</h3><p>כל שמירה מוסיפה גרסה. שחזור יוצר גרסה חדשה ואינו משנה את ההיסטוריה הקודמת.</p></div></div>
          <div className={styles.historyList}>{[...revisions].reverse().map((item) => <div key={item.revision_id}>
            <div className={styles.historyRow}><div><strong>גרסה {item.revision_number}{item.revision_number === revision.revision_number ? " · עדכנית" : ""}</strong><small>{item.created_at ?? "תאריך לא זמין"} · {item.items.length} הנחות{item.provisional ? " · זמנית" : ""}</small></div><button className={styles.subtleButton} onClick={() => setSelectedHistoryRevision(item)}>פרטי גרסה</button>{item.revision_number !== revision.revision_number && !scenario.archived && <button className={styles.subtleButton} onClick={() => { setRestoreTarget(item); setRestoreAcknowledged(false); }}>שחזור כגרסה חדשה</button>}</div>
            {selectedHistoryRevision?.revision_id === item.revision_id && <div className={styles.historyDetail}><strong>גרסה {item.revision_number} · {item.notes || "ללא הערות"}</strong><p>מקור זמני: {item.provisional ? "כן" : "לא"}{item.issue_codes.length ? ` · ${item.issue_codes.join(", ")}` : ""}</p>{item.items.map((line) => <div key={line.id}>{line.label} · {kindLabels[line.kind]} · {formatMoney(line.amount, scenario.currency)} · {line.origin}</div>)}{item.completeness_snapshot.length > 0 && <pre>{JSON.stringify(item.completeness_snapshot, null, 2)}</pre>}</div>}
          </div>)}</div>
          {restoreTarget && <div className={styles.itemCard}><div className={styles.sectionHeading}><div><h4>שחזור גרסה {restoreTarget.revision_number}</h4><p>הפעולה תשמור עותק חדש מעל גרסה {revision.revision_number}.</p></div><button className={styles.subtleButton} onClick={() => setRestoreTarget(null)}>ביטול</button></div>{(restoreTarget.provisional || revision.provisional) && <label className={styles.check}><input type="checkbox" checked={restoreAcknowledged} onChange={(event) => setRestoreAcknowledged(event.target.checked)} /><span>עיינתי באזהרות המקור הזמני של הגרסה ואני מאשר/ת לשחזר.</span></label>}<button className={styles.button} onClick={() => void doRestore()} disabled={saving || ((restoreTarget.provisional || revision.provisional) && !restoreAcknowledged)}>שחזור ושמירה כגרסה חדשה</button></div>}
        </section>

        <section className={styles.section} aria-labelledby="planning-comparison-title">
          <div className={styles.sectionHeading}><div><h3 id="planning-comparison-title">השוואת תרחישים</h3><p>אפשר להשוות בין שניים לארבעה תרחישים באותו מטבע. הסיכומים והחודשים מגיעים מהשירות.</p></div><button className={styles.button} onClick={() => void doCompare()} disabled={saving || compareIds.length < 2 || compareIds.length > 4}>השוואת הנבחרים ({compareIds.length})</button></div>
          <div className={styles.compareChecks}>{sameCurrencyScenarios.map((item) => <label className={styles.compareChoice} key={item.scenario_id}><input type="checkbox" checked={compareIds.includes(item.scenario_id)} disabled={!compareIds.includes(item.scenario_id) && compareIds.length >= 4} onChange={(event) => { setComparison(null); setCompareIds((ids) => event.target.checked ? [...ids, item.scenario_id] : ids.filter((id) => id !== item.scenario_id)); }} /><span>{item.name}<small className={styles.muted}> · {item.current_revision_number} גרסאות{item.archived ? " · ארכיון" : ""}</small></span></label>)}</div>
          {comparison && <div className={styles.comparisonList}>{comparison.months.map((month, monthIndex) => <article className={styles.compareMonth} key={month}><h4>{humanMonth(month)}</h4>{comparison.scenarios.map((series) => { const plan = series.months[monthIndex]; return <div className={styles.compareScenario} key={series.scenario_id}><strong>{series.name}</strong>{plan ? <div className={styles.compareAmounts}><span>הכנסה <bdi dir="ltr">{formatMoney(plan.income, comparison.currency)}</bdi></span><span>הוצאות <bdi dir="ltr">{formatMoney(plan.expenses, comparison.currency)}</bdi></span><span>עודף <bdi dir="ltr">{formatMoney(plan.operating_surplus, comparison.currency)}</bdi></span><span>חיסכון נטו <bdi dir="ltr">{formatMoney(plan.net_planned_savings, comparison.currency)}</bdi></span></div> : <span className={styles.muted}>אין תכנון בחודש זה</span>}</div>; })}</article>)}</div>}
        </section>

        <section className={styles.section} aria-label="השוואה לביצוע">
          <div className={styles.sectionHeading}><div><h3>תכנון מול ביצוע</h3><p>בחודשים עם כיסוי או סיווג לא מלא, סטיות נשארות לא זמינות במקום להיחשב כאפס.</p></div><button className={styles.subtleButton} onClick={() => void doActualCompare()} disabled={saving}>טעינת השוואה לביצוע</button></div>
          {actual && <div className={styles.monthlyGrid}>{actual.months.map((month) => <article className={styles.monthCard} key={month.month}><h4>{humanMonth(month.month)} · {month.complete ? "נתוני ביצוע מלאים" : "ביצוע חלקי / לא ידוע"}</h4><div className={styles.monthValues}><div className={styles.monthValue}><span>הכנסה בפועל</span><bdi dir="ltr">{formatMoney(month.actual_income, actual.currency)}</bdi></div><div className={styles.monthValue}><span>הוצאות בפועל</span><bdi dir="ltr">{formatMoney(month.actual_expenses, actual.currency)}</bdi></div><div className={styles.monthValue}><span>סטיית הכנסה</span><bdi dir="ltr">{formatMoney(month.income_variance, actual.currency)}</bdi></div><div className={styles.monthValue}><span>סטיית עודף</span><bdi dir="ltr">{formatMoney(month.surplus_variance, actual.currency)}</bdi></div></div>{month.issue_codes.length > 0 && <small className={styles.muted}>{month.issue_codes.join(", ")}</small>}</article>)}</div>}
        </section>
      </>}
    </>}
  </div>;
}
