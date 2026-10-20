"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { MonthPicker } from "@/components/ui/month-picker";
import { Button, buttonVariants } from "@/components/ui/button";
import { ErrorState, LoadingState } from "@/components/ui/async-state";
import { formatAmount as formatMoney, rateToPercent as formatRateAsPercent, percentToRate, currencyLabel, formatHebrewDate, formatHebrewMonth, issueLabel } from "@/lib/display";
import { ApiRequestError } from "@/lib/api";
import { getScenarios, getRevision as getPlanningRevision, getRevisions as getPlanningRevisions } from "@/features/planning/api";
import type { PlanningItem, PlanningRevision, PlanningScenario } from "@/features/planning/types";
import { getRevisions as getNetWorthRevisions, getSnapshots } from "@/features/net-worth/api";
import type { SnapshotRevision, SnapshotSummary } from "@/features/net-worth/types";
import {
  cloneForecast,
  createForecast,
  getForecastProjection,
  getForecastRevisions,
  getForecasts,
  getNetWorthSeeds,
  previewForecast,
  restoreForecastRevision,
  saveForecastRevision,
  setForecastArchived,
} from "./api";
import type {
  ForecastAdjustment,
  ForecastAdjustmentOperation,
  ForecastCase,
  ForecastDraft,
  ForecastEvent,
  ForecastEventType,
  ForecastInputPayload,
  ForecastMonth,
  ForecastPool,
  ForecastPoolType,
  ForecastProjection,
  ForecastRevisionProjection,
  ForecastRevisionSummary,
  ForecastRole,
  ForecastSummary,
} from "./types";
import { readUnknownForecastMutation, storeUnknownForecastMutation } from "./unknown-mutation";
import styles from "./forecasts.module.css";

const roles: ForecastRole[] = ["conservative", "baseline", "optimistic"];
const roleLabels: Record<ForecastRole, string> = {
  conservative: "שמרני",
  baseline: "בסיסי",
  optimistic: "אופטימי",
};
const roleColors: Record<ForecastRole, string> = {
  conservative: "var(--forecast-conservative)",
  baseline: "var(--primary)",
  optimistic: "var(--forecast-optimistic)",
};
const savingKinds = new Set(["savings_contribution", "savings_withdrawal"]);
const eventTypes: ForecastEventType[] = ["income", "expense", "contribution", "withdrawal"];
const eventLabels: Record<ForecastEventType, string> = {
  income: "הכנסה חד־פעמית",
  expense: "הוצאה חד־פעמית",
  contribution: "הפקדה לקופה",
  withdrawal: "משיכה מקופה",
};

type EditorState = {
  mode: "create" | "edit";
  forecastId?: string;
  expectedRevisionNumber?: number;
  step: 1 | 2 | 3;
  name: string;
  scenarioId: string;
  sourceRevisionNumber: number;
  pools: ForecastPool[];
  cases: ForecastCase[];
  notes: string;
  provisionalAcknowledged: boolean;
};

function monthLabel(month: string) { return formatHebrewMonth(month.slice(0, 7)); }

/** Exact aggregation for display only; all forecast calculations stay on the server. */
function sumDisplayAmounts(values: string[]): string | null {
  if (values.some((value) => !/^-?\d+(?:\.\d+)?$/.test(value))) return null;
  const scale = Math.max(0, ...values.map((value) => value.split(".")[1]?.length ?? 0));
  const total = values.reduce((sum, value) => {
    const [whole, fraction = ""] = value.replace(/^-/, "").split(".");
    return sum + (value.startsWith("-") ? -BigInt(1) : BigInt(1)) * BigInt(whole + fraction.padEnd(scale, "0"));
  }, BigInt(0));
  const digits = (total < BigInt(0) ? -total : total).toString().padStart(scale + 1, "0");
  return `${total < BigInt(0) ? "-" : ""}${scale ? `${digits.slice(0, -scale)}.${digits.slice(-scale)}` : digits}`;
}

function forecastMonth(start: string, number: number) {
  const [year, month] = start.slice(0, 7).split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1 + number - 1, 1));
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}
function forecastMonthNumber(start: string, value: string) {
  return (Number(value.slice(0, 4)) - Number(start.slice(0, 4))) * 12 + Number(value.slice(5, 7)) - Number(start.slice(5, 7)) + 1;
}

function sourceItems(revision: PlanningRevision | null): PlanningItem[] {
  return revision?.items.filter((item) => savingKinds.has(item.kind)) ?? [];
}

function defaultCases(revision: PlanningRevision, poolName: string): ForecastCase[] {
  const annualRates: Record<ForecastRole, string> = { conservative: "0", baseline: "0.03", optimistic: "0.06" };
  return roles.map((role) => ({
    role,
    annual_return_rate: annualRates[role],
    routes: sourceItems(revision).map((item) => ({ source_item_id: item.id, pool_name: poolName })),
    sweep_enabled: false,
    sweep_pool_name: null,
    adjustments: [],
    events: [],
    confirmed: false,
  }));
}

function savedCases(cases: ForecastCase[], revision: PlanningRevision, poolName: string): ForecastCase[] {
  const defaults = defaultCases(revision, poolName);
  return roles.map((role) => {
    const selected = cases.find((item) => item.role === role);
    if (!selected) return defaults.find((item) => item.role === role)!;
    return {
      ...selected,
      routes: sourceItems(revision).map((item) => selected.routes.find((route) => route.source_item_id === item.id) ?? {
        source_item_id: item.id, pool_name: poolName,
      }),
      confirmed: false,
    };
  });
}

function emptyPool(startMonth: string, name: string): ForecastPool {
  return { name, pool_type: "cash", opening_balance: "0", as_of_date: startMonth.slice(0, 10) };
}

function describeError(error: unknown) {
  if (!(error instanceof ApiRequestError)) return "הפעולה לא הושלמה. בדקו את הקלט ונסו שוב.";
  if (error.apiError?.code === "STALE_REVISION") return "נשמרה גרסה חדשה בזמן העבודה. רעננו את התחזית ופתחו טיוטה חדשה לפני שמירה.";
  if (error.apiError?.code === "QUALITY_ACKNOWLEDGEMENT_REQUIRED") return "יש לעיין במקור התכנון או ביתרות הישנות ולאשר אותן לפני שמירה.";
  if (error.apiError?.code === "VALIDATION_ERROR") return "בדקו את הסכומים, התאריכים וניתוב הקופות לפני חישוב או שמירה.";
  if (error.status === 0 || error.status >= 500) return "לא ידוע אם השמירה הושלמה. רעננו את התחזית לפני ניסיון נוסף.";
  return error.apiError?.message || "בדקו את הנתונים ונסו שוב.";
}

function hasUnknownMutationOutcome(error: unknown) {
  return error instanceof ApiRequestError && (error.status === 0 || error.status >= 500);
}

function itemLabel(item: PlanningItem) {
  return `${item.label} · ${item.kind === "savings_contribution" ? "הפקדה" : "משיכה"}`;
}

function ErrorBanner({ message }: { message: string }) {
  return <div className={styles.alert} role="alert">{message}</div>;
}

