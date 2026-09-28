"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/async-state";
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
import styles from "./forecasts.module.css";

const roles: ForecastRole[] = ["conservative", "baseline", "optimistic"];
const roleLabels: Record<ForecastRole, string> = {
  conservative: "שמרני",
  baseline: "בסיסי",
  optimistic: "אופטימי",
};
const roleColors: Record<ForecastRole, string> = {
  conservative: "#a96556",
  baseline: "#3f7253",
  optimistic: "#527c9b",
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

function formatMoney(value: string | null | undefined, currency: string) {
  if (value == null || value === "") return "—";
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [whole, fraction] = unsigned.split(".");
  return `${negative ? "−" : ""}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${fraction ? `.${fraction}` : ""}\u00a0${currency}`;
}

function formatRateAsPercent(rate: string) {
  const negative = rate.startsWith("-");
  const unsigned = negative ? rate.slice(1) : rate;
  const [whole, fraction = ""] = unsigned.split(".");
  const digits = `${whole}${fraction.padEnd(2, "0")}`;
  const integer = digits.length > 2 ? digits.slice(0, -2) : "0";
  const decimal = digits.length > 2 ? digits.slice(-2) : digits.padStart(2, "0");
  return `${negative ? "-" : ""}${integer}.${decimal}`.replace(/\.00$/, "");
}

function percentToRate(percent: string) {
  const text = percent.trim().replace(/%$/, "").trim();
  if (!/^-?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text)) return "0";
  const negative = text.startsWith("-");
  const unsigned = negative ? text.slice(1) : text;
  const [whole = "0", fraction = ""] = unsigned.split(".");
  const allDigits = `${whole || "0"}${fraction}`.replace(/^0+(?=\d)/, "");
  const shifted = allDigits.length > 2
    ? `${allDigits.slice(0, -2)}.${allDigits.slice(-2)}`
    : `0.${allDigits.padStart(2, "0")}`;
  const trimmed = shifted.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
  return `${negative && trimmed !== "0" ? "-" : ""}${trimmed}`;
}

