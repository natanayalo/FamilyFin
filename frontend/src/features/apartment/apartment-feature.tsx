"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { ApiRequestError } from "@/lib/api";
import { getForecastRevisions, getForecasts } from "@/features/forecasts/api";
import type { ForecastRevisionSummary, ForecastRole, ForecastSummary } from "@/features/forecasts/types";
import {
  cloneApartmentStudy,
  createApartmentStudy,
  getApartmentOptions,
  getApartmentPoolBalances,
  getApartmentRevisionProjection,
  getApartmentRevisions,
  getApartmentStudies,
  previewApartment,
  restoreApartmentRevision,
  saveApartmentRevision,
  setApartmentArchived,
} from "./api";
import type {
  ApartmentAlternative,
  ApartmentDraft,
  ApartmentInput,
  ApartmentRevision,
  ApartmentSnapshot,
  ApartmentStudy,
  ApartmentSourceOptions,
} from "./types";
import { emptyAlternative, emptyGuardrails } from "./types";
import { readUnknownApartmentMutation, storeUnknownApartmentMutation, type UnknownApartmentMutation } from "./unknown-mutation";
import styles from "./apartment.module.css";

const roles: ForecastRole[] = ["conservative", "baseline", "optimistic"];
const roleLabel: Record<ForecastRole, string> = { conservative: "שמרני", baseline: "בסיסי", optimistic: "אופטימי" };

type Editor = {
  alternatives: ApartmentAlternative[];
  guardrails: ApartmentInput["guardrails"];
  notes: string;
  sourceQualityAcknowledged: boolean;
};

function makeEditor(snapshot?: ApartmentSnapshot, poolNames: string[] = []): Editor {
  if (snapshot) {
    return {
      alternatives: snapshot.alternatives.map((item) => ({ ...item, confirmed: false })),
      guardrails: { ...snapshot.guardrails },
      notes: snapshot.notes,
      sourceQualityAcknowledged: snapshot.source_quality_acknowledged,
    };
  }
  return {
    alternatives: [emptyAlternative(0, poolNames), emptyAlternative(1, poolNames)],
    guardrails: emptyGuardrails(),
    notes: "",
    sourceQualityAcknowledged: false,
  };
}

function decimalToPercent(value: string | null | undefined) {
  if (!value) return "";
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [whole = "0", fraction = ""] = unsigned.split(".");
  const digits = `${whole || "0"}${fraction}`;
  const decimalIndex = (whole || "0").length + 2;
  const shifted = decimalIndex >= digits.length
    ? `${digits}${"0".repeat(decimalIndex - digits.length)}`
    : `${digits.slice(0, decimalIndex)}.${digits.slice(decimalIndex)}`;
  const [integer, decimal] = shifted.split(".");
  const normalized = `${integer.replace(/^0+(?=\d)/, "")}${decimal === undefined ? "" : `.${decimal}`}`
    .replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
  return `${negative && normalized !== "0" ? "-" : ""}${normalized}`;
}

function percentToDecimal(value: string) {
  const clean = value.trim().replace(/%$/, "").trim();
  if (!clean) return "0";
  if (!/^-?(?:\d+(?:\.\d*)?|\.\d+)$/.test(clean)) return "NaN";
  const negative = clean.startsWith("-");
  const unsigned = negative ? clean.slice(1) : clean;
  const [whole = "0", fraction = ""] = unsigned.split(".");
  const digits = `${whole || "0"}${fraction}`;
  const decimalIndex = (whole || "0").length - 2;
  const shifted = decimalIndex > 0
    ? `${digits.slice(0, decimalIndex)}.${digits.slice(decimalIndex)}`
    : `0.${"0".repeat(-decimalIndex)}${digits}`;
  const [integer, decimal] = shifted.split(".");
  const normalized = `${integer.replace(/^0+(?=\d)/, "")}${decimal === undefined ? "" : `.${decimal}`}`
    .replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
  return `${negative && normalized !== "0" ? "-" : ""}${normalized}`;
}

function formatMoney(value: string | null | undefined, currency: string) {
  if (value == null || value === "") return "—";
  return `${value.replace(/^-/, "−")}${currency ? ` ${currency}` : ""}`;
}

function inputFromEditor(
  editor: Editor,
  forecastId: string,
  forecastRevisionNumber: number,
): ApartmentInput {
  return {
    forecast_id: forecastId,
    forecast_revision_number: forecastRevisionNumber,
    guardrails: editor.guardrails,
    alternatives: editor.alternatives,
    notes: editor.notes,
    source_quality_acknowledged: editor.sourceQualityAcknowledged,
  };
}

function isUnknownMutation(error: unknown) {
  return error instanceof ApiRequestError && (error.status === 0 || error.status >= 500);
}

function isStaleRevision(error: unknown) {
  return error instanceof ApiRequestError && error.apiError?.code === "STALE_REVISION";
}

function errorMessage(error: unknown) {
  if (!(error instanceof ApiRequestError)) return "הפעולה לא הושלמה. בדקו את הנתונים ונסו שוב.";
  if (error.apiError?.code === "STALE_REVISION") return "נשמרה גרסה חדשה בזמן העבודה. רעננו את המחקר ופתחו גרסה עדכנית לפני שמירה.";
  if (error.apiError?.code === "QUALITY_ACKNOWLEDGEMENT_REQUIRED") return "יש לאשר כל חלופה ולעיין במקור התכנון הזמני לפני שמירה.";
  if (error.status === 0 || error.status >= 500) return "לא ידוע אם הפעולה הושלמה. בדקו את רשימת המחקרים לפני ניסיון נוסף.";
  return error.apiError?.message || "בדקו את הנתונים ונסו שוב.";
}