export function ForecastsFeature() {
  const [forecasts, setForecasts] = useState<ForecastSummary[]>([]);
  const [scenarios, setScenarios] = useState<PlanningScenario[]>([]);
  const [snapshots, setSnapshots] = useState<SnapshotSummary[]>([]);
  const [selectedForecastId, setSelectedForecastId] = useState("");
  const [revisions, setRevisions] = useState<ForecastRevisionSummary[]>([]);
  const [selectedRevisionNumber, setSelectedRevisionNumber] = useState(0);
  const [detail, setDetail] = useState<ForecastRevisionProjection | null>(null);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [sourceRevision, setSourceRevision] = useState<PlanningRevision | null>(null);
  const [planningRevisions, setPlanningRevisions] = useState<Array<{ revision_id: string; revision_number: number }>>([]);
  const [seedSnapshotId, setSeedSnapshotId] = useState("");
  const [seedRevisionSummaries, setSeedRevisionSummaries] = useState<SnapshotRevision[]>([]);
  const [seedRevision, setSeedRevision] = useState<SnapshotRevision | null>(null);
  const [seedAccountKeys, setSeedAccountKeys] = useState<string[]>([]);
  const [seedPoolTypes, setSeedPoolTypes] = useState<Record<string, ForecastPoolType>>({});
  const [horizon, setHorizon] = useState<12 | 24 | 36>(36);
  const [selectedRole, setSelectedRole] = useState<ForecastRole>("baseline");
  const [preview, setPreview] = useState<ForecastDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [unknownOperation, setUnknownOperation] = useState(readUnknownForecastMutation);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const projectionSequence = useRef(0);
  const newForecastButton = useRef<HTMLButtonElement>(null);
  const editorWasOpen = useRef(false);
  const [seedError, setSeedError] = useState("");
  const [restoreError, setRestoreError] = useState("");

  const selectedForecast = forecasts.find((item) => item.forecast_id === selectedForecastId) ?? null;
  const visibleForecasts = forecasts;
  const eligibleSeedBalances = seedRevision?.balances.filter((item) => item.side === "asset" && item.liquidity === "liquid") ?? [];
  const selectedScenario = scenarios.find((item) => item.scenario_id === editor?.scenarioId) ?? null;
  const savingItems = sourceItems(sourceRevision);

  function markUnknownOperationReconciled() {
    if (!unknownOperation) return;
    const reconciled = { ...unknownOperation, reconciled: true };
    storeUnknownForecastMutation(reconciled);
    setUnknownOperation(reconciled);
    if (unknownOperation.kind === "create") closeEditor();
  }

  async function refreshAll(preferredForecastId?: string, preferredRevisionNumber?: number): Promise<boolean> {
    const sequence = ++projectionSequence.current;
    setLoading(true);
    setError("");
    try {
      const [nextForecasts, nextScenarios, nextSnapshots] = await Promise.all([
        getForecasts(true),
        getScenarios(false).then((result) => result.data),
        getSnapshots(false),
      ]);
      if (sequence !== projectionSequence.current) return false;
      setForecasts(nextForecasts);
      setScenarios(nextScenarios);
      setSnapshots(nextSnapshots);
      const chosen = nextForecasts.find((item) => item.forecast_id === preferredForecastId)
        ?? nextForecasts.find((item) => !item.archived)
        ?? nextForecasts[0]
        ?? null;
      setSelectedForecastId(chosen?.forecast_id ?? "");
      if (!chosen) {
        setRevisions([]);
        setSelectedRevisionNumber(0);
        setDetail(null);
        markUnknownOperationReconciled();
        return true;
      }
      const nextRevisions = await getForecastRevisions(chosen.forecast_id);
      if (sequence !== projectionSequence.current) return false;
      setRevisions(nextRevisions);
      const revisionNumber = nextRevisions.some((item) => item.revision_number === preferredRevisionNumber)
        ? preferredRevisionNumber!
        : chosen.current_revision_number;
      setSelectedRevisionNumber(revisionNumber);
      const result = await getForecastProjection(chosen.forecast_id, revisionNumber);
      if (sequence !== projectionSequence.current) return false;
      setDetail(result);
      markUnknownOperationReconciled();
      return true;
    } catch (cause) {
      if (sequence === projectionSequence.current) setError(describeError(cause));
      return false;
    } finally {
      if (sequence === projectionSequence.current) setLoading(false);
    }
  }

  const editing = Boolean(editor);
  const initialRefresh = useRef(refreshAll);
  useEffect(() => { void initialRefresh.current(); }, []);
  useEffect(() => {
    if (editing) {
      document.getElementById("forecast-editor-heading")?.scrollIntoView?.({ block: "start" });
      document.getElementById("forecast-name")?.focus();
    } else if (editorWasOpen.current) newForecastButton.current?.focus();
    editorWasOpen.current = editing;
  }, [editing]);

  async function chooseForecast(forecastId: string) {
    const sequence = ++projectionSequence.current;
    setSelectedForecastId(forecastId);
    setDetail(null);
    setError("");
    const chosen = forecasts.find((item) => item.forecast_id === forecastId);
    if (!chosen) return;
    setBusy(true);
    try {
      const nextRevisions = await getForecastRevisions(forecastId);
      if (sequence !== projectionSequence.current) return;
      setRevisions(nextRevisions);
      const number = chosen.current_revision_number;
      setSelectedRevisionNumber(number);
      const result = await getForecastProjection(forecastId, number);
      if (sequence === projectionSequence.current) setDetail(result);
    } catch (cause) { if (sequence === projectionSequence.current) setError(describeError(cause)); }
    finally { if (sequence === projectionSequence.current) setBusy(false); }
  }

  async function chooseForecastRevision(revisionNumber: number) {
    if (!selectedForecast) return;
    const sequence = ++projectionSequence.current;
    setSelectedRevisionNumber(revisionNumber);
    setDetail(null);
    setBusy(true);
    setError("");
    try {
      const result = await getForecastProjection(selectedForecast.forecast_id, revisionNumber);
      if (sequence === projectionSequence.current) setDetail(result);
    } catch (cause) { if (sequence === projectionSequence.current) setError(describeError(cause)); }
    finally { if (sequence === projectionSequence.current) setBusy(false); }
  }

  async function loadScenarioRevision(scenarioId: string, revisionNumber?: number) {
    const [listResult, scenarioResult] = await Promise.all([
      getPlanningRevisions(scenarioId),
      getScenarios(true).then((result) => result.data.find((item) => item.scenario_id === scenarioId) ?? null),
    ]);
    const list = listResult.data;
    const number = revisionNumber ?? scenarioResult?.current_revision_number ?? list.at(-1)?.revision_number ?? 1;
    const revision = (await getPlanningRevision(scenarioId, number)).data;
    setPlanningRevisions(list.map((item) => ({ revision_id: item.revision_id, revision_number: item.revision_number })));
    setSourceRevision(revision);
    return { list, scenario: scenarioResult, revision };
  }

  async function startCreate() {
    if (!scenarios.length || unknownOperation) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const scenario = scenarios[0];
      const { revision } = await loadScenarioRevision(scenario.scenario_id, scenario.current_revision_number);
      const pool = emptyPool(scenario.start_month, "מזומן משפחתי");
      setEditor({
        mode: "create", step: 1, name: `${scenario.name} · תחזית חיסכון`,
        scenarioId: scenario.scenario_id, sourceRevisionNumber: revision.revision_number,
        pools: [pool], cases: defaultCases(revision, pool.name), notes: "", provisionalAcknowledged: false,
      });
      setPreview(null);
    } catch (cause) { setError(describeError(cause)); }
    finally { setBusy(false); }
  }

  async function startEdit() {
    if (!selectedForecast) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const snapshotProjection = await getForecastProjection(selectedForecast.forecast_id, selectedForecast.current_revision_number);
      const snapshot = snapshotProjection.snapshot;
      const { revision } = await loadScenarioRevision(snapshot.scenario_id, snapshot.source_revision_number);
      setEditor({
        mode: "edit", forecastId: selectedForecast.forecast_id,
        expectedRevisionNumber: selectedForecast.current_revision_number, step: 1,
        name: selectedForecast.name, scenarioId: snapshot.scenario_id,
        sourceRevisionNumber: snapshot.source_revision_number,
        pools: snapshot.starting_pools.map((pool) => ({ ...pool })),
        cases: savedCases(snapshot.cases, revision, snapshot.starting_pools[0]?.name ?? ""),
        notes: snapshot.notes, provisionalAcknowledged: snapshot.provisional_acknowledged,
      });
      setPreview(null);
    } catch (cause) { setError(describeError(cause)); }
    finally { setBusy(false); }
  }

  function closeEditor() {
    setEditor(null);
    setPreview(null);
    setSourceRevision(null);
    setError("");
    setSeedError("");
  }

  function updateEditor(change: (current: EditorState) => EditorState, clearConfirmations = true) {
    setEditor((current) => {
      if (!current) return current;
      const updated = change(current);
      return clearConfirmations ? { ...updated, cases: updated.cases.map((item) => ({ ...item, confirmed: false })) } : updated;
    });
    if (clearConfirmations) setPreview(null);
  }

  async function changeScenario(scenarioId: string) {
    const scenario = scenarios.find((item) => item.scenario_id === scenarioId);
    if (!scenario || !editor || editor.mode !== "create") return;
    setBusy(true);
    setError("");
    try {
      const { revision } = await loadScenarioRevision(scenarioId, scenario.current_revision_number);
      const pool = emptyPool(scenario.start_month, "מזומן משפחתי");
      updateEditor((current) => ({
        ...current, scenarioId, sourceRevisionNumber: revision.revision_number,
        pools: [pool], cases: defaultCases(revision, pool.name), provisionalAcknowledged: false,
      }));
    } catch (cause) { setError(describeError(cause)); }
    finally { setBusy(false); }
  }

  async function changeSourceRevision(revisionNumber: number) {
    if (!editor || editor.mode !== "create") return;
    setBusy(true);
    setError("");
    try {
      const revision = (await getPlanningRevision(editor.scenarioId, revisionNumber)).data;
      setSourceRevision(revision);
      updateEditor((current) => ({
        ...current,
        sourceRevisionNumber: revisionNumber,
        cases: current.cases.map((item) => ({
          ...item,
          routes: sourceItems(revision).map((source) => item.routes.find((route) => route.source_item_id === source.id) ?? {
            source_item_id: source.id, pool_name: current.pools[0]?.name ?? "",
          }),
        })),
      }));
    } catch (cause) { setError(describeError(cause)); }
    finally { setBusy(false); }
  }

  async function chooseSeedSnapshot(snapshotId: string) {
    setSeedSnapshotId(snapshotId);
    setSeedRevision(null);
    setSeedRevisionSummaries([]);
    setSeedAccountKeys([]);
    setSeedError("");
    if (!snapshotId) return;
    try {
      const next = await getNetWorthRevisions(snapshotId);
      setSeedRevisionSummaries(next);
      const newest = next.at(-1);
      if (!newest) return;
      setSeedRevision(newest);
      setSeedAccountKeys(newest.balances.filter((item) => item.side === "asset" && item.liquidity === "liquid").map((item) => item.account_key));
    } catch (cause) { setSeedError(describeError(cause)); }
  }

  async function chooseSeedRevision(revisionNumber: number) {
    if (!seedSnapshotId) return;
    const selected = seedRevisionSummaries.find((item) => item.revision_number === revisionNumber);
    if (!selected) return;
    setSeedError("");
    setSeedRevision(selected);
    setSeedAccountKeys(selected.balances.filter((item) => item.side === "asset" && item.liquidity === "liquid").map((item) => item.account_key));
  }

  async function addNetWorthPools() {
    if (!editor || !seedRevision || seedAccountKeys.length === 0) return;
    setBusy(true);
    setSeedError("");
    try {
      const seeds = await getNetWorthSeeds(seedRevision.revision_id, seedAccountKeys, seedPoolTypes);
      updateEditor((current) => ({
        ...current,
        pools: [
          ...current.pools,
          ...seeds.map((seed) => ({
            name: seed.name,
            pool_type: seed.pool_type,
            opening_balance: seed.opening_balance,
            as_of_date: seed.as_of_date,
            net_worth_account_key: seed.account_key,
            net_worth_snapshot_revision_id: seed.snapshot_revision_id,
            source_valuation_date: seed.valuation_date,
            source_stale: seed.stale,
            source_quality_acknowledged: false,
          })),
        ],
      }));
      setNotice("היתרות נוספו לקופות התחלתיות מתוך גרסת תמונת המצב שנבחרה.");
    } catch (cause) { setSeedError(describeError(cause)); }
    finally { setBusy(false); }
  }

  function editorPayload(current: EditorState): ForecastInputPayload {
    return {
      scenario_id: current.scenarioId,
      source_revision_number: current.sourceRevisionNumber,
      starting_pools: current.pools,
      cases: current.cases,
      notes: current.notes,
      provisional_acknowledged: current.provisionalAcknowledged,
    };
  }

  async function calculatePreview() {
    if (!editor) return;
    setBusy(true);
    setError("");
    try {
      const result = await previewForecast(editorPayload(editor));
      setPreview(result);
    } catch (cause) { setError(describeError(cause)); }
    finally { setBusy(false); }
  }

  async function saveEditor() {
    if (!editor || !preview || (unknownOperation && editor.mode === "create")) return;
    if (editor.cases.some((item) => !item.confirmed)) {
      setError("עברו על שלושת המקרים ואשרו את ההנחות בכל כרטיס לפני השמירה.");
      return;
    }
    if (sourceRevision?.provisional && !editor.provisionalAcknowledged) {
      setError("הגרסה הנבחרת זמנית. אשרו את איכות המקור לפני שמירה.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    let createRequestPending = false;
    try {
      const payload = editorPayload(editor);
      // Re-run the deterministic engine with the exact reviewed confirmation state.
      // The saved revision and the preview therefore carry the same assumptions hash.
      await previewForecast(payload);
      let saved: ForecastSummary | { forecast_id?: string; revision_number: number };
      if (editor.mode === "create") {
        createRequestPending = true;
        saved = await createForecast({ ...payload, name: editor.name });
        createRequestPending = false;
        setNotice("התחזית נשמרה בגרסה 1. ההנחות והתוצאות ההיסטוריות נשמרות כגרסה בלתי־ניתנת לשינוי.");
        closeEditor();
        await refreshAll(saved.forecast_id, saved.current_revision_number);
      } else {
        const result = await saveForecastRevision(editor.forecastId!, {
          expected_revision_number: editor.expectedRevisionNumber!,
          starting_pools: payload.starting_pools,
          cases: payload.cases,
          notes: payload.notes,
          provisional_acknowledged: payload.provisional_acknowledged,
        });
        setNotice(`נשמרה גרסה ${result.revision_number} חדשה; הגרסאות הקודמות נשארו ללא שינוי.`);
        closeEditor();
        await refreshAll(editor.forecastId, result.revision_number);
      }
    } catch (cause) {
      if (createRequestPending && hasUnknownMutationOutcome(cause)) {
        const uncertain = { kind: "create" as const, reconciled: false };
        storeUnknownForecastMutation(uncertain);
        setUnknownOperation(uncertain);
        setError("");
      } else setError(describeError(cause));
    }
    finally { setBusy(false); }
  }

  async function runAction(operation: () => Promise<unknown>, message: string, unknownKind?: "clone") {
    if (unknownOperation && unknownKind) return;
    setBusy(true);
    setError("");
    setNotice("");
    let operationPending = true;
    try {
      await operation();
      operationPending = false;
      setNotice(message);
      await refreshAll(selectedForecastId);
    } catch (cause) {
      if (operationPending && unknownKind && hasUnknownMutationOutcome(cause)) {
        const uncertain = { kind: unknownKind, reconciled: false };
        storeUnknownForecastMutation(uncertain);
        setUnknownOperation(uncertain);
        setError("");
      } else setError(describeError(cause));
    }
    finally { setBusy(false); }
  }

  function closeUnknownOperation() {
    if (!unknownOperation?.reconciled) return;
    closeEditor();
    storeUnknownForecastMutation(null);
    setUnknownOperation(null);
    setNotice("הפעולה הלא ודאית נסגרה לאחר רענון התחזיות. אפשר להתחיל פעולה חדשה.");
  }

  async function restoreSelectedRevision() {
    if (!selectedForecast || !detail) return;
    setRestoreError("");
    await runAction(async () => {
      const restored = await restoreForecastRevision(selectedForecast.forecast_id, selectedRevisionNumber, {
        expected_revision_number: selectedForecast.current_revision_number,
        provisional_acknowledged: detail.snapshot.provisional_acknowledged,
      });
      setSelectedRevisionNumber(restored.revision_number);
    }, `גרסה ${selectedRevisionNumber} שוחזרה כגרסה חדשה.`);
  }

  if (loading) return <LoadingState label="טוענים תחזיות וגרסאות שמורות…" />;
  if (error && forecasts.length === 0 && !editor) return <ErrorState description={error} onRetry={() => void refreshAll()} retrying={loading} />;

  return <div className={styles.page}>
    <div className={styles.toolbar}>
      <p>ראו איך יתרת הפתיחה, ההפקדות והנחות התשואה משפיעות על החיסכון לאורך זמן.</p>
      <div className={styles.toolbarActions}><Button variant="outline" disabled={busy} onClick={() => void refreshAll(selectedForecastId, selectedRevisionNumber || undefined)}>{unknownOperation && !unknownOperation.reconciled ? "רענון ובדיקת מצב" : "רענון"}</Button><Button ref={newForecastButton} disabled={busy || Boolean(editor) || !scenarios.length || Boolean(unknownOperation)} onClick={() => void startCreate()}>תחזית חדשה</Button></div>
    </div>
    {unknownOperation && <section className={styles.warning} role="status" aria-live="polite">
      <strong>{unknownOperation.kind === "create" ? "לא ידוע אם התחזית נוצרה." : "לא ידוע אם העותק נוצר."}</strong>
      <p>{unknownOperation.reconciled
        ? "התחזיות רועננו. בדקו ברשימה אם הפעולה הושלמה; יצירה ושכפול עדיין חסומים כדי למנוע כפילות."
        : "רעננו את התחזיות כדי לבדוק אם הפעולה הושלמה. עד אז אי אפשר לשמור או לשכפל שוב."}</p>
      {unknownOperation.reconciled
        ? <Button size="sm" variant="outline" onClick={closeUnknownOperation}>בדקתי את התחזיות וסגירת הפעולה הלא ודאית</Button>
        : <Button size="sm" variant="outline" disabled={busy} onClick={() => void refreshAll(selectedForecastId, selectedRevisionNumber || undefined)}>רענון ובדיקת מצב</Button>}
    </section>}
    {error && <ErrorBanner message={error} />}
    {notice && <div className={styles.notice} role="status">{notice}</div>}

    {editor && sourceRevision ? <Editor
      key={`${editor.scenarioId}-${editor.sourceRevisionNumber}-${editor.expectedRevisionNumber ?? "new"}`}
      editor={editor}
      setEditor={setEditor}
      updateEditor={updateEditor}
      clearPreview={() => setPreview(null)}
      closeEditor={closeEditor}
      saveEditor={() => void saveEditor()}
      saveBlocked={Boolean(unknownOperation && editor.mode === "create")}
      calculatePreview={() => void calculatePreview()}
      busy={busy}
      preview={preview}
      scenarios={scenarios}
      selectedScenario={selectedScenario}
      planningRevisions={planningRevisions}
      sourceRevision={sourceRevision}
      sourceItems={savingItems}
      onScenarioChange={(id) => void changeScenario(id)}
      onSourceRevisionChange={(number) => void changeSourceRevision(number)}
      snapshots={snapshots}
      seedSnapshotId={seedSnapshotId}
      seedRevision={seedRevision}
      seedRevisionSummaries={seedRevisionSummaries}
      seedAccountKeys={seedAccountKeys}
      seedPoolTypes={seedPoolTypes}
      seedError={seedError}
      eligibleSeedBalances={eligibleSeedBalances}
      onSeedSnapshotChange={(id) => void chooseSeedSnapshot(id)}
      onSeedRevisionChange={(number) => void chooseSeedRevision(number)}
      setSeedAccountKeys={setSeedAccountKeys}
      setSeedPoolTypes={setSeedPoolTypes}
      addNetWorthPools={() => void addNetWorthPools()}
    /> : <>
      {forecasts.length > 0 && <div className={styles.forecastControls}>
        <Field label="התחזית הנבחרת"><select aria-label="התחזית הנבחרת" value={selectedForecastId} disabled={busy} onChange={(event) => void chooseForecast(event.target.value)}>
          {visibleForecasts.map((item) => <option key={item.forecast_id} value={item.forecast_id}>{item.name}{item.archived ? " · בארכיון" : ""} · {currencyLabel(item.currency)}</option>)}
        </select></Field>
        <Button variant="outline" disabled={busy || selectedForecast?.archived} onClick={() => void startEdit()}>עריכת הנחות</Button>
      </div>}
      {busy && !detail && forecasts.length > 0 ? <LoadingState label="טוענים את גרסת התחזית שנבחרה…" /> : selectedForecast && !detail ? <ErrorState title="לא ניתן לטעון את גרסת התחזית" description={error || "רעננו את הגרסה כדי לנסות שוב."} onRetry={() => void chooseForecast(selectedForecast.forecast_id)} retrying={busy} /> : !selectedForecast || !detail ? <section className={`${styles.section} ${styles.setup}`} aria-labelledby="forecast-setup-title">
        <h2 id="forecast-setup-title">איך החיסכון שלכם יכול להתפתח?</h2>
        <p>{scenarios.length ? "מתחילים בתכנון קיים, מוסיפים את הכסף שכבר חסכתם ומשווים בין שלוש הנחות תשואה." : "תחילה בונים תקציב עם הכנסות, הוצאות והעברות לחיסכון. אחר כך אפשר להוסיף יתרת פתיחה ולבנות תחזית."}</p>
        <div className={styles.actionRow}>{!scenarios.length ? <Link className={buttonVariants()} href="/planning">יצירת תקציב</Link> : !unknownOperation && <Button onClick={() => void startCreate()}>יצירת תחזית</Button>}</div>
        <ol className={styles.setupSteps}><li><strong>בוחרים תכנון</strong><span>הפקדות ומשיכות מהגרסה שנבחרה.</span></li><li><strong>מוסיפים יתרת פתיחה</strong><span>הכסף שכבר נמצא בקופות בתחילת התחזית.</span></li><li><strong>משווים תוצאות</strong><span>הפרדה בין הפקדות לבין תשואה משוערת.</span></li></ol>
      </section> : <>
        {selectedRevisionNumber !== selectedForecast.current_revision_number && <div className={styles.warning}>מוצגת גרסה היסטורית {selectedRevisionNumber}. עריכת הנחות מתחילה מהגרסה העדכנית {selectedForecast.current_revision_number}.</div>}
        {selectedForecast.archived && <div className={styles.warning}>התחזית בארכיון. אפשר לעיין בה או להחזיר אותה דרך כלי הניהול.</div>}
        {detail.source_verification.at_creation.provisional && <div className={styles.warning}>תחזית זו מבוססת על מקור תכנון חלקי או זמני. פרטי הכיסוי והאישור זמינים בכלי הניהול.</div>}
        <ForecastResults key={`${selectedForecast.forecast_id}-${detail.snapshot.revision_number}`}
          draft={detail.draft} snapshot={detail.snapshot} horizon={horizon} setHorizon={setHorizon}
          selectedRole={selectedRole} setSelectedRole={setSelectedRole} />
        <details className={`${styles.section} ${styles.disclosure}`} aria-label="מקורות, גרסאות וניהול"><summary><span>מקורות, גרסאות וניהול<small>תכנון המקור, היסטוריה, שכפול וארכיון</small></span><ChevronDown size={18} aria-hidden="true" /></summary>
        <section className={styles.section} aria-labelledby="forecast-detail-heading">
          <div className={styles.sectionHeading}><div><span className={styles.eyebrow}>תוצאות מחושבות · לא יתרות שנמדדו</span><h3 id="forecast-detail-heading">{selectedForecast.name}</h3><p>{currencyLabel(detail.snapshot.currency)} · 36 חודשים · גרסת תחזית {detail.snapshot.revision_number}</p></div><div className={styles.actionRow}>
            <Button size="sm" variant="outline" onClick={() => void runAction(() => cloneForecast(selectedForecast.forecast_id), "נוצר עותק חדש של התחזית.", "clone")} disabled={busy || Boolean(unknownOperation)}>שכפול</Button>
            <Button size="sm" variant="outline" onClick={() => void runAction(() => setForecastArchived(selectedForecast.forecast_id, !selectedForecast.archived), selectedForecast.archived ? "התחזית הוחזרה מהארכיון." : "התחזית הועברה לארכיון.")} disabled={busy}>{selectedForecast.archived ? "החזרה מהארכיון" : "העברה לארכיון"}</Button>
          </div></div>
          <details className={styles.assumptionDetails}><summary>מקורות ופרטים טכניים</summary><div className={styles.summaryMeta}>
            <span>תרחיש תכנון: <bdi>{detail.snapshot.scenario_id}</bdi></span>
            <span>גרסת מקור נעולה: <bdi>{detail.snapshot.source_revision_number}</bdi></span>
            <span>גיבוב הנחות: <code dir="ltr">{detail.snapshot.assumption_hash.slice(0, 18)}…</code></span>
            <span>מקור הון: {detail.snapshot.net_worth_snapshot_revision_id ? "יתרות מתמונת הון מדודה" : "יתרות פתיחה ידניות"}</span>
          </div>
          </details>
          {detail.source_verification.at_creation.provisional && <div className={styles.warning}><strong>איכות מקור התכנון בעת השמירה:</strong> זמנית · {detail.source_verification.at_creation.issue_codes.join(" · ") || "נדרשה סקירת מקור"} · אישור נשמר: {detail.snapshot.provisional_acknowledged ? "כן" : "לא"}</div>}
          <div className={styles.verificationGrid}>
            <VerificationCard title="אימות המקור בעת השמירה" value={detail.source_verification.at_creation} />
            <VerificationCard title="אימות תרחיש התכנון כעת" value={detail.source_verification.current} />
          </div>
          <div className={styles.revisionBar}>
            <label className={styles.field}><span>גרסת תחזית לבדיקה</span><select value={selectedRevisionNumber} onChange={(event) => void chooseForecastRevision(Number(event.target.value))}>{revisions.map((revision) => <option key={revision.revision_id} value={revision.revision_number}>גרסה {revision.revision_number} · {revision.created_at ? formatHebrewDate(revision.created_at.slice(0, 10)) : "תאריך לא זמין"}</option>)}</select></label>
            <span className={styles.badge}>{selectedRevisionNumber === selectedForecast.current_revision_number ? "הגרסה הנוכחית" : "גרסה היסטורית"}</span>
            {selectedRevisionNumber < selectedForecast.current_revision_number && <Button size="sm" variant="outline" disabled={busy || selectedForecast.archived} onClick={() => void restoreSelectedRevision()}>שחזור כגרסה חדשה</Button>}
          </div>
          {restoreError && <ErrorBanner message={restoreError} />}
        </section>
        </details>
      </>}
    </>}
  </div>;
}

type EditorProps = {
  editor: EditorState;
  setEditor: React.Dispatch<React.SetStateAction<EditorState | null>>;
  updateEditor: (change: (current: EditorState) => EditorState, clearConfirmations?: boolean) => void;
  clearPreview: () => void;
  closeEditor: () => void;
  saveEditor: () => void;
  saveBlocked: boolean;
  calculatePreview: () => void;
  busy: boolean;
  preview: ForecastDraft | null;
  scenarios: PlanningScenario[];
  selectedScenario: PlanningScenario | null;
  planningRevisions: Array<{ revision_id: string; revision_number: number }>;
  sourceRevision: PlanningRevision;
  sourceItems: PlanningItem[];
  onScenarioChange: (id: string) => void;
  onSourceRevisionChange: (number: number) => void;
  snapshots: SnapshotSummary[];
  seedSnapshotId: string;
  seedRevision: SnapshotRevision | null;
  seedRevisionSummaries: Array<{ revision_id: string; revision_number: number }>;
  seedAccountKeys: string[];
  seedPoolTypes: Record<string, ForecastPoolType>;
  seedError: string;
  eligibleSeedBalances: SnapshotRevision["balances"];
  onSeedSnapshotChange: (id: string) => void;
  onSeedRevisionChange: (number: number) => void;
  setSeedAccountKeys: (keys: string[]) => void;
  setSeedPoolTypes: (types: Record<string, ForecastPoolType>) => void;
  addNetWorthPools: () => void;
};

function Editor(props: EditorProps) {
  const {
    editor, updateEditor, clearPreview, closeEditor, saveEditor, saveBlocked, calculatePreview, busy, preview,
    scenarios, selectedScenario, planningRevisions, sourceRevision, sourceItems, onScenarioChange,
    onSourceRevisionChange, snapshots, seedSnapshotId, seedRevision, seedRevisionSummaries,
    seedAccountKeys, seedPoolTypes, seedError, eligibleSeedBalances, onSeedSnapshotChange,
    onSeedRevisionChange, setSeedAccountKeys, setSeedPoolTypes, addNetWorthPools,
  } = props;
  const allConfirmed = editor.cases.length === 3 && editor.cases.every((item) => item.confirmed);
  const stalePools = editor.pools.filter((pool) => pool.source_stale);
  const seedStartMonth = seedRevision ? forecastStartMonth(seedRevision.snapshot_date) : null;
  const seedMatchesScenario = Boolean(seedStartMonth && selectedScenario?.start_month === seedStartMonth);
  const canSave = Boolean(preview) && allConfirmed && (!sourceRevision.provisional || editor.provisionalAcknowledged)
    && stalePools.every((pool) => pool.source_quality_acknowledged);

  function patchCase(role: ForecastRole, change: (item: ForecastCase) => ForecastCase, clearConfirmation = true) {
    updateEditor((current) => ({
      ...current,
      cases: current.cases.map((item) => {
        if (item.role !== role) return item;
        const changed = change(item);
        return { ...changed, confirmed: clearConfirmation ? false : changed.confirmed };
      }),
    }), false);
    if (clearConfirmation) {
      clearPreview();
      props.setEditor((current) => current ? { ...current, cases: current.cases.map((item) => item.role === role ? { ...item, confirmed: false } : item) } : current);
    }
  }

  function patchPool(index: number, patch: Partial<ForecastPool>) {
    updateEditor((current) => ({
      ...current,
      pools: current.pools.map((pool, itemIndex) => itemIndex === index ? { ...pool, ...patch } : pool),
      cases: patch.name === undefined ? current.cases : current.cases.map((item) => ({
        ...item,
        routes: item.routes.map((route) => route.pool_name === current.pools[index].name ? { ...route, pool_name: patch.name! } : route),
        sweep_pool_name: item.sweep_pool_name === current.pools[index].name ? patch.name! : item.sweep_pool_name,
        events: item.events.map((event) => event.pool_name === current.pools[index].name ? { ...event, pool_name: patch.name! } : event),
      })),
    }));
  }

  function addPool() {
    if (!selectedScenario) return;
    const nextNumber = editor.pools.length + 1;
    updateEditor((current) => ({ ...current, pools: [...current.pools, emptyPool(selectedScenario.start_month, `קופה ${nextNumber}`)] }));
  }

  const previewBaseline = preview?.projections.baseline;

  return <section className={styles.editor} aria-labelledby="forecast-editor-heading">
    <div className={styles.editorHeading}><div><span className={styles.eyebrow}>{editor.mode === "create" ? "בונה תחזית חדשה" : `גרסה ${editor.expectedRevisionNumber} · עריכת הנחות`}</span><h3 id="forecast-editor-heading">{editor.mode === "create" ? "תחזית חיסכון" : editor.name}</h3><p>שלושה שלבים: מקור תכנון, יתרות פתיחה, מקרי תחזית ותוצאות.</p></div><button type="button" className={styles.textButton} onClick={closeEditor}>סגירת העורך</button></div>
    <ol className={styles.steps} aria-label="שלבי עריכת התחזית">
      {["מקור תכנון", "יתרות פתיחה", "מקרי תחזית"].map((label, index) => <li key={label} aria-current={editor.step === index + 1 ? "step" : undefined} className={editor.step === index + 1 ? styles.activeStep : editor.step > index + 1 ? styles.completeStep : ""}><span>{index + 1}</span>{label}</li>)}
    </ol>

    {editor.step === 1 && <div className={styles.stepContent}>
      <div className={styles.formGrid}>
        {editor.mode === "create" ? <Field label="תרחיש תכנון"><select aria-label="תרחיש תכנון" value={editor.scenarioId} onChange={(event) => onScenarioChange(event.target.value)}>{scenarios.map((scenario) => <option key={scenario.scenario_id} value={scenario.scenario_id}>{scenario.name} · {scenario.currency}</option>)}</select></Field> : <Field label="תרחיש תכנון"><input disabled value={`${selectedScenario?.name ?? editor.scenarioId} · ${selectedScenario?.currency ?? ""}`} /></Field>}
        {editor.mode === "create" ? <Field label="גרסת תכנון מדויקת"><select aria-label="גרסת תכנון מדויקת" value={editor.sourceRevisionNumber} onChange={(event) => onSourceRevisionChange(Number(event.target.value))}>{planningRevisions.map((revision) => <option key={revision.revision_id} value={revision.revision_number}>גרסה {revision.revision_number}</option>)}</select></Field> : <Field label="גרסת תכנון נעולה"><input disabled value={`גרסה ${editor.sourceRevisionNumber} · ${sourceRevision.revision_id.slice(0, 12)}`} /></Field>}
        <Field label="שם התחזית"><input id="forecast-name" aria-label="שם התחזית" maxLength={200} value={editor.name} onChange={(event) => updateEditor((current) => ({ ...current, name: event.target.value }), false)} /></Field>
      </div>
      <div className={styles.referenceCard}><strong>{selectedScenario?.name ?? "תכנון המקור"} · גרסה {sourceRevision.revision_number}</strong><span>{selectedScenario ? `${formatHebrewMonth(selectedScenario.start_month)} עד ${formatHebrewMonth(selectedScenario.end_month)}` : "גרסת התכנון שנשמרה עם התחזית"}. תנועות חודשיות חוזרות גם בשנים הבאות; אירועים חד־פעמיים אינם חוזרים.</span><details><summary>מזהי מקור</summary><code dir="ltr">{editor.scenarioId} · {sourceRevision.revision_id}</code></details></div>
      {sourceRevision.provisional && <div className={styles.warning}><strong>הגרסה הזמנית כוללת:</strong> {sourceRevision.issue_codes.join(" · ") || "פערי איכות במקור"}<label className={styles.check}><input type="checkbox" checked={editor.provisionalAcknowledged} onChange={(event) => updateEditor((current) => ({ ...current, provisionalAcknowledged: event.target.checked }), false)} /> קראתי ואישרתי את מצב מקור התכנון הזה.</label></div>}
      {sourceItems.length > 0 && <div className={styles.referenceCard}><strong>תנועות חיסכון והעברה מהמקור</strong>{sourceItems.map((item) => <span key={item.id}>{itemLabel(item)} · {formatMoney(item.amount, selectedScenario?.currency ?? "ILS")}</span>)}</div>}
      <Field label="הערות לגרסה"><textarea rows={3} maxLength={2000} value={editor.notes} onChange={(event) => updateEditor((current) => ({ ...current, notes: event.target.value }), false)} /></Field>
      <div className={styles.formActions}><Button onClick={() => updateEditor((current) => ({ ...current, step: 2 }), false)}>המשך ליתרות פתיחה</Button><Button variant="outline" onClick={closeEditor}>ביטול</Button></div>
    </div>}

    {editor.step === 2 && <div className={styles.stepContent}>
      <div className={styles.sectionHeading}><div><h4>קופות ויתרות פתיחה</h4><p>הזינו את הכסף שכבר נמצא בכל קופה בתחילת התחזית. ההפקדות העתידיות יתווספו בנפרד מתכנון המקור.</p></div><Button size="sm" variant="outline" onClick={addPool}>הוספת קופה ידנית</Button></div>
      <div className={styles.poolGrid}>{editor.pools.map((pool, index) => <article className={styles.poolCard} key={`pool-${index}`}>
        <div className={styles.cardTop}><strong>{pool.net_worth_account_key ? "יתרה שנמדדה" : "יתרה ידנית"}</strong><button type="button" className={styles.textButton} disabled={editor.pools.length <= 1} onClick={() => updateEditor((current) => ({ ...current, pools: current.pools.filter((_, itemIndex) => itemIndex !== index) }))}>הסרה</button></div>
        <div className={styles.formGrid}>
          <Field label="שם הקופה"><input aria-label={`שם קופה ${index + 1}`} required maxLength={200} value={pool.name} onChange={(event) => patchPool(index, { name: event.target.value })} /></Field>
          <Field label="סוג"><select aria-label={`סוג קופה ${index + 1}`} value={pool.pool_type} onChange={(event) => patchPool(index, { pool_type: event.target.value as ForecastPoolType })}><option value="cash">מזומן או חיסכון</option><option value="investment">השקעה</option></select></Field>
          <Field label={`יתרת פתיחה (${currencyLabel(selectedScenario?.currency ?? "ILS")})`}><input aria-label={`יתרת פתיחה קופה ${index + 1}`} dir="ltr" inputMode="decimal" required value={pool.opening_balance} onChange={(event) => patchPool(index, { opening_balance: event.target.value })} /></Field>
          <Field label="נכון לתאריך"><input aria-label={`תאריך יתרת פתיחה קופה ${index + 1}`} type="date" required value={pool.as_of_date} onChange={(event) => patchPool(index, { as_of_date: event.target.value })} /></Field>
        </div>
        {pool.net_worth_account_key && <div className={styles.sourceReference}><span>מקור חשבון: {pool.net_worth_account_key} · הערכה {pool.source_valuation_date ? formatHebrewDate(pool.source_valuation_date) : "לא זמין"}</span><code dir="ltr">{pool.net_worth_snapshot_revision_id}</code></div>}
        {pool.source_stale && <label className={styles.check}><input type="checkbox" checked={Boolean(pool.source_quality_acknowledged)} onChange={(event) => patchPool(index, { source_quality_acknowledged: event.target.checked })} /> אני מאשר/ת את יתרת המקור הישנה לקופה זו.</label>}
      </article>)}</div>

      {snapshots.length > 0 && <details className={styles.seedPanel}>
        <summary>בחירת יתרות מתוך הון משפחתי מדוד</summary>
        <p>המערכת תשתמש בחשבונות נכס נזילים בלבד ותשמור את מזהה הגרסה המדויקת ואת תאריך ההערכה.</p>
        <div className={styles.formGrid}>
          <Field label="תמונת מצב"><select aria-label="תמונת מצב ליתרות פתיחה" value={seedSnapshotId} onChange={(event) => onSeedSnapshotChange(event.target.value)}><option value="">בחירת תאריך תמונה</option>{snapshots.filter((item) => !item.archived).map((item) => <option key={item.snapshot_id} value={item.snapshot_id}>{formatHebrewDate(item.snapshot_date)} · גרסה {item.current_revision_number}</option>)}</select></Field>
          <Field label="גרסת תמונת מצב"><select aria-label="גרסת תמונת מצב ליתרות פתיחה" value={seedRevision?.revision_number ?? ""} onChange={(event) => onSeedRevisionChange(Number(event.target.value))}><option value="">בחירת גרסה</option>{seedRevisionSummaries.map((revision) => <option key={revision.revision_id} value={revision.revision_number}>גרסה {revision.revision_number}</option>)}</select></Field>
        </div>
        <div className={styles.seedAccounts}>{eligibleSeedBalances.map((balance) => <label className={styles.seedAccount} key={balance.account_key}>
          <input type="checkbox" checked={seedAccountKeys.includes(balance.account_key)} onChange={(event) => setSeedAccountKeys(event.target.checked ? [...seedAccountKeys, balance.account_key] : seedAccountKeys.filter((key) => key !== balance.account_key))} />
          <span><strong>{balance.account_name}</strong><small>{balance.account_key} · {formatMoney(balance.amount_ils, "ILS")} · הערכה {formatHebrewDate(balance.valuation_date)}{balance.stale ? " · הערכה ישנה" : ""}</small></span>
          <select aria-label={`סוג קופה לחשבון ${balance.account_name}`} value={seedPoolTypes[balance.account_key] ?? "cash"} onChange={(event) => setSeedPoolTypes({ ...seedPoolTypes, [balance.account_key]: event.target.value as ForecastPoolType })}><option value="cash">מזומן או חיסכון</option><option value="investment">השקעה</option></select>
        </label>)}</div>
        {seedRevision && <div className={styles.sourceReference}>גרסה נעולה <code dir="ltr">{seedRevision.revision_id}</code> · תאריך {seedRevision.snapshot_date} · {!seedStartMonth ? "אפשר להשתמש ביתרה רק מתמונת מצב של תחילת חודש או מסופו." : !seedMatchesScenario ? `תאריך זה מתאים לתרחיש שמתחיל ב־${seedStartMonth}, והתרחיש הנבחר מתחיל ב־${selectedScenario?.start_month}.` : `תחזית מתחילה ב־${seedStartMonth}`}</div>}
        {seedError && <ErrorBanner message={seedError} />}
        <Button type="button" variant="outline" disabled={busy || !seedRevision || !seedMatchesScenario || !seedAccountKeys.length} onClick={addNetWorthPools}>הוספת חשבונות נבחרים כקופות</Button>
      </details>}
      <div className={styles.formActions}><Button variant="outline" onClick={() => updateEditor((current) => ({ ...current, step: 1 }), false)}>חזרה למקור</Button><Button onClick={() => updateEditor((current) => ({ ...current, step: 3 }), false)}>המשך למקרי תחזית</Button></div>
    </div>}

    {editor.step === 3 && <div className={styles.stepContent}>
      <div className={styles.sectionHeading}><div><h4>הנחות בשלושה מקרי תחזית</h4><p>המספרים הם הנחות שתוכלו לשנות. התשואה השנתית חלה על כל הקופות; סוג הקופה אינו קובע שיעור נפרד.</p></div></div>
      <div className={styles.caseEditors}>{roles.map((role) => {
        const selected = editor.cases.find((item) => item.role === role)!;
        return <CaseEditor key={role} item={selected} pools={editor.pools} items={sourceItems} currency={selectedScenario?.currency ?? "ILS"} startMonth={selectedScenario?.start_month ?? editor.pools[0]?.as_of_date ?? ""}
          onChange={(next) => patchCase(role, () => next)} onConfirm={(confirmed) => patchCase(role, (item) => ({ ...item, confirmed }), false)} />;
      })}</div>
      <div className={styles.formGrid}><Field label="הערות לגרסה"><textarea rows={2} maxLength={2000} value={editor.notes} onChange={(event) => updateEditor((current) => ({ ...current, notes: event.target.value }), false)} /></Field></div>
      <div className={styles.formActions}><Button variant="outline" onClick={() => updateEditor((current) => ({ ...current, step: 2 }), false)}>חזרה ליתרות</Button><Button onClick={calculatePreview} disabled={busy}>{busy ? "מחשב…" : "חישוב תצוגה מקדימה"}</Button></div>
      {preview && previewBaseline && <>
        <ForecastResults draft={preview} snapshot={null} horizon={36} setHorizon={() => undefined} selectedRole="baseline" setSelectedRole={() => undefined} compact />
        {sourceRevision.provisional && <div className={styles.warning}><strong>הגרסה הזמנית כוללת:</strong> {sourceRevision.issue_codes.join(" · ")}<label className={styles.check}><input type="checkbox" checked={editor.provisionalAcknowledged} onChange={(event) => updateEditor((current) => ({ ...current, provisionalAcknowledged: event.target.checked }), false)} /> אני מאשר/ת במפורש מקור תכנון זמני זה.</label></div>}
        <div className={styles.confirmations}><strong>אישור הנחות לפני שמירה</strong><p>שינוי בקלט מנקה את האישורים ומחייב חישוב תצוגה מקדימה נוסף.</p><div className={styles.confirmGrid}>{roles.map((role) => <label className={styles.check} key={role}><input type="checkbox" checked={editor.cases.find((item) => item.role === role)?.confirmed ?? false} onChange={(event) => patchCase(role, (item) => ({ ...item, confirmed: event.target.checked }), false)} /> בדקתי ואישרתי את המקרה {roleLabels[role]}.</label>)}</div></div>
        {stalePools.length > 0 && !stalePools.every((pool) => pool.source_quality_acknowledged) && <div className={styles.warning}>יש לאשר את אזהרות יתרות המקור הישנות לכל קופה לפני שמירה.</div>}
        <div className={styles.formActions}><Button onClick={saveEditor} disabled={busy || saveBlocked || !canSave}>{busy ? "שומר…" : editor.mode === "create" ? "שמירת תחזית" : "שמירת גרסה חדשה"}</Button>{editor.mode === "edit" && <span className={styles.muted}>השמירה תיצור גרסה {editor.expectedRevisionNumber! + 1} ותשאיר גרסאות קודמות ללא שינוי.</span>}</div>
      </>}
    </div>}
  </section>;
}

function CaseEditor({ item, pools, items, currency, startMonth, onChange, onConfirm }: {
  item: ForecastCase;
  pools: ForecastPool[];
  items: PlanningItem[];
  currency: string;
  startMonth: string;
  onChange: (item: ForecastCase) => void;
  onConfirm: (confirmed: boolean) => void;
}) {
  const [returnPercent, setReturnPercent] = useState(formatRateAsPercent(item.annual_return_rate));
  useEffect(() => setReturnPercent(formatRateAsPercent(item.annual_return_rate)), [item.role, item.annual_return_rate]);

  function update(patch: Partial<ForecastCase>) { onChange({ ...item, ...patch, confirmed: false }); }
  function changeAdjustment(index: number, patch: Partial<ForecastAdjustment>) {
    update({ adjustments: item.adjustments.map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row) });
  }
  function changeEvent(index: number, patch: Partial<ForecastEvent>) {
    update({ events: item.events.map((row, rowIndex) => {
      if (rowIndex !== index) return row;
      const next = { ...row, ...patch };
      if (next.event_type === "income" || next.event_type === "expense") next.pool_name = null;
      else if (!next.pool_name) next.pool_name = pools[0]?.name ?? null;
      return next;
    }) });
  }

  return <article className={styles.caseEditor} aria-labelledby={`case-${item.role}`}>
    <div className={styles.caseTitle}><div><span className={styles.caseDot} style={{ background: roleColors[item.role] }} /><h5 id={`case-${item.role}`}>{roleLabels[item.role]}</h5></div><span className={styles.badge}>מקרה 36 חודשים</span></div>
    <div className={styles.formGrid}>
      <Field label="תשואה שנתית אפקטיבית (%)"><input aria-label={`תשואה שנתית ${roleLabels[item.role]}`} inputMode="decimal" value={returnPercent} onChange={(event) => { setReturnPercent(event.target.value); update({ annual_return_rate: percentToRate(event.target.value) }); }} /></Field>
      <label className={styles.check}><input type="checkbox" checked={item.sweep_enabled} onChange={(event) => update({ sweep_enabled: event.target.checked, sweep_pool_name: event.target.checked ? item.sweep_pool_name ?? pools[0]?.name ?? null : null })} /> העברת עודף מזומנים לקופה</label>
      {item.sweep_enabled && <Field label="קופת יעד לעודף"><select aria-label={`קופת יעד ${roleLabels[item.role]}`} value={item.sweep_pool_name ?? ""} onChange={(event) => update({ sweep_pool_name: event.target.value })}>{pools.map((pool) => <option key={pool.name} value={pool.name}>{pool.name}</option>)}</select></Field>}
    </div>

    <details className={styles.assumptionDetails} open={items.length > 0}>
      <summary>ניתוב הפקדות ומשיכות מתרחיש התכנון ({items.length})</summary>
      {items.length === 0 ? <p className={styles.muted}>בתרחיש אין כרגע שורות הפקדה או משיכה.</p> : items.map((source) => <Field key={source.id} label={itemLabel(source)}><select aria-label={`ניתוב ${roleLabels[item.role]} ${source.label}`} value={item.routes.find((route) => route.source_item_id === source.id)?.pool_name ?? ""} onChange={(event) => update({ routes: [...item.routes.filter((route) => route.source_item_id !== source.id), { source_item_id: source.id, pool_name: event.target.value }] })}><option value="" disabled>בחירת קופה</option>{pools.map((pool) => <option key={pool.name} value={pool.name}>{pool.name}</option>)}</select></Field>)}
    </details>

    <details className={styles.assumptionDetails}>
      <summary>התאמות לסכומי תכנון ({item.adjustments.length})</summary>
      <p className={styles.muted}>התאמה מחליפה, מוסיפה או משנה באחוזים סכום של שורה או קטגוריה בחודשים שנבחרו.</p>
      {item.adjustments.map((adjustment, index) => <div className={styles.inputRow} key={`adjustment-${index}`}>
        <Field label="סוג יעד"><select value={adjustment.target_type} onChange={(event) => changeAdjustment(index, { target_type: event.target.value as ForecastAdjustment["target_type"], target: "" })}><option value="line">שורת תכנון</option><option value="category">קטגוריה</option></select></Field>
        <Field label="שורה"><select aria-label={`יעד התאמה ${index + 1}`} value={adjustment.target_type === "line" && items.some((source) => source.id === adjustment.target) ? adjustment.target : ""} onChange={(event) => changeAdjustment(index, { target: event.target.value })}><option value="">בחירת שורה</option>{items.map((source) => <option key={source.id} value={source.id}>{itemLabel(source)}</option>)}</select></Field>
        {adjustment.target_type === "category" && <Field label="שם קטגוריה"><input value={adjustment.target} onChange={(event) => changeAdjustment(index, { target: event.target.value })} /></Field>}
        <Field label="פעולה"><select value={adjustment.operation} onChange={(event) => changeAdjustment(index, { operation: event.target.value as ForecastAdjustmentOperation })}><option value="replacement">החלפת סכום</option><option value="fixed_delta">תוספת או הפחתה</option><option value="percentage_change">שינוי באחוזים</option></select></Field>
        <Field label="ערך"><input inputMode="decimal" value={adjustment.value} onChange={(event) => changeAdjustment(index, { value: event.target.value })} /></Field>
        <MonthPicker label={`תחילת התאמה ${index + 1} · ${roleLabels[item.role]}`} showLabel value={forecastMonth(startMonth, adjustment.start_month)} min={forecastMonth(startMonth, 1)} max={forecastMonth(startMonth, 36)} onChange={(value) => changeAdjustment(index, { start_month: forecastMonthNumber(startMonth, value) })} />
        <MonthPicker label={`סיום התאמה ${index + 1} · ${roleLabels[item.role]}`} showLabel value={forecastMonth(startMonth, adjustment.end_month ?? 36)} min={forecastMonth(startMonth, adjustment.start_month)} max={forecastMonth(startMonth, 36)} onChange={(value) => changeAdjustment(index, { end_month: forecastMonthNumber(startMonth, value) })} />
        <button type="button" className={styles.textButton} onClick={() => update({ adjustments: item.adjustments.filter((_, rowIndex) => rowIndex !== index) })}>הסרת התאמה</button>
      </div>)}
      <Button size="sm" variant="outline" onClick={() => update({ adjustments: [...item.adjustments, { target_type: "line", target: "", operation: "fixed_delta", value: "0", start_month: 1, end_month: null }] })}>הוספת התאמה</Button>
    </details>

    <details className={styles.assumptionDetails}>
      <summary>אירועים חד־פעמיים או העברות ({item.events.length})</summary>
      {item.events.map((event, index) => <div className={styles.inputRow} key={`event-${index}`}>
        <Field label="סוג אירוע"><select value={event.event_type} onChange={(change) => changeEvent(index, { event_type: change.target.value as ForecastEventType })}>{eventTypes.map((type) => <option key={type} value={type}>{eventLabels[type]}</option>)}</select></Field>
        <MonthPicker label={`חודש אירוע ${index + 1} · ${roleLabels[item.role]}`} showLabel value={forecastMonth(startMonth, event.month)} min={forecastMonth(startMonth, 1)} max={forecastMonth(startMonth, 36)} onChange={(value) => changeEvent(index, { month: forecastMonthNumber(startMonth, value) })} />
        <Field label={`סכום (${currency})`}><input inputMode="decimal" value={event.amount} onChange={(change) => changeEvent(index, { amount: change.target.value })} /></Field>
        <Field label="תיאור"><input maxLength={200} value={event.label} onChange={(change) => changeEvent(index, { label: change.target.value })} /></Field>
        {(event.event_type === "contribution" || event.event_type === "withdrawal") && <Field label="קופת יעד"><select value={event.pool_name ?? ""} onChange={(change) => changeEvent(index, { pool_name: change.target.value })}>{pools.map((pool) => <option key={pool.name} value={pool.name}>{pool.name}</option>)}</select></Field>}
        <button type="button" className={styles.textButton} onClick={() => update({ events: item.events.filter((_, rowIndex) => rowIndex !== index) })}>הסרת אירוע</button>
      </div>)}
      <Button size="sm" variant="outline" onClick={() => update({ events: [...item.events, { event_type: "expense", month: 1, amount: "0", label: "אירוע חד־פעמי", pool_name: null }] })}>הוספת אירוע</Button>
    </details>
    <label className={styles.check}><input type="checkbox" checked={item.confirmed} onChange={(event) => onConfirm(event.target.checked)} /> עברתי על ההנחות ואישרתי את המקרה {roleLabels[item.role]}.</label>
  </article>;
}