function monthLabel(month: string) {
  const [year, monthNumber] = month.slice(0, 7).split("-").map(Number);
  return new Intl.DateTimeFormat("he-IL", { month: "short", year: "2-digit", timeZone: "UTC" }).format(new Date(Date.UTC(year, monthNumber - 1, 1)));
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
  if (error.status === 0 || error.status >= 500) return "לא ידוע אם השמירה הושלמה. רעננו את התחזית לפני ניסיון נוסף.";
  return error.apiError?.message || "בדקו את הנתונים ונסו שוב.";
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
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showArchived, setShowArchived] = useState(true);
  const [seedError, setSeedError] = useState("");
  const [restoreError, setRestoreError] = useState("");

  const selectedForecast = forecasts.find((item) => item.forecast_id === selectedForecastId) ?? null;
  const visibleForecasts = showArchived ? forecasts : forecasts.filter((item) => !item.archived);
  const eligibleSeedBalances = seedRevision?.balances.filter((item) => item.side === "asset" && item.liquidity === "liquid") ?? [];
  const selectedScenario = scenarios.find((item) => item.scenario_id === editor?.scenarioId) ?? null;
  const savingItems = sourceItems(sourceRevision);

  async function refreshAll(preferredForecastId?: string, preferredRevisionNumber?: number) {
    setLoading(true);
    setError("");
    try {
      const [nextForecasts, nextScenarios, nextSnapshots] = await Promise.all([
        getForecasts(true),
        getScenarios(false).then((result) => result.data),
        getSnapshots(false),
      ]);
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
        return;
      }
      const nextRevisions = await getForecastRevisions(chosen.forecast_id);
      setRevisions(nextRevisions);
      const revisionNumber = nextRevisions.some((item) => item.revision_number === preferredRevisionNumber)
        ? preferredRevisionNumber!
        : chosen.current_revision_number;
      setSelectedRevisionNumber(revisionNumber);
      setDetail(await getForecastProjection(chosen.forecast_id, revisionNumber));
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refreshAll(); }, []);

  async function chooseForecast(forecastId: string) {
    setSelectedForecastId(forecastId);
    setError("");
    const chosen = forecasts.find((item) => item.forecast_id === forecastId);
    if (!chosen) return;
    setBusy(true);
    try {
      const nextRevisions = await getForecastRevisions(forecastId);
      setRevisions(nextRevisions);
      const number = chosen.current_revision_number;
      setSelectedRevisionNumber(number);
      setDetail(await getForecastProjection(forecastId, number));
    } catch (cause) { setError(describeError(cause)); }
    finally { setBusy(false); }
  }

  async function chooseForecastRevision(revisionNumber: number) {
    if (!selectedForecast) return;
    setSelectedRevisionNumber(revisionNumber);
    setBusy(true);
    try { setDetail(await getForecastProjection(selectedForecast.forecast_id, revisionNumber)); }
    catch (cause) { setError(describeError(cause)); }
    finally { setBusy(false); }
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
    if (!scenarios.length) return;
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
    if (!editor || !preview) return;
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
    try {
      const payload = editorPayload(editor);
      // Re-run the deterministic engine with the exact reviewed confirmation state.
      // The saved revision and the preview therefore carry the same assumptions hash.
      await previewForecast(payload);
      let saved: ForecastSummary | { forecast_id?: string; revision_number: number };
      if (editor.mode === "create") {
        saved = await createForecast({ ...payload, name: editor.name });
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
    } catch (cause) { setError(describeError(cause)); }
    finally { setBusy(false); }
  }

  async function runAction(operation: () => Promise<unknown>, message: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await operation();
      setNotice(message);
      await refreshAll(selectedForecastId);
    } catch (cause) { setError(describeError(cause)); }
    finally { setBusy(false); }
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
      <div><span className={styles.eyebrow}>36 חודשים · תחזית, לא מדידה</span><h2>תחזיות חיסכון</h2><p>כל תחזית נעולה לגרסה מדויקת של תרחיש תכנון וליתרות פתיחה מפורשות.</p></div>
      <div className={styles.toolbarActions}><Button variant="outline" disabled={busy} onClick={() => void refreshAll(selectedForecastId, selectedRevisionNumber || undefined)}>רענון</Button><Button disabled={busy || !scenarios.length} onClick={() => void startCreate()}>תחזית חדשה</Button></div>
    </div>
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
      {forecasts.length > 0 && <section className={styles.section} aria-labelledby="saved-forecasts-heading">
        <div className={styles.sectionHeading}><div><h3 id="saved-forecasts-heading">תחזיות שמורות</h3><p>פתחו כל גרסה היסטורית כדי לראות את ההנחות והתוצאה שחושבה ממנה.</p></div><label className={styles.check}><input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} /> הצגת ארכיון</label></div>
        <div className={styles.forecastList} aria-label="תחזיות שמורות">
          {visibleForecasts.map((item) => <button key={item.forecast_id} type="button" className={`${styles.forecastChoice}${item.forecast_id === selectedForecastId ? ` ${styles.forecastSelected}` : ""}`} onClick={() => void chooseForecast(item.forecast_id)}>
            <span><strong>{item.name}</strong>{item.archived && <em>בארכיון</em>}</span>
            <small>{item.currency} · גרסה {item.current_revision_number} · מקור תכנון {item.source_revision_number}</small>
          </button>)}
        </div>
      </section>}

      {!selectedForecast || !detail ? <section className={styles.section}><EmptyState title="אין תחזית להצגה" description={scenarios.length ? "צרו תחזית חדשה ובחרו תרחיש תכנון ויתרות פתיחה." : "צרו תרחיש תכנון לפני בניית תחזית חיסכון."} action={scenarios.length ? <Button onClick={() => void startCreate()}>יצירת תחזית</Button> : undefined} /></section> : <>
        <section className={styles.section} aria-labelledby="forecast-detail-heading">
          <div className={styles.sectionHeading}><div><span className={styles.eyebrow}>תוצאות מחושבות · לא יתרות שנמדדו</span><h3 id="forecast-detail-heading">{selectedForecast.name}</h3><p>{detail.snapshot.currency} · 36 חודשים · גרסת תחזית {detail.snapshot.revision_number}</p></div><div className={styles.actionRow}>
            <Button size="sm" onClick={() => void startEdit()} disabled={busy || selectedForecast.archived}>עריכת הנחות</Button>
            <Button size="sm" variant="outline" onClick={() => void runAction(() => cloneForecast(selectedForecast.forecast_id), "נוצר עותק חדש של התחזית.")} disabled={busy}>שכפול</Button>
            <Button size="sm" variant="outline" onClick={() => void runAction(() => setForecastArchived(selectedForecast.forecast_id, !selectedForecast.archived), selectedForecast.archived ? "התחזית הוחזרה מהארכיון." : "התחזית הועברה לארכיון.")} disabled={busy}>{selectedForecast.archived ? "החזרה מהארכיון" : "העברה לארכיון"}</Button>
          </div></div>
          <div className={styles.summaryMeta}>
            <span>תרחיש תכנון: <bdi>{detail.snapshot.scenario_id}</bdi></span>
            <span>גרסת מקור נעולה: <bdi>{detail.snapshot.source_revision_number}</bdi></span>
            <span>גיבוב הנחות: <code dir="ltr">{detail.snapshot.assumption_hash.slice(0, 18)}…</code></span>
            <span>מקור הון: {detail.snapshot.net_worth_snapshot_revision_id ? "יתרות מתמונת הון מדודה" : "יתרות פתיחה ידניות"}</span>
          </div>
          {detail.source_verification.at_creation.provisional && <div className={styles.warning}><strong>איכות מקור התכנון בעת השמירה:</strong> זמנית · {detail.source_verification.at_creation.issue_codes.join(" · ") || "נדרשה סקירת מקור"} · אישור נשמר: {detail.snapshot.provisional_acknowledged ? "כן" : "לא"}</div>}
          <div className={styles.verificationGrid}>
            <VerificationCard title="אימות המקור בעת השמירה" value={detail.source_verification.at_creation} />
            <VerificationCard title="אימות תרחיש התכנון כעת" value={detail.source_verification.current} />
          </div>
          <div className={styles.revisionBar}>
            <label className={styles.field}><span>גרסת תחזית לבדיקה</span><select value={selectedRevisionNumber} onChange={(event) => void chooseForecastRevision(Number(event.target.value))}>{revisions.map((revision) => <option key={revision.revision_id} value={revision.revision_number}>גרסה {revision.revision_number} · {revision.created_at?.slice(0, 10) ?? "תאריך לא זמין"}</option>)}</select></label>
            <span className={styles.badge}>{selectedRevisionNumber === selectedForecast.current_revision_number ? "הגרסה הנוכחית" : "גרסה היסטורית"}</span>
            {selectedRevisionNumber < selectedForecast.current_revision_number && <Button size="sm" variant="outline" disabled={busy || selectedForecast.archived} onClick={() => void restoreSelectedRevision()}>שחזור כגרסה חדשה</Button>}
          </div>
          {restoreError && <ErrorBanner message={restoreError} />}
        </section>
        <ForecastResults
          draft={detail.draft}
          snapshot={detail.snapshot}
          horizon={horizon}
          setHorizon={setHorizon}
          selectedRole={selectedRole}
          setSelectedRole={setSelectedRole}
        />
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
    editor, updateEditor, clearPreview, closeEditor, saveEditor, calculatePreview, busy, preview,
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
      {["מקור תכנון", "יתרות פתיחה", "מקרי תחזית"].map((label, index) => <li key={label} className={editor.step === index + 1 ? styles.activeStep : editor.step > index + 1 ? styles.completeStep : ""}><span>{index + 1}</span>{label}</li>)}
    </ol>

    {editor.step === 1 && <div className={styles.stepContent}>
      <div className={styles.formGrid}>
        {editor.mode === "create" ? <Field label="תרחיש תכנון"><select aria-label="תרחיש תכנון" value={editor.scenarioId} onChange={(event) => onScenarioChange(event.target.value)}>{scenarios.map((scenario) => <option key={scenario.scenario_id} value={scenario.scenario_id}>{scenario.name} · {scenario.currency}</option>)}</select></Field> : <Field label="תרחיש תכנון"><input disabled value={`${selectedScenario?.name ?? editor.scenarioId} · ${selectedScenario?.currency ?? ""}`} /></Field>}
        {editor.mode === "create" ? <Field label="גרסת תכנון מדויקת"><select aria-label="גרסת תכנון מדויקת" value={editor.sourceRevisionNumber} onChange={(event) => onSourceRevisionChange(Number(event.target.value))}>{planningRevisions.map((revision) => <option key={revision.revision_id} value={revision.revision_number}>גרסה {revision.revision_number} · {revision.revision_id.slice(0, 8)}</option>)}</select></Field> : <Field label="גרסת תכנון נעולה"><input disabled value={`גרסה ${editor.sourceRevisionNumber} · ${sourceRevision.revision_id.slice(0, 12)}`} /></Field>}
        <Field label="שם התחזית"><input aria-label="שם התחזית" maxLength={200} value={editor.name} onChange={(event) => updateEditor((current) => ({ ...current, name: event.target.value }), false)} /></Field>
      </div>
      <div className={styles.referenceCard}><strong>מקור מדויק שנבחר</strong><span>תרחיש <bdi dir="ltr">{editor.scenarioId}</bdi> · גרסה {sourceRevision.revision_number} · {selectedScenario?.currency ?? ""}</span><code dir="ltr">{sourceRevision.revision_id}</code></div>
      {sourceRevision.provisional && <div className={styles.warning}><strong>הגרסה הזמנית כוללת:</strong> {sourceRevision.issue_codes.join(" · ") || "פערי איכות במקור"}<label className={styles.check}><input type="checkbox" checked={editor.provisionalAcknowledged} onChange={(event) => updateEditor((current) => ({ ...current, provisionalAcknowledged: event.target.checked }), false)} /> קראתי ואישרתי את מצב מקור התכנון הזה.</label></div>}
      {sourceItems.length > 0 && <div className={styles.referenceCard}><strong>תנועות חיסכון והעברה מהמקור</strong>{sourceItems.map((item) => <span key={item.id}>{itemLabel(item)} · {formatMoney(item.amount, selectedScenario?.currency ?? "ILS")} · <code dir="ltr">{item.id}</code></span>)}</div>}
      <Field label="הערות לגרסה"><textarea rows={3} maxLength={2000} value={editor.notes} onChange={(event) => updateEditor((current) => ({ ...current, notes: event.target.value }), false)} /></Field>
      <div className={styles.formActions}><Button onClick={() => updateEditor((current) => ({ ...current, step: 2 }), false)}>המשך ליתרות פתיחה</Button><Button variant="outline" onClick={closeEditor}>ביטול</Button></div>
    </div>}

    {editor.step === 2 && <div className={styles.stepContent}>
      <div className={styles.sectionHeading}><div><h4>קופות ויתרות פתיחה</h4><p>היתרות הן קלט מפורש. לא נגזרות עסקאות, הכנסות או חיסכון קודם.</p></div><Button size="sm" variant="outline" onClick={addPool}>הוספת קופה ידנית</Button></div>
      <div className={styles.poolGrid}>{editor.pools.map((pool, index) => <article className={styles.poolCard} key={`${pool.name}-${index}`}>
        <div className={styles.cardTop}><strong>{pool.net_worth_account_key ? "יתרה שנמדדה" : "יתרה ידנית"}</strong><button type="button" className={styles.textButton} disabled={editor.pools.length <= 1} onClick={() => updateEditor((current) => ({ ...current, pools: current.pools.filter((_, itemIndex) => itemIndex !== index) }))}>הסרה</button></div>
        <div className={styles.formGrid}>
          <Field label="שם הקופה"><input aria-label={`שם קופה ${index + 1}`} required maxLength={200} value={pool.name} onChange={(event) => patchPool(index, { name: event.target.value })} /></Field>
          <Field label="סוג"><select aria-label={`סוג קופה ${index + 1}`} value={pool.pool_type} onChange={(event) => patchPool(index, { pool_type: event.target.value as ForecastPoolType })}><option value="cash">מזומן או חיסכון</option><option value="investment">השקעה</option></select></Field>
          <Field label={`יתרת פתיחה (${selectedScenario?.currency ?? "ILS"})`}><input aria-label={`יתרת פתיחה קופה ${index + 1}`} inputMode="decimal" required value={pool.opening_balance} onChange={(event) => patchPool(index, { opening_balance: event.target.value })} /></Field>
          <Field label="נכון לתאריך"><input aria-label={`תאריך יתרת פתיחה קופה ${index + 1}`} type="date" required value={pool.as_of_date} onChange={(event) => patchPool(index, { as_of_date: event.target.value })} /></Field>
        </div>
        {pool.net_worth_account_key && <div className={styles.sourceReference}><span>מקור חשבון: {pool.net_worth_account_key} · הערכה {pool.source_valuation_date}</span><code dir="ltr">{pool.net_worth_snapshot_revision_id}</code></div>}
        {pool.source_stale && <label className={styles.check}><input type="checkbox" checked={Boolean(pool.source_quality_acknowledged)} onChange={(event) => patchPool(index, { source_quality_acknowledged: event.target.checked })} /> אני מאשר/ת את יתרת המקור הישנה לקופה זו.</label>}
      </article>)}</div>

      {snapshots.length > 0 && <details className={styles.seedPanel}>
        <summary>בחירת יתרות מתוך הון משפחתי מדוד</summary>
        <p>המערכת תשתמש בחשבונות נכס נזילים בלבד ותשמור את מזהה הגרסה המדויקת ואת תאריך ההערכה.</p>
        <div className={styles.formGrid}>
          <Field label="תמונת מצב"><select aria-label="תמונת מצב ליתרות פתיחה" value={seedSnapshotId} onChange={(event) => onSeedSnapshotChange(event.target.value)}><option value="">בחירת תאריך תמונה</option>{snapshots.filter((item) => !item.archived).map((item) => <option key={item.snapshot_id} value={item.snapshot_id}>{item.snapshot_date} · גרסה {item.current_revision_number}</option>)}</select></Field>
          <Field label="גרסת תמונת מצב"><select aria-label="גרסת תמונת מצב ליתרות פתיחה" value={seedRevision?.revision_number ?? ""} onChange={(event) => onSeedRevisionChange(Number(event.target.value))}><option value="">בחירת גרסה</option>{seedRevisionSummaries.map((revision) => <option key={revision.revision_id} value={revision.revision_number}>גרסה {revision.revision_number}</option>)}</select></Field>
        </div>
        <div className={styles.seedAccounts}>{eligibleSeedBalances.map((balance) => <label className={styles.seedAccount} key={balance.account_key}>
          <input type="checkbox" checked={seedAccountKeys.includes(balance.account_key)} onChange={(event) => setSeedAccountKeys(event.target.checked ? [...seedAccountKeys, balance.account_key] : seedAccountKeys.filter((key) => key !== balance.account_key))} />
          <span><strong>{balance.account_name}</strong><small>{balance.account_key} · {formatMoney(balance.amount_ils, "ILS")} · הערכה {balance.valuation_date}{balance.stale ? " · הערכה ישנה" : ""}</small></span>
          <select aria-label={`סוג קופה לחשבון ${balance.account_name}`} value={seedPoolTypes[balance.account_key] ?? "cash"} onChange={(event) => setSeedPoolTypes({ ...seedPoolTypes, [balance.account_key]: event.target.value as ForecastPoolType })}><option value="cash">מזומן או חיסכון</option><option value="investment">השקעה</option></select>
        </label>)}</div>
        {seedRevision && <div className={styles.sourceReference}>גרסה נעולה <code dir="ltr">{seedRevision.revision_id}</code> · תאריך {seedRevision.snapshot_date} · {!seedStartMonth ? "אפשר להשתמש ביתרה רק מתמונת מצב של תחילת חודש או מסופו." : !seedMatchesScenario ? `תאריך זה מתאים לתרחיש שמתחיל ב־${seedStartMonth}, והתרחיש הנבחר מתחיל ב־${selectedScenario?.start_month}.` : `תחזית מתחילה ב־${seedStartMonth}`}</div>}
        {seedError && <ErrorBanner message={seedError} />}
        <Button type="button" variant="outline" disabled={busy || !seedRevision || !seedMatchesScenario || !seedAccountKeys.length} onClick={addNetWorthPools}>הוספת חשבונות נבחרים כקופות</Button>
      </details>}
      <div className={styles.formActions}><Button variant="outline" onClick={() => updateEditor((current) => ({ ...current, step: 1 }), false)}>חזרה למקור</Button><Button onClick={() => updateEditor((current) => ({ ...current, step: 3 }), false)}>המשך למקרי תחזית</Button></div>
    </div>}

    {editor.step === 3 && <div className={styles.stepContent}>
      <div className={styles.sectionHeading}><div><h4>הנחות בשלושה מקרי תחזית</h4><p>תשואה שנתית אפקטיבית, ניתוב הפקדות ומשיכות, העברות חד־פעמיות והתאמות חודשיות.</p></div></div>
      <div className={styles.caseEditors}>{roles.map((role) => {
        const selected = editor.cases.find((item) => item.role === role)!;
        return <CaseEditor key={role} item={selected} pools={editor.pools} items={sourceItems} currency={selectedScenario?.currency ?? "ILS"}
          onChange={(next) => patchCase(role, () => next)} onConfirm={(confirmed) => patchCase(role, (item) => ({ ...item, confirmed }), false)} />;
      })}</div>
      <div className={styles.formGrid}><Field label="הערות לגרסה"><textarea rows={2} maxLength={2000} value={editor.notes} onChange={(event) => updateEditor((current) => ({ ...current, notes: event.target.value }), false)} /></Field></div>
      <div className={styles.formActions}><Button variant="outline" onClick={() => updateEditor((current) => ({ ...current, step: 2 }), false)}>חזרה ליתרות</Button><Button onClick={calculatePreview} disabled={busy}>{busy ? "מחשב…" : "חישוב תצוגה מקדימה"}</Button></div>
      {preview && previewBaseline && <>
        <ForecastResults draft={preview} snapshot={null} horizon={36} setHorizon={() => undefined} selectedRole="baseline" setSelectedRole={() => undefined} compact />
        {sourceRevision.provisional && <div className={styles.warning}><strong>הגרסה הזמנית כוללת:</strong> {sourceRevision.issue_codes.join(" · ")}<label className={styles.check}><input type="checkbox" checked={editor.provisionalAcknowledged} onChange={(event) => updateEditor((current) => ({ ...current, provisionalAcknowledged: event.target.checked }), false)} /> אני מאשר/ת במפורש מקור תכנון זמני זה.</label></div>}
        <div className={styles.confirmations}><strong>אישור הנחות לפני שמירה</strong><p>שינוי בקלט מנקה את האישורים ומחייב חישוב תצוגה מקדימה נוסף.</p><div className={styles.confirmGrid}>{roles.map((role) => <label className={styles.check} key={role}><input type="checkbox" checked={editor.cases.find((item) => item.role === role)?.confirmed ?? false} onChange={(event) => patchCase(role, (item) => ({ ...item, confirmed: event.target.checked }), false)} /> בדקתי ואישרתי את המקרה {roleLabels[role]}.</label>)}</div></div>
        {stalePools.length > 0 && !stalePools.every((pool) => pool.source_quality_acknowledged) && <div className={styles.warning}>יש לאשר את אזהרות יתרות המקור הישנות לכל קופה לפני שמירה.</div>}
        <div className={styles.formActions}><Button onClick={saveEditor} disabled={busy || !canSave}>{busy ? "שומר…" : editor.mode === "create" ? "שמירת תחזית" : "שמירת גרסה חדשה"}</Button>{editor.mode === "edit" && <span className={styles.muted}>השמירה תיצור גרסה {editor.expectedRevisionNumber! + 1} ותשאיר גרסאות קודמות ללא שינוי.</span>}</div>
      </>}
    </div>}
  </section>;
}