function NumberField({ label, value, onChange, hint }: {
  label: string; value: string | number; onChange(value: string): void; hint?: string;
}) {
  return <label className={styles.field}>
    <span>{label}</span>
    <input dir="ltr" inputMode="decimal" type="text" value={value} onChange={(event) => onChange(event.target.value)} aria-label={label} />
    {hint && <small>{hint}</small>}
  </label>;
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange(value: string): void }) {
  return <label className={styles.field}><span>{label}</span><input value={value} onChange={(event) => onChange(event.target.value)} aria-label={label} /></label>;
}

function SelectField<T extends string>({ label, value, choices, onChange, disabled = false }: {
  label: string; value: T; choices: Array<{ value: T; label: string }>; onChange(value: T): void; disabled?: boolean;
}) {
  return <label className={styles.field}><span>{label}</span><select value={value} disabled={disabled} onChange={(event) => onChange(event.target.value as T)} aria-label={label}>
    {choices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
  </select></label>;
}

function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warning" | "error" | "success" }) {
  return <div className={`${styles.notice} ${styles[tone]}`} role={tone === "error" || tone === "warning" ? "alert" : "status"}>{children}</div>;
}

export function ApartmentFeature() {
  const [forecasts, setForecasts] = useState<ForecastSummary[]>([]);
  const [studies, setStudies] = useState<ApartmentStudy[]>([]);
  const [forecastRevisions, setForecastRevisions] = useState<ForecastRevisionSummary[]>([]);
  const [options, setOptions] = useState<ApartmentSourceOptions | null>(null);
  const [selectedForecastId, setSelectedForecastId] = useState("");
  const [selectedForecastRevision, setSelectedForecastRevision] = useState(0);
  const [selectedStudyId, setSelectedStudyId] = useState("");
  const [selectedStudyRevision, setSelectedStudyRevision] = useState(0);
  const [studyRevisions, setStudyRevisions] = useState<ApartmentRevision[]>([]);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [studyName, setStudyName] = useState("");
  const [draft, setDraft] = useState<ApartmentDraft | null>(null);
  const [draftCurrent, setDraftCurrent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [staleRevisionConflict, setStaleRevisionConflict] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showArchived, setShowArchived] = useState(true);
  const [unknownMutation, setUnknownMutation] = useState<UnknownApartmentMutation | null>(readUnknownApartmentMutation);
  const [poolBalances, setPoolBalances] = useState<Record<string, Record<string, string>>>({});

  const selectedStudy = studies.find((item) => item.study_id === selectedStudyId) ?? null;
  const isEditing = Boolean(selectedStudy);
  const sourceProvisional = options?.planning_source.at_creation.provisional ?? false;
  const allConfirmed = Boolean(editor?.alternatives.length && editor.alternatives.every((item) => item.confirmed));
  const visibleStudies = studies.filter((item) => item.forecast_id === selectedForecastId && (showArchived || !item.archived));

  const refreshAll = useCallback(async (reconcileUnknown = false) => {
    setError("");
    try {
      const [nextForecasts, nextStudies] = await Promise.all([getForecasts(true), getApartmentStudies(true)]);
      setForecasts(nextForecasts);
      setStudies(nextStudies);
      if (reconcileUnknown && unknownMutation) {
        const reconciled = { ...unknownMutation, reconciled: true };
        storeUnknownApartmentMutation(reconciled);
        setUnknownMutation(reconciled);
      }
      return { forecasts: nextForecasts, studies: nextStudies };
    } catch (caught) {
      setError(errorMessage(caught));
      return null;
    }
  }, [unknownMutation]);

  useEffect(() => {
    let active = true;
    void (async () => {
      setLoading(true);
      try {
        const [nextForecasts, nextStudies] = await Promise.all([getForecasts(true), getApartmentStudies(true)]);
        if (!active) return;
        setForecasts(nextForecasts);
        setStudies(nextStudies);
        const first = nextForecasts.find((item) => !item.archived) ?? nextForecasts[0];
        if (first) {
          setSelectedForecastId(first.forecast_id);
          const revisions = await getForecastRevisions(first.forecast_id);
          if (!active) return;
          setForecastRevisions(revisions);
          const revisionNumber = revisions.at(-1)?.revision_number ?? 0;
          if (revisionNumber) {
            setSelectedForecastRevision(revisionNumber);
            const nextOptions = await getApartmentOptions(first.forecast_id, revisionNumber);
            if (!active) return;
            setOptions(nextOptions);
            setEditor(makeEditor(undefined, nextOptions.forecast_revision.starting_pools.map((pool) => pool.name)));
            setStudyName(`${first.name} · תכנון דירה`);
          }
        }
      } catch (caught) {
        if (active) setError(errorMessage(caught));
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, []);

  async function changeForecast(forecastId: string) {
    setBusy(true); setError(""); setNotice(""); setSelectedStudyId(""); setSelectedStudyRevision(0); setStudyRevisions([]);
    setStaleRevisionConflict(false);
    setDraft(null); setDraftCurrent(false); setEditor(null); setSelectedForecastId(forecastId);
    try {
      const nextForecast = forecasts.find((item) => item.forecast_id === forecastId);
      const revisions = await getForecastRevisions(forecastId);
      setForecastRevisions(revisions);
      const revisionNumber = revisions.at(-1)?.revision_number ?? 0;
      setSelectedForecastRevision(revisionNumber);
      if (revisionNumber) {
        const nextOptions = await getApartmentOptions(forecastId, revisionNumber);
        setOptions(nextOptions);
        setEditor(makeEditor(undefined, nextOptions.forecast_revision.starting_pools.map((pool) => pool.name)));
      } else setOptions(null);
      setStudyName(`${nextForecast?.name ?? ""} · תכנון דירה`);
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(false); }
  }

  async function changeForecastRevision(revisionNumber: number) {
    if (selectedStudy) return;
    setBusy(true); setError(""); setStaleRevisionConflict(false); setSelectedForecastRevision(revisionNumber); setDraft(null); setDraftCurrent(false);
    try {
      const nextOptions = await getApartmentOptions(selectedForecastId, revisionNumber);
      setOptions(nextOptions);
      setEditor(makeEditor(undefined, nextOptions.forecast_revision.starting_pools.map((pool) => pool.name)));
      setNotice("");
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(false); }
  }

  async function openStudy(studyId: string, revisionNumber?: number) {
    setError(""); setNotice(""); setDraft(null); setDraftCurrent(false); setStaleRevisionConflict(false);
    if (!studyId) {
      setSelectedStudyId(""); setSelectedStudyRevision(0); setStudyRevisions([]);
      const forecast = forecasts.find((item) => item.forecast_id === selectedForecastId);
      setEditor(makeEditor(undefined, options?.forecast_revision.starting_pools.map((pool) => pool.name) ?? []));
      setStudyName(`${forecast?.name ?? ""} · תכנון דירה`);
      return;
    }
    setBusy(true);
    try {
      const study = studies.find((item) => item.study_id === studyId) ?? await (async () => {
        const refreshed = await getApartmentStudies(true); setStudies(refreshed);
        return refreshed.find((item) => item.study_id === studyId)!;
      })();
      const revisions = await getApartmentRevisions(studyId);
      const number = revisionNumber ?? study.current_revision_number;
      const [saved, nextOptions, forecastRevs] = await Promise.all([
        getApartmentRevisionProjection(studyId, number),
        getApartmentOptions(study.forecast_id, study.forecast_revision_number),
        getForecastRevisions(study.forecast_id),
      ]);
      setSelectedForecastId(study.forecast_id);
      setSelectedForecastRevision(study.forecast_revision_number);
      setForecastRevisions(forecastRevs);
      setSelectedStudyId(studyId);
      setStudyRevisions(revisions);
      setSelectedStudyRevision(number);
      setOptions(nextOptions);
      setStudyName(study.name);
      setEditor(makeEditor(saved.snapshot, nextOptions.forecast_revision.starting_pools.map((pool) => pool.name)));
      setDraft(saved.draft);
      setDraftCurrent(false);
      if (study.archived) setNotice("המחקר בארכיון. אפשר לעיין בו ולבטל את הארכוב.");
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(false); }
  }

  async function changeStudyRevision(revisionNumber: number) {
    if (!selectedStudyId) return;
    setBusy(true); setError(""); setStaleRevisionConflict(false); setSelectedStudyRevision(revisionNumber); setDraftCurrent(false);
    try {
      const saved = await getApartmentRevisionProjection(selectedStudyId, revisionNumber);
      setEditor(makeEditor(saved.snapshot, options?.forecast_revision.starting_pools.map((pool) => pool.name) ?? []));
      setDraft(saved.draft);
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(false); }
  }

  function updateAlternative(index: number, patch: Partial<ApartmentAlternative>) {
    setEditor((current) => current ? {
      ...current,
      alternatives: current.alternatives.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch, confirmed: false } : item),
    } : current);
    setDraftCurrent(false);
  }

  function updateEditor(patch: Partial<Editor>, invalidateAll = false) {
    setEditor((current) => current ? {
      ...current,
      ...patch,
      alternatives: (patch.alternatives ?? current.alternatives).map((item) => invalidateAll ? { ...item, confirmed: false } : item),
    } : current);
    setDraftCurrent(false);
  }

  function updateCollection(index: number, key: "purchase_costs" | "housing_costs" | "pool_draws", itemIndex: number, field: string, value: string) {
    const alt = editor?.alternatives[index];
    if (!alt) return;
    const next = [...alt[key]] as Array<Record<string, string>>;
    next[itemIndex] = { ...next[itemIndex], [field]: value };
    updateAlternative(index, { [key]: next } as Partial<ApartmentAlternative>);
  }

  async function refreshPreview(inputEditor = editor) {
    if (!inputEditor || !selectedForecastId || !selectedForecastRevision) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await previewApartment(inputFromEditor(inputEditor, selectedForecastId, selectedForecastRevision));
      setDraft(response); setDraftCurrent(true);
    } catch (caught) { setError(errorMessage(caught)); setDraftCurrent(false); }
    finally { setBusy(false); }
  }

  async function toggleConfirmation(index: number, confirmed: boolean) {
    if (!editor) return;
    const next: Editor = {
      ...editor,
      alternatives: editor.alternatives.map((item, itemIndex) => itemIndex === index ? { ...item, confirmed } : item),
    };
    setEditor(next);
    const allNowConfirmed = next.alternatives.every((item) => item.confirmed);
    setDraftCurrent(false);
    if (allNowConfirmed) await refreshPreview(next);
  }

  async function reconcilePending() {
    if (!unknownMutation) return;
    const result = await refreshAll(true);
    if (result) setNotice("רשימת המחקרים נטענה מחדש מהשרת. בדקו אם המחקר או העותק מופיעים לפני סגירת הפעולה הממתינה.");
  }

  function closePending() {
    storeUnknownApartmentMutation(null); setUnknownMutation(null); setNotice("הפעולה הממתינה נסגרה. ניתן להתחיל יצירה או שכפול חדשים.");
  }

  async function runCreateOrClone(kind: "create" | "clone", operation: () => Promise<ApartmentStudy>, label: string, forecastId = selectedForecastId, studyId?: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      const created = await operation();
      await refreshAll(false);
      if (kind === "create") {
        setSelectedForecastId(created.forecast_id);
        await openStudy(created.study_id, created.current_revision_number);
      } else {
        await openStudy(created.study_id, created.current_revision_number);
      }
      setNotice(kind === "create" ? "המחקר נשמר." : "נוצר עותק עצמאי של המחקר.");
    } catch (caught) {
      setError(errorMessage(caught));
      if (isUnknownMutation(caught)) {
        const pending: UnknownApartmentMutation = { kind, reconciled: false, forecastId, studyId, label };
        storeUnknownApartmentMutation(pending); setUnknownMutation(pending);
        const result = await refreshAll(false);
        if (result) {
          const reconciled = { ...pending, reconciled: true };
          storeUnknownApartmentMutation(reconciled); setUnknownMutation(reconciled);
          setNotice("התוצאה לא ידועה. רשימת המחקרים עודכנה; בדקו אותה ואז סגרו את הפעולה הממתינה כדי לאפשר ניסיון חדש.");
        }
      }
    } finally { setBusy(false); }
  }

  async function save() {
    if (!editor || !draft || !draftCurrent || !allConfirmed) return;
    if (sourceProvisional && !editor.sourceQualityAcknowledged) {
      setError("המקור התכנוני הזמני דורש אישור לפני שמירה."); return;
    }
    if (!selectedForecastId || !selectedForecastRevision) return;
    const input = inputFromEditor(editor, selectedForecastId, selectedForecastRevision);
    setBusy(true); setError(""); setNotice("");
    try {
      if (selectedStudy) {
        const saved = await saveApartmentRevision(selectedStudy.study_id, { ...input, expected_revision_number: selectedStudy.current_revision_number });
        await refreshAll(false);
        await openStudy(selectedStudy.study_id, saved.revision_number);
        setNotice("נשמרה גרסה חדשה. הגרסאות הקודמות נשארו ללא שינוי.");
      } else {
        await runCreateOrClone("create", () => createApartmentStudy({ ...input, name: studyName }), studyName, selectedForecastId);
      }
    } catch (caught) { setError(errorMessage(caught)); if (isStaleRevision(caught)) setStaleRevisionConflict(true); }
    finally { setBusy(false); }
  }

  async function restoreSelected() {
    if (!selectedStudy || !selectedStudyRevision) return;
    setBusy(true); setError("");
    try {
      const restored = await restoreApartmentRevision(selectedStudy.study_id, selectedStudyRevision, selectedStudy.current_revision_number);
      await refreshAll(false); await openStudy(selectedStudy.study_id, restored.revision_number);
      setNotice("הגרסה שנבחרה שוחזרה כגרסה חדשה. ההיסטוריה נשמרה.");
    } catch (caught) { setError(errorMessage(caught)); if (isStaleRevision(caught)) setStaleRevisionConflict(true); }
    finally { setBusy(false); }
  }

  async function cloneSelected() {
    if (!selectedStudy || unknownMutation) return;
    await runCreateOrClone("clone", () => cloneApartmentStudy(selectedStudy.study_id), selectedStudy.name, selectedStudy.forecast_id, selectedStudy.study_id);
  }

  async function toggleArchive() {
    if (!selectedStudy) return;
    setBusy(true); setError("");
    try {
      await setApartmentArchived(selectedStudy.study_id, !selectedStudy.archived);
      await refreshAll(false);
      setNotice(selectedStudy.archived ? "המחקר הוצא מהארכיון." : "המחקר הועבר לארכיון.");
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(false); }
  }

  async function reopenLatestStudy() {
    if (!selectedStudyId) return;
    setBusy(true); setError("");
    try {
      const freshStudies = await getApartmentStudies(true);
      setStudies(freshStudies);
      const latest = freshStudies.find((item) => item.study_id === selectedStudyId);
      if (!latest) throw new Error("Study not found after refresh");
      await openStudy(selectedStudyId, latest.current_revision_number);
      setNotice("המחקר נטען מחדש מהגרסה העדכנית. שינויים שלא נשמרו הוסרו.");
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(false); }
  }

  async function loadBalances(index: number) {
    const alt = editor?.alternatives[index];
    if (!alt || !selectedForecastId || !selectedForecastRevision) return;
    const key = `${index}-${alt.forecast_role}-${alt.purchase_month}`;
    if (poolBalances[key]) return;
    try {
      const balances = await getApartmentPoolBalances({ forecastId: selectedForecastId, revisionNumber: selectedForecastRevision, role: alt.forecast_role, purchaseMonth: alt.purchase_month });
      setPoolBalances((current) => ({ ...current, [key]: balances }));
    } catch (caught) { setError(errorMessage(caught)); }
  }

  const poolNames = options?.forecast_revision.starting_pools.map((pool) => pool.name) ?? [];
  const sourceHash = options?.forecast_revision.assumption_hash ?? selectedStudy?.forecast_assumption_hash ?? "";
  const sourceRevisionId = options?.forecast_revision.source_revision_id ?? "";
  const sourcePlan = options?.planning_source.at_creation;
  const visibleDraft = draft;

  useEffect(() => {
    if (!editor || !selectedForecastId || !selectedForecastRevision) return;
    editor.alternatives.forEach((_alternative, index) => { void loadBalances(index); });
    // The visible inputs determine these read-only month-end pool balances.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor?.alternatives.map((item) => `${item.forecast_role}:${item.purchase_month}`).join("|"), selectedForecastId, selectedForecastRevision]);

  if (loading) return <section className={styles.feature}><div className={styles.loading}>טוענים מחקרים ותחזיות…</div></section>;

  return <section className={styles.feature}>
    <div className={styles.toolbar}>
      <label className={styles.field}>
        <span>תחזית שמורה</span>
        <select value={selectedForecastId} disabled={busy || isEditing} onChange={(event) => void changeForecast(event.target.value)} aria-label="תחזית שמורה">
          {forecasts.map((forecast) => <option key={forecast.forecast_id} value={forecast.forecast_id}>{forecast.name}{forecast.archived ? " · בארכיון" : ""}</option>)}
        </select>
      </label>
      <label className={styles.field}>
        <span>מחקר דירה</span>
        <select value={selectedStudyId} disabled={busy || !selectedForecastId} onChange={(event) => void openStudy(event.target.value)} aria-label="מחקר דירה">
          <option value="">מחקר חדש</option>
          {visibleStudies.map((study) => <option key={study.study_id} value={study.study_id}>{study.name} · גרסה {study.current_revision_number}{study.archived ? " · ארכיון" : ""}</option>)}
        </select>
      </label>
      {!isEditing && <label className={styles.field}>
        <span>גרסת תחזית מדויקת</span>
        <select value={selectedForecastRevision || ""} disabled={busy || !forecastRevisions.length} onChange={(event) => void changeForecastRevision(Number(event.target.value))} aria-label="גרסת תחזית מדויקת">
          {forecastRevisions.map((revision) => <option key={revision.revision_id} value={revision.revision_number}>גרסה {revision.revision_number} · {revision.assumption_hash.slice(0, 10)}</option>)}
        </select>
      </label>}
      {isEditing && <div className={styles.field}><span>גרסת תחזית נעולה</span><div className={styles.readOnly}>גרסה {selectedStudy?.forecast_revision_number} · {selectedStudy?.forecast_assumption_hash.slice(0, 10)}</div></div>}
      <label className={styles.checkLine}><input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} /> הצגת מחקרים בארכיון</label>
      <Button variant="outline" disabled={busy} onClick={() => void refreshAll(Boolean(unknownMutation))}>{unknownMutation && !unknownMutation.reconciled ? "רענון ובדיקת תוצאה" : "רענון"}</Button>
    </div>

    {!forecasts.length && <Notice tone="warning">צריך ליצור ולשמור תחזית חיסכון לפני תכנון רכישת דירה.</Notice>}
    {error && <Notice tone="error">{error}</Notice>}
    {notice && <Notice tone="success">{notice}</Notice>}
    {staleRevisionConflict && selectedStudy && <Notice tone="warning">הטיוטה מבוססת על גרסה ישנה ואי אפשר לשמור אותה. פתחו מחדש את הגרסה הנוכחית כדי להמשיך.<br /><Button variant="outline" disabled={busy} onClick={() => void reopenLatestStudy()}>טעינת הגרסה העדכנית</Button></Notice>}
    {unknownMutation && <div className={styles.unknown} role="alert">
      <strong>תוצאת {unknownMutation.kind === "create" ? "היצירה" : "השכפול"} אינה ידועה.</strong>
      <p>השרת אולי שמר את המחקר. עדכנו את הרשימה ובדקו את המחקרים המוצגים לפני שתסגרו את הפעולה הממתינה. יצירה ושכפול נשארים נעולים עד הסגירה.</p>
      {!unknownMutation.reconciled
        ? <Button variant="outline" disabled={busy} onClick={() => void reconcilePending()}>בדיקת מצב מול השרת</Button>
        : <Button variant="outline" disabled={busy} onClick={closePending}>בדקתי את הרשימה — סגירת הפעולה הממתינה</Button>}
    </div>}

    {selectedStudy && <section className={styles.history} aria-label="היסטוריית מחקר">
      <div className={styles.historyHeader}><div><h2>{selectedStudy.name}</h2><p>מקור המחקר נשאר נעול לגרסת התחזית שנבחרה בעת יצירתו.</p></div><span className={styles.tag}>{selectedStudy.archived ? "בארכיון" : "פעיל"}</span></div>
      <div className={styles.historyActions}>
        <label className={styles.field}><span>גרסת מחקר לעיון</span><select value={selectedStudyRevision || selectedStudy.current_revision_number} disabled={busy} onChange={(event) => void changeStudyRevision(Number(event.target.value))} aria-label="גרסת מחקר לעיון">
          {studyRevisions.map((revision) => <option key={revision.revision_id} value={revision.revision_number}>גרסה {revision.revision_number} · {revision.assumption_hash.slice(0, 10)}</option>)}
        </select></label>
        <Button variant="outline" disabled={busy || selectedStudyRevision === selectedStudy.current_revision_number} onClick={() => void restoreSelected()}>שחזור כגרסה חדשה</Button>
        <Button variant="outline" disabled={busy || Boolean(unknownMutation)} onClick={() => void cloneSelected()}>שכפול למחקר חדש</Button>
        <Button variant="outline" disabled={busy} onClick={() => void toggleArchive()}>{selectedStudy.archived ? "הוצאה מהארכיון" : "העברה לארכיון"}</Button>
      </div>
    </section>}

    {options && selectedForecastRevision > 0 && editor && <>
      <section className={styles.provenance} aria-label="מקור הנתונים">
        <div><strong>מקור התחזית</strong><span>{options.forecast.name} · גרסה {options.forecast_revision.revision_number}</span></div>
        <div><strong>Hash התחזית</strong><span dir="ltr">{sourceHash}</span></div>
        <div><strong>תכנון שנשמר בתחזית</strong><span>גרסה {options.forecast_revision.source_revision_number} · {sourceRevisionId.slice(0, 12)}</span></div>
        <div><strong>מצב המקור בעת יצירת התחזית</strong><span>{sourcePlan?.provisional ? "זמני" : "מאומת"}{sourcePlan?.issue_codes.length ? ` · ${sourcePlan.issue_codes.join(", ")}` : ""}</span></div>
        {options.planning_source.current.revision_number !== options.planning_source.at_creation.revision_number && <p className={styles.notice}>התכנון השתנה מאז יצירת התחזית. המחקר ממשיך להשתמש בתכנון המקורי מגרסה {options.planning_source.at_creation.revision_number}; הוא לא עובר אוטומטית לגרסה העדכנית.</p>}
      </section>
      {sourceProvisional && <Notice tone="warning">התחזית יורשת בעיות מקור מתוכנית זמנית. האישור יישמר עם גרסת המחקר.</Notice>}

      <section className={styles.editorHead}>
        <div><h2>{isEditing ? "עריכת הנחות המחקר" : "מחקר רכישת דירה חדש"}</h2><p>החישובים והתחזית החודשית מגיעים מ־ApartmentPlanningService. כל המספרים הם אומדן בלבד.</p></div>
        {!isEditing && <TextField label="שם המחקר" value={studyName} onChange={setStudyName} />}
      </section>

      <section className={styles.guardrails} aria-label="כללי סף">
        <h3>כללי סף</h3>
        <NumberField label="נזילות מינימלית לאחר רכישה (אופציונלי)" value={editor.guardrails.minimum_remaining_liquidity ?? ""} onChange={(value) => updateEditor({ guardrails: { ...editor.guardrails, minimum_remaining_liquidity: value || null } }, true)} />
        <NumberField label="יחס דיור להכנסה ברוטו מרבי (%)" value={decimalToPercent(editor.guardrails.maximum_housing_cost_to_income_ratio)} onChange={(value) => updateEditor({ guardrails: { ...editor.guardrails, maximum_housing_cost_to_income_ratio: value ? percentToDecimal(value) : null } }, true)} hint="ההמרה לאחוז מתבצעת פעם אחת בגבול ה־API." />
      </section>

      <div className={styles.alternativesHeading}><div><h3>חלופות רכישה</h3><p>יש להגדיר ולאשר 2–4 חלופות.</p></div><div className={styles.countActions}>
        <Button variant="outline" disabled={busy || editor.alternatives.length <= 2} onClick={() => { updateEditor({ alternatives: editor.alternatives.slice(0, -1) }, true); }}>הסרת חלופה</Button>
        <Button variant="outline" disabled={busy || editor.alternatives.length >= 4} onClick={() => { updateEditor({ alternatives: [...editor.alternatives, emptyAlternative(editor.alternatives.length, poolNames)] }, true); }}>הוספת חלופה</Button>
      </div></div>

      <div className={styles.alternatives}>
        {editor.alternatives.map((alt, index) => {
          const balanceKey = `${index}-${alt.forecast_role}-${alt.purchase_month}`;
          const balances = poolBalances[balanceKey] ?? {};
          const projection = visibleDraft?.projections.find((item) => item.alternative_name === alt.name);
          return <article className={styles.alternative} key={`${selectedStudyId || "new"}-${index}`}>
            <div className={styles.alternativeHead}><div><span className={styles.altNumber}>חלופה {index + 1}</span><h4>{alt.name || `חלופה ${index + 1}`}</h4></div>{projection && <span className={`${styles.tag} ${projection.readiness.ready ? styles.ready : styles.notReady}`}>{projection.readiness.ready ? "מוכנה לפי כללי הסף" : "דורשת בדיקה"}</span>}</div>
            <div className={styles.fieldsGrid}>
              <TextField label="שם החלופה" value={alt.name} onChange={(name) => updateAlternative(index, { name })} />
              <SelectField label="תרחיש תחזית" value={alt.forecast_role} choices={roles.map((role) => ({ value: role, label: roleLabel[role] }))} onChange={(forecast_role) => updateAlternative(index, { forecast_role })} />
              <NumberField label="חודש רכישה (1–36)" value={alt.purchase_month} onChange={(value) => updateAlternative(index, { purchase_month: Number(value) || 1 })} />
              <NumberField label="מחיר הנכס" value={alt.property_price} onChange={(property_price) => updateAlternative(index, { property_price })} />
              <NumberField label="מתנה משפחתית" value={alt.family_gift} onChange={(family_gift) => updateAlternative(index, { family_gift })} />
              <SelectField label="כלל הון עצמי" value={alt.equity_requirement.mode} choices={[{ value: "percentage", label: "אחוז ממחיר הדירה" }, { value: "amount", label: "סכום" }]} onChange={(mode) => updateAlternative(index, { equity_requirement: { ...alt.equity_requirement, mode } })} />
              <NumberField label={alt.equity_requirement.mode === "percentage" ? "דרישת הון עצמי (%)" : "דרישת הון עצמי (סכום)"} value={alt.equity_requirement.mode === "percentage" ? decimalToPercent(alt.equity_requirement.value) : alt.equity_requirement.value} onChange={(value) => updateAlternative(index, { equity_requirement: { ...alt.equity_requirement, value: alt.equity_requirement.mode === "percentage" ? percentToDecimal(value) : value } })} />
              <NumberField label="קרן משכנתה" value={alt.mortgage.principal} onChange={(principal) => updateAlternative(index, { mortgage: { ...alt.mortgage, principal } })} />
              <NumberField label="ריבית שנתית נומינלית (%)" value={decimalToPercent(alt.mortgage.annual_nominal_rate)} onChange={(value) => updateAlternative(index, { mortgage: { ...alt.mortgage, annual_nominal_rate: percentToDecimal(value) } })} />
              <NumberField label="תקופת משכנתה בחודשים (12–480)" value={alt.mortgage.term_months} onChange={(value) => updateAlternative(index, { mortgage: { ...alt.mortgage, term_months: Number(value) || 12 } })} />
            </div>

            <details className={styles.detailSection} open>
              <summary>עלויות רכישה</summary>
              {alt.purchase_costs.map((cost, costIndex) => <div className={styles.rowEditor} key={`purchase-cost-${costIndex}`}>
                <TextField label={`שם עלות ${costIndex + 1}`} value={cost.label} onChange={(value) => updateCollection(index, "purchase_costs", costIndex, "label", value)} />
                <NumberField label={`סכום עלות ${costIndex + 1}`} value={cost.amount} onChange={(value) => updateCollection(index, "purchase_costs", costIndex, "amount", value)} />
                <Button variant="ghost" size="sm" disabled={alt.purchase_costs.length <= 1} aria-label={`הסרת עלות ${costIndex + 1}`} onClick={() => updateAlternative(index, { purchase_costs: alt.purchase_costs.filter((_item, item) => item !== costIndex) })}>הסרה</Button>
              </div>)}
              <Button variant="outline" size="sm" onClick={() => updateAlternative(index, { purchase_costs: [...alt.purchase_costs, { label: "עלות נוספת", amount: "0" }] })}>הוספת עלות</Button>
            </details>

            <details className={styles.detailSection} open>
              <summary>משיכות מקופות חיסכון</summary>
              <p className={styles.help}>היתרות מחושבות לפי תרחיש התחזית ובסוף חודש הרכישה, לפני משיכת הרכישה. בקשות המשיכה עצמן נשארות בדיוק כפי שהוזנו.</p>
              {poolNames.map((pool) => {
                const drawIndex = alt.pool_draws.findIndex((draw) => draw.pool_name === pool);
                const amount = drawIndex >= 0 ? alt.pool_draws[drawIndex].amount : "0";
                return <div className={styles.rowEditor} key={pool}><div className={styles.poolName}><strong>{pool}</strong><small>יתרה זמינה: {formatMoney(balances[pool], options.forecast.currency)}</small></div>
                  <NumberField label={`משיכה מ־${pool}`} value={amount} onChange={(value) => {
                    const next = [...alt.pool_draws];
                    if (drawIndex >= 0) next[drawIndex] = { ...next[drawIndex], amount: value };
                    else next.push({ pool_name: pool, amount: value });
                    updateAlternative(index, { pool_draws: next });
                  }} />
                </div>;
              })}
            </details>

            <details className={styles.detailSection}>
              <summary>הוצאות דיור שמסתיימות ועלויות דיור חדשות</summary>
              <fieldset className={styles.expenseChoices}><legend>הוצאות קיימות להפסקה לאחר המעבר</legend>
                {options.expense_lines.length === 0 ? <p>אין שורות הוצאה בתוכנית המקור.</p> : options.expense_lines.map((line) => <label key={line.id} className={styles.checkLine}>
                  <input type="checkbox" checked={alt.stopped_housing_line_ids.includes(line.id)} onChange={(event) => updateAlternative(index, { stopped_housing_line_ids: event.target.checked ? [...alt.stopped_housing_line_ids, line.id] : alt.stopped_housing_line_ids.filter((id) => id !== line.id) })} />
                  <span>{line.label} · {line.amount} {options.forecast.currency}</span>
                </label>)}
              </fieldset>
              <h5>הוצאות דיור חודשיות חדשות לאחר המעבר</h5>
              {alt.housing_costs.map((cost, costIndex) => <div className={styles.rowEditor} key={`housing-cost-${costIndex}`}>
                <TextField label={`שם הוצאה חודשית ${costIndex + 1}`} value={cost.label} onChange={(value) => updateCollection(index, "housing_costs", costIndex, "label", value)} />
                <NumberField label={`סכום חודשי ${costIndex + 1}`} value={cost.amount} onChange={(value) => updateCollection(index, "housing_costs", costIndex, "amount", value)} />
                <Button variant="ghost" size="sm" disabled={alt.housing_costs.length <= 1} aria-label={`הסרת הוצאה ${costIndex + 1}`} onClick={() => updateAlternative(index, { housing_costs: alt.housing_costs.filter((_item, item) => item !== costIndex) })}>הסרה</Button>
              </div>)}
              <Button variant="outline" size="sm" onClick={() => updateAlternative(index, { housing_costs: [...alt.housing_costs, { label: "הוצאה חודשית נוספת", amount: "0" }] })}>הוספת הוצאה</Button>
            </details>

            {projection && <section className={styles.projection} aria-label={`תוצאות ${alt.name}`}>
              <div className={styles.sectionTitle}><div><h5>מקורות, שימושים ומוכנות</h5><p>הערכה לפי הנתונים והגרסה הנעולה.</p></div></div>
              <dl className={styles.metrics}>
                <div><dt>שימושים</dt><dd>{formatMoney(projection.total_uses, options.forecast.currency)}</dd></div>
                <div><dt>סה״כ מקורות</dt><dd>{formatMoney(projection.total_sources, options.forecast.currency)}</dd></div>
                <div><dt>הון עצמי מוצע</dt><dd>{formatMoney(projection.proposed_equity, options.forecast.currency)}</dd></div>
                <div><dt>הון עצמי נדרש</dt><dd>{formatMoney(projection.required_equity, options.forecast.currency)}</dd></div>
                <div><dt>משכנתה</dt><dd>{formatMoney(projection.mortgage_principal, options.forecast.currency)}</dd></div>
                <div><dt>מתנה</dt><dd>{formatMoney(projection.family_gift, options.forecast.currency)}</dd></div>
                <div><dt>משיכות שבוצעו בתחזית</dt><dd>{formatMoney(projection.fulfilled_pool_draws, options.forecast.currency)}</dd></div>
                <div><dt>פער מימון</dt><dd>{formatMoney(projection.funding_gap, options.forecast.currency)}</dd></div>
                <div><dt>נזילות לאחר רכישה</dt><dd>{formatMoney(projection.remaining_liquidity, options.forecast.currency)}</dd></div>
                <div><dt>ריבית מצטברת</dt><dd>{formatMoney(projection.total_interest, options.forecast.currency)}</dd></div>
                <div><dt>יתרה בחודש 36</dt><dd>{formatMoney(projection.month_36_balance, options.forecast.currency)}</dd></div>
              </dl>
              <p className={styles.readiness}>{projection.readiness.ready ? "החלופה עומדת בכללי הסף שהוגדרו." : "נדרשת בדיקה לפני שניתן לסמן את החלופה כמוכנה."}</p>
              {projection.readiness.failures.length > 0 && <ul className={styles.failures}>{projection.readiness.failures.map((failure) => <li key={failure}>{failure}</li>)}</ul>}
              <details className={styles.resultDetails}>
                <summary>לוח תשלומים והנחות נוסחה למשכנתה</summary>
                <p>ריבית חודשית = ריבית שנתית נומינלית ÷ 12. תשלום קבוע: P × r / (1 − (1 + r)^−n); בריבית אפס P ÷ n. עיגול חצי־לזוגי לאגורות; התשלום האחרון סוגר את היתרה.</p>
                <div className={styles.tableWrap}><table><thead><tr><th>חודש</th><th>תשלום</th><th>ריבית</th><th>קרן</th><th>יתרה</th></tr></thead><tbody>
                  {projection.mortgage_schedule.slice(0, 36).map((row) => <tr key={row.period}><td>{row.period}</td><td>{formatMoney(row.payment, options.forecast.currency)}</td><td>{formatMoney(row.interest, options.forecast.currency)}</td><td>{formatMoney(row.principal, options.forecast.currency)}</td><td>{formatMoney(row.remaining_principal, options.forecast.currency)}</td></tr>)}
                </tbody></table></div>
                <small>Hash טיוטת הנחות: <span dir="ltr">{draft?.assumption_hash}</span></small>
              </details>
              <details className={styles.resultDetails}>
                <summary>תוצאות חודשיות לתקופה של 36 חודשים</summary>
                <div className={styles.monthlyCards}>{projection.monthly.map((month) => <div className={styles.monthCard} key={month.month_number}>
                  <strong>חודש {month.month_number} · {month.month.slice(0, 7)}</strong>
                  <span>הכנסה: {formatMoney(month.income, options.forecast.currency)}</span>
                  <span>הוצאות: {formatMoney(month.expenses, options.forecast.currency)}</span>
                  <span>דיור: {formatMoney(month.housing_cost, options.forecast.currency)}</span>
                  <span>תזרים לאחר תחזית: {formatMoney(month.cash_after_sweep, options.forecast.currency)}</span>
                  <span>יתרה: {formatMoney(month.ending_balance, options.forecast.currency)}</span>
                </div>)}</div>
              </details>
            </section>}

            <label className={styles.confirm}><input type="checkbox" checked={alt.confirmed} disabled={busy || !visibleDraft} onChange={(event) => void toggleConfirmation(index, event.target.checked)} />
              <span>עיינתי בחלופה הזו ומאשר/ת את ההנחות</span></label>
          </article>;
        })}
      </div>

      {visibleDraft && <section className={styles.comparison}>
        <h3>השוואת חלופות</h3>
        <div className={styles.comparisonCards}>{visibleDraft.comparison?.alternatives.map((row) => <article key={row.alternative_name}>
          <h4>{row.alternative_name}</h4><span>חודש {row.purchase_month} · {roleLabel[row.forecast_role]}</span>
          <dl><div><dt>פער מימון</dt><dd>{formatMoney(row.closing_gap, options.forecast.currency)}</dd></div><div><dt>החזר חודשי</dt><dd>{formatMoney(row.mortgage_payment, options.forecast.currency)}</dd></div><div><dt>ריבית כוללת</dt><dd>{formatMoney(row.total_interest, options.forecast.currency)}</dd></div><div><dt>נזילות שנותרה</dt><dd>{formatMoney(row.remaining_liquidity, options.forecast.currency)}</dd></div></dl>
        </article>)}</div>
        <p className={styles.disclaimer}>הערכה המבוססת על ההנחות שסופקו; אינה הצעת משכנתה או התחייבות.</p>
      </section>}
      {visibleDraft && !draftCurrent && <Notice tone="warning">החישוב המוצג שייך לטיוטה קודמת. חשבו מחדש לאחר השינוי ואישור כל החלופות לפני שמירה.</Notice>}

      <section className={styles.saveArea}>
        <TextField label="הערות למחקר" value={editor.notes} onChange={(notes) => updateEditor({ notes })} />
        {sourceProvisional && <label className={styles.confirm}><input type="checkbox" checked={editor.sourceQualityAcknowledged} onChange={(event) => updateEditor({ sourceQualityAcknowledged: event.target.checked })} /><span>עיינתי בסוגיות המקור התכנוני הזמני ומאשר/ת להמשיך</span></label>}
        {!draftCurrent && <p className={styles.help}>{allConfirmed ? "החלופות אושרו. חשבו טיוטה עדכנית לפני השמירה." : "שינוי בהנחה או באישור החלופה דורש חישוב טיוטה עדכני."}</p>}
        <div className={styles.saveActions}>
          <Button variant="outline" disabled={busy} onClick={() => void refreshPreview()}>חישוב / רענון טיוטה</Button>
          <Button disabled={busy || Boolean(unknownMutation) || staleRevisionConflict || !allConfirmed || !draftCurrent || (sourceProvisional && !editor.sourceQualityAcknowledged) || (!selectedStudy && !studyName.trim())} onClick={() => void save()}>{busy ? "שומר…" : selectedStudy ? "שמירת גרסה חדשה" : "יצירת מחקר"}</Button>
        </div>
        {draftCurrent && allConfirmed && <small>Hash הטיוטה שמיועד לשמירה: <span dir="ltr">{draft?.assumption_hash}</span></small>}
      </section>
    </>}

    {selectedStudy && studyRevisions.length > 0 && <details className={styles.historyList}>
      <summary>היסטוריית גרסאות ({studyRevisions.length})</summary>
      <ol>{studyRevisions.map((revision) => <li key={revision.revision_id}><button type="button" onClick={() => void changeStudyRevision(revision.revision_number)}>גרסה {revision.revision_number}</button><span>{revision.created_at ? new Date(revision.created_at).toLocaleString("he-IL") : ""}</span><code>{revision.assumption_hash.slice(0, 16)}</code></li>)}</ol>
    </details>}
  </section>;
}