export function ForecastResults({ draft, snapshot, horizon, setHorizon, selectedRole, setSelectedRole, compact = false }: {
  draft: ForecastDraft;
  snapshot: ForecastRevisionProjection["snapshot"] | null;
  horizon: 12 | 24 | 36;
  setHorizon: (value: 12 | 24 | 36) => void;
  selectedRole: ForecastRole;
  setSelectedRole: (role: ForecastRole) => void;
  compact?: boolean;
}) {
  const projectionByRole = draft.projections;
  const currency = projectionByRole.baseline.currency;
  const currentProjection = projectionByRole[selectedRole];
  const currentMonths = currentProjection.months.slice(0, horizon);
  const [selectedMonth, setSelectedMonth] = useState("");
  const visibleMonth = currentMonths.find((month) => month.month.slice(0, 7) === selectedMonth) ?? currentMonths[0];
  const terminal = currentMonths.at(-1);
  const point = draft.comparison?.checkpoints[selectedRole]?.find((item) => item.horizon_month === horizon);
  const opening = currentProjection.months[0]?.pools.length
    ? sumDisplayAmounts(currentProjection.months[0].pools.map((pool) => pool.opening_balance)) : null;
  const firstShortfall = currentProjection.first_shortfall_month;
  const shortfall = firstShortfall && firstShortfall <= horizon ? currentProjection.months[firstShortfall - 1] : null;
  const titleId = compact ? "forecast-preview-title" : "forecast-results-title";

  return <section className={`${styles.section} ${compact ? styles.compactResults : ""}`} aria-labelledby={titleId}>
    <div className={styles.sectionHeading}><div><h2 id={titleId}>{compact ? "תצוגה מקדימה" : "החיסכון הצפוי"} · {horizon} חודשים</h2><p>{currentMonths[0] && formatHebrewMonth(currentMonths[0].month)} עד {terminal && formatHebrewMonth(terminal.month)} · הנחות עבודה, לא יתרה שנמדדה.</p></div>{!compact && <Field label="תקופת התחזית"><select aria-label="אופק תחזית" value={horizon} onChange={(event) => setHorizon(Number(event.target.value) as 12 | 24 | 36)}><option value={12}>12 חודשים</option><option value={24}>24 חודשים</option><option value={36}>36 חודשים</option></select></Field>}</div>
    <div className={styles.forecastMetrics} aria-label={`הרכב תחזית ${roleLabels[selectedRole]}`}>
      <div className={`${styles.forecastMetric} ${styles.endingMetric}`}><span>יתרה צפויה · {roleLabels[selectedRole]}</span><strong>{formatMoney(terminal?.ending_balance, currency)}</strong></div>
      <div className={styles.forecastMetric}><span>יתרה בתחילת התחזית</span><strong>{formatMoney(opening, currency)}</strong></div>
      <div className={styles.forecastMetric}><span>הפקדות לאורך התקופה</span><strong>{formatMoney(point?.contributions, currency)}</strong></div>
      <div className={styles.forecastMetric}><span>תשואה משוערת לאורך התקופה</span><strong>{formatMoney(point?.estimated_returns, currency)}</strong></div>
    </div>
    <p className={styles.balanceExplanation}>היתרה הצפויה כוללת את יתרת הפתיחה, ההפקדות והתשואה המשוערת, בתוספת עודפים שהועברו ובניכוי משיכות. עודפים שהועברו: <bdi>{formatMoney(point?.swept_surplus, currency)}</bdi> · משיכות שמומנו בתחזית: <bdi>{formatMoney(point?.withdrawals, currency)}</bdi>.</p>
    {shortfall && <div className={styles.warning} role="status">חלק מהמשיכות המתוכננות אינן מכוסות ביתרות הקופות. הפער הראשון מופיע ב{formatHebrewMonth(shortfall.month)}.</div>}
    {currentProjection.provisional && <div className={styles.warning}>התחזית מבוססת על תכנון חלקי או זמני: {currentProjection.issue_codes.map(issueLabel).join(" · ") || "נדרשת בדיקת מקור"}.</div>}
    <div className={styles.caseSummaryGrid} role="group" aria-label="השוואת הנחות תשואה">
      {roles.map((role) => {
        const ending = projectionByRole[role].months[horizon - 1];
        const assumption = snapshot?.cases.find((item) => item.role === role);
        const content = <><span>{roleLabels[role]}{assumption ? ` · ${formatRateAsPercent(assumption.annual_return_rate)}% לשנה` : ""}</span><strong>{formatMoney(ending?.ending_balance, currency)}</strong><small>יתרה צפויה בסוף התקופה</small></>;
        return compact ? <article className={styles.caseSummary} key={role}>{content}</article> : <button type="button" aria-pressed={role === selectedRole} className={`${styles.caseSummary} ${role === selectedRole ? styles.activeCase : ""}`} key={role} onClick={() => setSelectedRole(role)}>{content}</button>;
      })}
    </div>
    <p className={styles.muted}>{!compact && "בחרו מקרה כדי לעדכן את הרכב היתרה ואת הפירוט. "}שיעורי התשואה הם הנחות לשינוי בעורך; החישוב אינו מבטיח תשואה.</p>
    <div className={styles.chartCard}>
      <div className={styles.chartHeading}><div><h4>התפתחות החיסכון בשלושת המקרים</h4><p>{horizon} חודשים · {currencyLabel(currency)} · א׳ = אלפים, מ׳ = מיליונים</p></div><span className={styles.badge}>תחזית</span></div>
      <ForecastChart projections={projectionByRole} months={horizon} currency={currency} />
    </div>
    {!compact && visibleMonth && <section className={styles.monthlySection} aria-label="פירוט חודשי של התחזית">
      <div className={styles.sectionHeading}><div><h3>מה קורה בכל חודש?</h3><p>תזרימים לפי ההנחות במקרה {roleLabels[selectedRole]}.</p></div><MonthPicker label="חודש בתחזית" value={visibleMonth.month.slice(0, 7)} min={currentMonths[0]?.month.slice(0, 7)} max={terminal?.month.slice(0, 7)} onChange={setSelectedMonth} /></div>
      <div className={styles.monthList} aria-label={`תזרימי ${roleLabels[selectedRole]} לפי חודש`}><MonthlyDetail key={`${selectedRole}-${visibleMonth.month_number}`} month={visibleMonth} currency={currency} expanded /></div>
    </section>}
    {currentProjection.methodology && <details className={styles.assumptionDetails}>
      <summary>הנחות, מקורות ומתודולוגיה</summary>
      <div className={styles.referenceCard}><strong>מקור תכנון</strong><span>תרחיש <bdi dir="ltr">{currentProjection.scenario_id}</bdi> · גרסה {currentProjection.source_revision_number}</span><code dir="ltr">{currentProjection.source_revision_id}</code></div>
      {snapshot && <div className={styles.referenceCard}><strong>מקורות יתרות הפתיחה</strong>{snapshot.starting_pools.map((pool) => <span key={pool.name}>{pool.name} · {pool.net_worth_account_key ? `חשבון מדוד ${pool.net_worth_account_key}` : "הוזן ידנית"} · {formatMoney(pool.opening_balance, currency)} נכון ל־{formatHebrewDate(pool.as_of_date)}</span>)}</div>}
      <p>גרסת נוסחה: <bdi>{currentProjection.methodology.policy_version}</bdi> · גיבוב הנחות: <code dir="ltr">{currentProjection.assumption_hash}</code></p>
      <ol>{currentProjection.methodology.calculation_order.map((step) => <li key={step}>{step}</li>)}</ol>
      <p>{currentProjection.methodology.projection_disclaimer}</p>
      {snapshot && <div className={styles.assumptionGrid}>{snapshot.cases.map((item) => <div key={item.role}><strong>{roleLabels[item.role]}</strong><p>תשואה שנתית אפקטיבית: {`${formatRateAsPercent(item.annual_return_rate)}%`}</p><p>{item.routes.length} ניתובים · {item.adjustments.length} התאמות · {item.events.length} אירועים · {item.sweep_enabled ? `עודף לקופה ${item.sweep_pool_name}` : "ללא העברת עודף"}</p>{item.events.map((event, index) => <small key={`${event.label}-${index}`}>{eventLabels[event.event_type]} · חודש {event.month} · {formatMoney(event.amount, currency)} · {event.label}</small>)}</div>)}</div>}
    </details>}
  </section>;
}