function CaseEditor({ item, pools, items, currency, onChange, onConfirm }: {
  item: ForecastCase;
  pools: ForecastPool[];
  items: PlanningItem[];
  currency: string;
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
        <Field label="מתחיל בחודש"><input type="number" min="1" max="36" value={adjustment.start_month} onChange={(event) => changeAdjustment(index, { start_month: Number(event.target.value) })} /></Field>
        <Field label="עד חודש"><input type="number" min="1" max="36" placeholder="36" value={adjustment.end_month ?? ""} onChange={(event) => changeAdjustment(index, { end_month: event.target.value ? Number(event.target.value) : null })} /></Field>
        <button type="button" className={styles.textButton} onClick={() => update({ adjustments: item.adjustments.filter((_, rowIndex) => rowIndex !== index) })}>הסרת התאמה</button>
      </div>)}
      <Button size="sm" variant="outline" onClick={() => update({ adjustments: [...item.adjustments, { target_type: "line", target: "", operation: "fixed_delta", value: "0", start_month: 1, end_month: null }] })}>הוספת התאמה</Button>
    </details>

    <details className={styles.assumptionDetails}>
      <summary>אירועים חד־פעמיים או העברות ({item.events.length})</summary>
      {item.events.map((event, index) => <div className={styles.inputRow} key={`event-${index}`}>
        <Field label="סוג אירוע"><select value={event.event_type} onChange={(change) => changeEvent(index, { event_type: change.target.value as ForecastEventType })}>{eventTypes.map((type) => <option key={type} value={type}>{eventLabels[type]}</option>)}</select></Field>
        <Field label="חודש"><input type="number" min="1" max="36" value={event.month} onChange={(change) => changeEvent(index, { month: Number(change.target.value) })} /></Field>
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

function ForecastResults({ draft, snapshot, horizon, setHorizon, selectedRole, setSelectedRole, compact = false }: {
  draft: ForecastDraft;
  snapshot: ForecastRevisionProjection["snapshot"] | null;
  horizon: 12 | 24 | 36;
  setHorizon: (value: 12 | 24 | 36) => void;
  selectedRole: ForecastRole;
  setSelectedRole: (role: ForecastRole) => void;
  compact?: boolean;
}) {
  const projectionByRole = draft.projections;
  const baseline = projectionByRole.baseline;
  const currency = baseline.currency;
  const maxMonths = compact ? 12 : horizon;
  const currentProjection = projectionByRole[selectedRole];
  const currentMonths = currentProjection.months.slice(0, maxMonths);
  const checkpoint = (role: ForecastRole, months: 12 | 24 | 36) => draft.comparison?.checkpoints[role]?.find((item) => item.horizon_month === months);

  return <section className={`${styles.section} ${compact ? styles.compactResults : ""}`} aria-labelledby={compact ? "forecast-preview-title" : "forecast-results-title"}>
    <div className={styles.sectionHeading}><div><span className={styles.eyebrow}>יתרות ותזרימים צפויים</span><h3 id={compact ? "forecast-preview-title" : "forecast-results-title"}>{compact ? "תצוגה מקדימה לאחר חישוב" : "תוצאות ותחזית"}</h3><p>שלושת המקרים הם הנחות עבודה. הם אינם ערבות לתשואה או מדידה של יתרה בפועל.</p></div>{!compact && <label className={styles.field}><span>אופק להצגה</span><select aria-label="אופק תחזית" value={horizon} onChange={(event) => setHorizon(Number(event.target.value) as 12 | 24 | 36)}><option value={12}>12 חודשים</option><option value={24}>24 חודשים</option><option value={36}>36 חודשים</option></select></label>}</div>
    {!compact && <div className={styles.caseSummaryGrid}>{roles.map((role) => {
      const series = projectionByRole[role];
      const terminal = series.months[horizon - 1];
      const point = checkpoint(role, horizon);
      return <article className={styles.caseSummary} key={role} style={{ borderInlineStartColor: roleColors[role] }}>
        <span>{roleLabels[role]}</span><strong><bdi>{formatMoney(terminal?.ending_balance, currency)}</bdi></strong><small>יתרה צפויה בחודש {horizon}</small>
        <div><span>הפקדות</span><bdi>{formatMoney(point?.contributions ?? terminal?.contributions, currency)}</bdi></div>
        <div><span>תשואה משוערת</span><bdi>{formatMoney(point?.estimated_returns ?? terminal?.estimated_returns, currency)}</bdi></div>
        <div><span>משיכות שבוצעו</span><bdi>{formatMoney(point?.withdrawals ?? terminal?.fulfilled_withdrawals, currency)}</bdi></div>
        {series.first_shortfall_month && <em>פער מימון מתחיל בחודש {series.first_shortfall_month}</em>}
      </article>;
    })}</div>}
    <div className={styles.chartCard}>
      <div className={styles.chartHeading}><div><h4>טווח תוצאות לפי מקרה</h4><p>{horizon} חודשים · יתרה מצטברת של הקופות</p></div><span className={styles.badge}>תחזית</span></div>
      <ForecastChart projections={projectionByRole} months={maxMonths} currency={currency} />
    </div>
    <div className={styles.detailControls}>
      <label className={styles.field}><span>פירוט חודשי למקרה</span><select aria-label="מקרה להצגת פירוט חודשי" value={selectedRole} onChange={(event) => setSelectedRole(event.target.value as ForecastRole)}>{roles.map((role) => <option key={role} value={role}>{roleLabels[role]}</option>)}</select></label>
      {snapshot && <span className={styles.badge}>גרסה שמורה {snapshot.revision_number} · {snapshot.currency}</span>}
    </div>
    {currentProjection.provisional && <div className={styles.warning}>התחזית מבוססת על תרחיש תכנון זמני: {currentProjection.issue_codes.join(" · ") || "פערי איכות במקור"}.</div>}
    <div className={styles.monthList} aria-label={`תזרימי ${roleLabels[selectedRole]} לפי חודש`}>
      {currentMonths.map((month) => <MonthlyDetail key={`${selectedRole}-${month.month_number}`} month={month} currency={currency} />)}
    </div>
    {currentProjection.methodology && <details className={styles.assumptionDetails}>
      <summary>הנחות, מקורות ומתודולוגיה</summary>
      <div className={styles.referenceCard}><strong>מקור תכנון</strong><span>תרחיש <bdi dir="ltr">{currentProjection.scenario_id}</bdi> · גרסה {currentProjection.source_revision_number}</span><code dir="ltr">{currentProjection.source_revision_id}</code></div>
      {snapshot && <div className={styles.referenceCard}><strong>מקורות יתרות הפתיחה</strong>{snapshot.starting_pools.map((pool) => <span key={pool.name}>{pool.name} · {pool.net_worth_account_key ? `חשבון מדוד ${pool.net_worth_account_key}` : "הוזן ידנית"} · {formatMoney(pool.opening_balance, currency)} נכון ל־{pool.as_of_date}</span>)}</div>}
      <p>גרסת נוסחה: <bdi>{currentProjection.methodology.policy_version}</bdi> · גיבוב הנחות: <code dir="ltr">{currentProjection.assumption_hash}</code></p>
      <ol>{currentProjection.methodology.calculation_order.map((step) => <li key={step}>{step}</li>)}</ol>
      <p>{currentProjection.methodology.projection_disclaimer}</p>
      {snapshot && <div className={styles.assumptionGrid}>{snapshot.cases.map((item) => <div key={item.role}><strong>{roleLabels[item.role]}</strong><p>תשואה שנתית אפקטיבית: {formatMoney(formatRateAsPercent(item.annual_return_rate), "%")}</p><p>{item.routes.length} ניתובים · {item.adjustments.length} התאמות · {item.events.length} אירועים · {item.sweep_enabled ? `עודף לקופה ${item.sweep_pool_name}` : "ללא העברת עודף"}</p>{item.events.map((event, index) => <small key={`${event.label}-${index}`}>{eventLabels[event.event_type]} · חודש {event.month} · {formatMoney(event.amount, currency)} · {event.label}</small>)}</div>)}</div>}
    </details>}
  </section>;
}

function ForecastChart({ projections, months, currency }: { projections: Record<ForecastRole, ForecastProjection>; months: number; currency: string }) {
  const width = 800;
  const height = 270;
  const left = 58;
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
  return <div className={styles.chartScroll}>
    <svg className={styles.chart} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`גרף יתרות צפויות בשלושה מקרי תחזית, ${months} חודשים`}>
      {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
        const y = top + (height - top - bottom) * ratio;
        const value = maxValue * (1 - ratio);
        return <g key={ratio}><line x1={left} y1={y} x2={width - right} y2={y} className={styles.gridLine} /><text x={left - 8} y={y + 4} textAnchor="end" className={styles.axisLabel}>{compactAxisMoney(value, currency)}</text></g>;
      })}
      {paths.map(({ role, path }) => <path key={role} d={path} fill="none" stroke={roleColors[role]} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />)}
      <text x={left} y={height - 10} className={styles.axisLabel}>{first ? monthLabel(first.month) : ""}</text>
      <text x={width - right} y={height - 10} textAnchor="end" className={styles.axisLabel}>{last ? monthLabel(last.month) : ""}</text>
    </svg>
    <div className={styles.legend}>{roles.map((role) => <span key={role}><i style={{ background: roleColors[role] }} />{roleLabels[role]}</span>)}</div>
  </div>;
}

function compactAxisMoney(value: number, currency: string) {
  if (!Number.isFinite(value)) return "—";
  return `${new Intl.NumberFormat("he-IL", { notation: "compact", maximumFractionDigits: 1 }).format(value)} ${currency}`;
}

function MonthlyDetail({ month, currency }: { month: ForecastMonth; currency: string }) {
  const values: Array<[string, string]> = [
    ["הכנסות תכנון ואירועים", month.income], ["הוצאות תכנון ואירועים", month.expenses],
    ["הפקדות לקופות", month.contributions], ["תשואה משוערת", month.estimated_returns],
    ["משיכות שבוצעו", month.fulfilled_withdrawals], ["עודף שהועבר", month.swept_surplus],
    ["פער מימון", month.unmet_funding_gap], ["יתרה צפויה בסוף החודש", month.ending_balance],
  ];
  return <details className={styles.monthCard}>
    <summary><span><strong>חודש {month.month_number}</strong><small>{monthLabel(month.month)} · {month.month.slice(0, 10)}</small></span><span className={styles.monthBalance}><small>יתרה צפויה</small><bdi>{formatMoney(month.ending_balance, currency)}</bdi></span><span className={styles.expandHint}>פירוט</span></summary>
    <div className={styles.monthFlowGrid}>{values.map(([label, value]) => <div key={label}><span>{label}</span><bdi>{formatMoney(value, currency)}</bdi></div>)}</div>
    <div className={styles.poolMonthlyList}><strong>תנועות לפי קופה</strong>{month.pools.map((pool) => <div className={styles.poolMonth} key={pool.pool_id}>
      <div><strong>{pool.pool_name}</strong><span>{pool.pool_type === "cash" ? "מזומן או חיסכון" : "השקעה"}</span></div>
      <div><small>פתיחה</small><bdi>{formatMoney(pool.opening_balance, currency)}</bdi></div>
      <div><small>תשואה צפויה</small><bdi>{formatMoney(pool.estimated_return, currency)}</bdi></div>
      <div><small>הפקדות / עודף</small><bdi>{formatMoney(pool.contributions, currency)}</bdi></div>
      <div><small>משיכות</small><bdi>{formatMoney(pool.fulfilled_withdrawal, currency)}</bdi></div>
      <div><small>סגירה צפויה</small><bdi>{formatMoney(pool.closing_balance, currency)}</bdi></div>
    </div>)}</div>
  </details>;
}

function VerificationCard({ title, value }: { title: string; value: { scenario_id: string; revision_id: string; revision_number: number; provisional: boolean; issue_codes: string[] } }) {
  return <div className={styles.verificationCard}><strong>{title}</strong><span>גרסה {value.revision_number} · {value.provisional ? "זמנית" : "איכות מאומתת"}</span><code dir="ltr">{value.revision_id}</code><small>{value.issue_codes.length ? value.issue_codes.join(" · ") : "לא נשמרו קודי איכות פתוחים"}</small></div>;
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