function ForecastChart({ projections, months }: { projections: Record<ForecastRole, ForecastProjection>; months: number; currency: string }) {
  const chartContainer = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  useEffect(() => {
    const element = chartContainer.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const resize = () => {
      const measured = element.getBoundingClientRect().width;
      if (measured > 0) setWidth(Math.max(260, Math.round(measured)));
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const height = width < 500 ? 230 : 270;
  const left = width < 500 ? 66 : 72;
  const right = 20;
  const top = 18;
  const bottom = 38;
  const data = roles.map((role) => projections[role].months.slice(0, months).map((month) => Number(month.ending_balance)));
  const maxValue = Math.max(1, ...data.flat().filter(Number.isFinite));
  const paths = roles.map((role, roleIndex) => {
    const values = data[roleIndex];
    const points = values.map((value, index) => {
      const x = left + (values.length <= 1 ? 0 : index * (width - left - right) / (values.length - 1));
      const y = top + (height - top - bottom) * (1 - value / maxValue);
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    });
    return { role, path: points.join(" ") };
  });
  const first = projections.baseline.months[0];
  const last = projections.baseline.months[months - 1];
  return <div ref={chartContainer} className={styles.chartScroll}>
    <svg className={styles.chart} viewBox={`0 0 ${width} ${height}`} direction="ltr" role="img" aria-label={`גרף יתרות צפויות בשלושה מקרי תחזית, ${months} חודשים`}>
      {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
        const y = top + (height - top - bottom) * ratio;
        const value = maxValue * (1 - ratio);
        return <g key={ratio}><line x1={left} y1={y} x2={width - right} y2={y} className={styles.gridLine} /><text x={left - 8} y={y + 4} textAnchor="end" className={styles.axisLabel}>{compactAxisMoney(value)}</text></g>;
      })}
      {paths.map(({ role, path }) => <path key={role} d={path} fill="none" stroke={roleColors[role]} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />)}
      <text x={left} y={height - 10} className={styles.axisLabel}>{first ? new Intl.DateTimeFormat("he-IL", { month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(`${first.month.slice(0, 7)}-01T00:00:00Z`)) : ""}</text>
      <text x={width - right} y={height - 10} textAnchor="end" className={styles.axisLabel}>{last ? new Intl.DateTimeFormat("he-IL", { month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(`${last.month.slice(0, 7)}-01T00:00:00Z`)) : ""}</text>
    </svg>
    <div className={styles.legend}>{roles.map((role) => <span key={role}><i style={{ background: roleColors[role] }} />{roleLabels[role]}</span>)}</div>
  </div>;
}

function compactAxisMoney(value: number) {
  if (!Number.isFinite(value)) return "-";
  const format = (number: number) => new Intl.NumberFormat("he-IL", { maximumFractionDigits: 1 }).format(number);
  if (Math.abs(value) >= 1_000_000) return `${format(value / 1_000_000)} מ׳`;
  if (Math.abs(value) >= 1_000) return `${format(value / 1_000)} א׳`;
  return format(value);
}

function MonthlyDetail({ month, currency, expanded = false }: { month: ForecastMonth; currency: string; expanded?: boolean }) {
  const values: Array<[string, string]> = [
    ["הכנסות תכנון ואירועים", month.income], ["הוצאות תכנון ואירועים", month.expenses],
    ["הפקדות לקופות", month.contributions], ["תשואה משוערת", month.estimated_returns],
    ["משיכות שמומנו בתחזית", month.fulfilled_withdrawals], ["עודף שהועבר", month.swept_surplus],
    ["פער מימון", month.unmet_funding_gap], ["יתרה צפויה בסוף החודש", month.ending_balance],
  ];
  return <details className={styles.monthCard} open={expanded || undefined}>
    <summary><span><strong>חודש {month.month_number}</strong><small>{monthLabel(month.month)}</small></span><span className={styles.monthBalance}><small>יתרה צפויה</small><bdi>{formatMoney(month.ending_balance, currency)}</bdi></span><span className={styles.expandHint}>פירוט</span></summary>
    <div className={styles.monthFlowGrid}>{values.map(([label, value]) => <div key={label}><span>{label}</span><bdi>{formatMoney(value, currency)}</bdi></div>)}</div>
    <div className={styles.poolMonthlyList}><strong>תנועות לפי קופה</strong>{month.pools.map((pool) => <div className={styles.poolMonth} key={pool.pool_id}>
      <div><strong>{pool.pool_name}</strong><span>{pool.pool_type === "cash" ? "מזומן או חיסכון" : "השקעה"}</span></div>
      <div><small>פתיחה</small><bdi>{formatMoney(pool.opening_balance, currency)}</bdi></div>
      <div><small>תשואה צפויה</small><bdi>{formatMoney(pool.estimated_return, currency)}</bdi></div>
      <div><small>הפקדות</small><bdi>{formatMoney(pool.contributions, currency)}</bdi></div><div><small>עודף שהועבר</small><bdi>{formatMoney(pool.swept_surplus, currency)}</bdi></div>
      <div><small>משיכות</small><bdi>{formatMoney(pool.fulfilled_withdrawal, currency)}</bdi></div>
      <div><small>סגירה צפויה</small><bdi>{formatMoney(pool.closing_balance, currency)}</bdi></div>
    </div>)}</div>
  </details>;
}

function VerificationCard({ title, value }: { title: string; value: { scenario_id: string; revision_id: string; revision_number: number; provisional: boolean; issue_codes: string[] } }) {
  return <div className={styles.verificationCard}><strong>{title}</strong><span>גרסה {value.revision_number} · {value.provisional ? "זמנית" : "איכות מאומתת"}</span><details><summary>פרטי אימות</summary><code dir="ltr">{value.revision_id}</code><small>{value.issue_codes.length ? value.issue_codes.join(" · ") : "לא נשמרו קודי איכות פתוחים"}</small></details></div>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className={styles.field}><span>{label}</span>{children}</label>;
}

function forecastStartMonth(snapshotDate: string): string | null {
  const date = new Date(`${snapshotDate}T00:00:00Z`);
  const day = date.getUTCDate();
  if (day === 1) return `${snapshotDate.slice(0, 7)}-01`;
  const next = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1));
  if ((next.getTime() - date.getTime()) / 86_400_000 !== 1) return null;
  return `${next.getUTCFullYear()}-${String(next.getUTCMonth() + 1).padStart(2, "0")}-01`;
}
