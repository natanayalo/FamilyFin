"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { SelectHTMLAttributes } from "react";
import { ApiRequestError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/async-state";
import { FormField } from "@/components/ui/form-patterns";
import { Input } from "@/components/ui/input";
import { clearOverride, createRule, disableRule, getCoverage, getReviewQueue, getRules, previewRule, saveOverride } from "./api";
import type { ClassificationRule, Coverage, EconomicClass, ExpenseBehavior, ReviewItem, RuleDraft, RulePreview } from "./types";
import styles from "./classification.module.css";

const economicClasses: EconomicClass[] = ["income", "consumption", "refund", "internal_transfer", "savings_transfer", "credit_card_settlement", "debt_principal", "unclassified"];
const behaviors: ExpenseBehavior[] = ["fixed", "variable", "unknown", "not_applicable"];
const sources = ["override", "reusable_rule", "builtin_rule", "unclassified"] as const;
const classLabels: Record<EconomicClass, string> = {
  income: "הכנסה", consumption: "צריכה", refund: "החזר", internal_transfer: "העברה פנימית",
  savings_transfer: "העברת חיסכון", credit_card_settlement: "סילוק כרטיס אשראי", debt_principal: "קרן חוב", unclassified: "לא מסווג",
};
const behaviorLabels: Record<ExpenseBehavior, string> = { fixed: "קבועה", variable: "משתנה", unknown: "לא ידוע", not_applicable: "לא רלוונטי" };
const sourceLabels: Record<(typeof sources)[number], string> = { override: "תיקון ידני", reusable_rule: "כלל חוזר", builtin_rule: "כלל מערכת", unclassified: "לא מסווג" };

type PageState<T> = { items: T[]; nextCursor?: string | null };

function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className="control-input" {...props} />;
}

function errorText(error: unknown) {
  if (error instanceof ApiRequestError && error.status === 0) return "תוצאת הפעולה לא ידועה. טענו מחדש ובדקו את המצב לפני ניסיון נוסף.";
  if (error instanceof ApiRequestError && error.apiError?.message) return error.apiError.message;
  return error instanceof Error ? error.message : "לא ניתן להשלים את הפעולה.";
}

function RuleFields({ draft, update }: { draft: RuleDraft; update: <K extends keyof RuleDraft>(key: K, value: RuleDraft[K]) => void }) {
  return <div className={styles.ruleFields}>
    <FormField id="rule-account" label="סוג חשבון" required><Input id="rule-account" value={draft.account_kind} maxLength={64} onChange={(event) => update("account_kind", event.target.value)} /></FormField>
    <FormField id="rule-direction" label="כיוון"><Select id="rule-direction" value={draft.direction} onChange={(event) => update("direction", event.target.value as RuleDraft["direction"])}><option value="debit">חיוב</option><option value="credit">זיכוי</option><option value="zero">אפס</option></Select></FormField>
    <FormField id="rule-currency" label="מטבע" required><Input id="rule-currency" value={draft.currency} maxLength={8} onChange={(event) => update("currency", event.target.value.toUpperCase())} /></FormField>
    <FormField id="rule-class" label="סיווג כלכלי"><Select id="rule-class" value={draft.economic_class} onChange={(event) => update("economic_class", event.target.value as EconomicClass)}>{economicClasses.map((value) => <option key={value} value={value}>{classLabels[value]}</option>)}</Select></FormField>
    <FormField id="rule-source-category" label="קטגוריית מקור" required><Input id="rule-source-category" value={draft.source_category} maxLength={200} onChange={(event) => update("source_category", event.target.value)} /></FormField>
    <FormField id="rule-movement" label="סוג תנועה במקור"><Input id="rule-movement" value={draft.source_movement_type ?? ""} maxLength={200} onChange={(event) => update("source_movement_type", event.target.value || null)} /></FormField>
    <FormField id="rule-analysis-category" label="קטגוריית ניתוח"><Input id="rule-analysis-category" value={draft.analysis_category ?? ""} maxLength={200} onChange={(event) => update("analysis_category", event.target.value || null)} /></FormField>
    <FormField id="rule-behavior" label="התנהגות הוצאה"><Select id="rule-behavior" value={draft.expense_behavior ?? ""} onChange={(event) => update("expense_behavior", event.target.value ? event.target.value as ExpenseBehavior : null)}><option value="">ברירת מחדל של השירות</option>{behaviors.map((value) => <option key={value} value={value}>{behaviorLabels[value]}</option>)}</Select></FormField>
    <FormField id="rule-reason" label="סיבה"><Input id="rule-reason" value={draft.reason} maxLength={500} onChange={(event) => update("reason", event.target.value)} /></FormField>
  </div>;
}

export function ClassificationFeature() {
  const [month, setMonth] = useState("");
  const [accountKind, setAccountKind] = useState("");
  const [currency, setCurrency] = useState("ILS");
  const [issue, setIssue] = useState("");
  const [economicClass, setEconomicClass] = useState("");
  const [source, setSource] = useState("");
  const [includeResolved, setIncludeResolved] = useState(false);
  const [queueCursor, setQueueCursor] = useState<string | undefined>();
  const [queueHistory, setQueueHistory] = useState<Array<string | undefined>>([]);
  const [ruleCursor, setRuleCursor] = useState<string | undefined>();
  const [ruleHistory, setRuleHistory] = useState<Array<string | undefined>>([]);
  const [queue, setQueue] = useState<PageState<ReviewItem>>({ items: [] });
  const [rules, setRules] = useState<PageState<ClassificationRule>>({ items: [] });
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [refreshIndex, setRefreshIndex] = useState(0);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [draft, setDraft] = useState<RuleDraft>({
    account_kind: "bank", direction: "debit", source_category: "", source_movement_type: null,
    currency: "ILS", economic_class: "consumption", analysis_category: null,
    expense_behavior: "unknown", reason: "Saved from classification review",
  });
  const [preview, setPreview] = useState<{ value: RulePreview; fingerprint: string } | null>(null);
  const draftFingerprint = useMemo(() => JSON.stringify(draft), [draft]);

  const updateDraft = useCallback(<K extends keyof RuleDraft>(key: K, value: RuleDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  }, []);

  const refresh = useCallback(() => {
    setQueueCursor(undefined);
    setQueueHistory([]);
    setRuleCursor(undefined);
    setRuleHistory([]);
    setRefreshIndex((value) => value + 1);
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const filters = {
      month: month || undefined,
      account_kind: accountKind || undefined,
      currency: currency || undefined,
      issue: issue || undefined,
      economic_class: economicClass || undefined,
      classification_source: source || undefined,
      include_resolved: includeResolved,
    };
    Promise.all([
      getCoverage({ month: month || undefined, currency: currency || undefined }),
      getReviewQueue(filters, queueCursor),
      getRules(ruleCursor),
    ]).then(([coverageResponse, queueResponse, ruleResponse]) => {
      if (!active) return;
      setCoverage(coverageResponse.data);
      setQueue({ items: queueResponse.data, nextCursor: queueResponse.meta?.next_cursor });
      setRules({ items: ruleResponse.data, nextCursor: ruleResponse.meta?.next_cursor });
    }).catch((reason: unknown) => {
      if (active) setError(errorText(reason));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [month, accountKind, currency, issue, economicClass, source, includeResolved, queueCursor, ruleCursor, refreshIndex]);

  function changeFilter(setter: (value: string) => void, value: string) {
    setter(value);
    setQueueCursor(undefined);
    setQueueHistory([]);
  }

  async function runAction(key: string, action: () => Promise<unknown>) {
    setError("");
    setBusy(key);
    try {
      await action();
      setPreview(null);
      refresh();
    } catch (reason) {
      setError(errorText(reason));
      if (reason instanceof ApiRequestError && reason.status === 0) refresh();
    } finally {
      setBusy("");
    }
  }

  async function onOverride(item: ReviewItem, form: HTMLFormElement) {
    const values = new FormData(form);
    await runAction(`override-${item.transaction_id}`, () => saveOverride(item, {
      economic_class: String(values.get("economic_class")),
      analysis_category: String(values.get("analysis_category") || "") || null,
      expense_behavior: String(values.get("expense_behavior")),
    }));
  }

  async function onClear(item: ReviewItem) {
    await runAction(`clear-${item.transaction_id}`, () => clearOverride(item));
  }

  async function onPreviewRule() {
    setError("");
    setBusy("rule-preview");
    try {
      const response = await previewRule(draft);
      setPreview({ value: response.data, fingerprint: draftFingerprint });
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy("");
    }
  }

  async function onCreateRule() {
    if (!preview || preview.fingerprint !== draftFingerprint) return;
    await runAction("rule-create", () => createRule(draft, preview.value.expected_current_rule_id));
  }

  async function onDisableRule(rule: ClassificationRule) {
    await runAction(`rule-disable-${rule.id}`, () => disableRule(rule));
  }

  if (loading && !coverage && !queue.items.length) return <Card className={styles.module}><LoadingState label="טוענים תור סיווג וכיסוי…" /></Card>;
  if (error && !coverage && !queue.items.length && !rules.items.length) return <Card className={styles.module}><ErrorState description={error} onRetry={refresh} /></Card>;

  return <div className={styles.module}>
    {error && <div className={styles.error} role="alert"><span>{error}</span><Button type="button" variant="outline" size="sm" onClick={refresh}>טעינה מחדש</Button></div>}
    {coverage && <section className={styles.coverage} aria-labelledby="classification-coverage-title">
      <Card className={styles.coverageCard}>
        <div className={styles.coverageHead}><div><h2 id="classification-coverage-title">כיסוי סיווג</h2><p>עסקאות שהתקבלו על ידי שירות הסיווג במסנן הנבחר</p></div><strong>{coverage.classification_coverage_percent === null ? "—" : `${coverage.classification_coverage_percent}%`}</strong></div>
        <progress aria-label="אחוז העסקאות המסווגות" max={100} value={Number(coverage.classification_coverage_percent ?? 0)} />
        <div className={styles.coverageStats}><span><b>{coverage.classified_count}</b> מסווגות</span><span><b>{coverage.unclassified_count}</b> לא מסווגות</span><span><b>{coverage.review_required_count}</b> דורשות בדיקה</span><span><b>{coverage.total_accepted}</b> התקבלו</span></div>
        <div className={styles.coverageBreakdown}>
          <div><h3>לפי סיווג</h3>{Object.entries(coverage.by_economic_class).filter(([, count]) => count > 0).map(([name, count]) => <span key={name}>{classLabels[name as EconomicClass]} <b>{count}</b></span>)}</div>
          <div><h3>לפי מקור</h3>{Object.entries(coverage.by_source).filter(([, count]) => count > 0).map(([name, count]) => <span key={name}>{sourceLabels[name as keyof typeof sourceLabels]} <b>{count}</b></span>)}</div>
          {Object.keys(coverage.issue_counts).length > 0 && <div><h3>קודי בדיקה</h3>{Object.entries(coverage.issue_counts).map(([name, count]) => <span key={name}><bdi>{name}</bdi> <b>{count}</b></span>)}</div>}
        </div>
      </Card>
    </section>}

    <Card className={styles.panel}>
      <div className={styles.panelHead}><div><h2>תור בדיקה</h2><p>סינון הרשומות והחלטה על סיווג לכל עסקה</p></div><span className={styles.countPill}>{queue.items.length} בעמוד</span></div>
      <div className={styles.filters}>
        <FormField id="filter-month" label="חודש"><Input id="filter-month" type="month" value={month} onChange={(event) => changeFilter(setMonth, event.target.value)} /></FormField>
        <FormField id="filter-account" label="סוג חשבון"><Input id="filter-account" value={accountKind} onChange={(event) => changeFilter(setAccountKind, event.target.value)} /></FormField>
        <FormField id="filter-currency" label="מטבע"><Input id="filter-currency" value={currency} maxLength={8} onChange={(event) => changeFilter(setCurrency, event.target.value.toUpperCase())} /></FormField>
        <FormField id="filter-issue" label="קוד בדיקה"><Input id="filter-issue" value={issue} onChange={(event) => changeFilter(setIssue, event.target.value)} /></FormField>
        <FormField id="filter-class" label="סיווג כלכלי"><Select id="filter-class" value={economicClass} onChange={(event) => changeFilter(setEconomicClass, event.target.value)}><option value="">הכול</option>{economicClasses.map((value) => <option key={value} value={value}>{classLabels[value]}</option>)}</Select></FormField>
        <FormField id="filter-source" label="מקור סיווג"><Select id="filter-source" value={source} onChange={(event) => changeFilter(setSource, event.target.value)}><option value="">הכול</option>{sources.map((value) => <option key={value} value={value}>{sourceLabels[value]}</option>)}</Select></FormField>
        <label className={styles.checkFilter}><input type="checkbox" checked={includeResolved} onChange={(event) => { setIncludeResolved(event.target.checked); setQueueCursor(undefined); setQueueHistory([]); }} />הצגת עסקאות שכבר סווגו</label>
      </div>
      {loading && <LoadingState label="מעדכנים תוצאות…" />}
      {!loading && queue.items.length === 0 && <EmptyState title="אין עסקאות בתור הזה" description="אפשר לשנות את המסננים או להציג גם עסקאות שכבר סווגו." />}
      <div className={styles.queue}>
        {queue.items.map((item) => {
          const classification = item.effective_classification;
          return <article className={styles.reviewItem} key={`${item.transaction_id}-${item.expected_override_version}`}>
            <div className={styles.transactionHead}>
              <div><h3>{item.description || "עסקה ללא תיאור"}</h3><p><bdi>{item.booking_date}</bdi> · עסקה <bdi>{item.transaction_id}</bdi> · {item.account_kind}</p></div>
              <div className={styles.amount} dir="ltr"><bdi>{item.amount}</bdi> <bdi>{item.currency}</bdi></div>
            </div>
            <div className={styles.chips}><span>{classLabels[classification.economic_class]}</span><span>{behaviorLabels[classification.expense_behavior]}</span><span>{sourceLabels[classification.source]}</span>{classification.analysis_category && <span>{classification.analysis_category}</span>}</div>
            <p className={styles.explanation}>{classification.explanation}</p>
            {item.issues.length > 0 && <ul className={styles.issues}>{item.issues.map((problem, index) => <li key={`${problem.code}-${index}`}><bdi>{problem.code}</bdi> — {problem.message}</li>)}</ul>}
            <details className={styles.sourceDetails}><summary>פרטי מקור</summary><p>קטגוריה: {item.source_category}{item.source_movement_type ? ` · סוג תנועה: ${item.source_movement_type}` : ""}</p><pre>{JSON.stringify(item.source_fields, null, 2)}</pre></details>
            <Button type="button" variant="ghost" size="sm" aria-expanded={expanded === item.transaction_id} onClick={() => setExpanded(expanded === item.transaction_id ? null : item.transaction_id)}>{expanded === item.transaction_id ? "סגירת עורך" : "עריכת סיווג"}</Button>
            {expanded === item.transaction_id && <form className={styles.overrideForm} onSubmit={(event) => { event.preventDefault(); void onOverride(item, event.currentTarget); }}>
              <FormField id={`class-${item.transaction_id}`} label="סיווג כלכלי"><Select name="economic_class" id={`class-${item.transaction_id}`} defaultValue={classification.economic_class}>{economicClasses.map((value) => <option key={value} value={value}>{classLabels[value]}</option>)}</Select></FormField>
              <FormField id={`category-${item.transaction_id}`} label="קטגוריית ניתוח"><Input name="analysis_category" id={`category-${item.transaction_id}`} defaultValue={classification.analysis_category ?? ""} /></FormField>
              <FormField id={`behavior-${item.transaction_id}`} label="התנהגות הוצאה"><Select name="expense_behavior" id={`behavior-${item.transaction_id}`} defaultValue={classification.expense_behavior}>{behaviors.map((value) => <option key={value} value={value}>{behaviorLabels[value]}</option>)}</Select></FormField>
              <div className={styles.actions}><Button type="submit" disabled={Boolean(busy)}>{busy === `override-${item.transaction_id}` ? "שומרים…" : "שמירת תיקון"}</Button><Button type="button" variant="outline" disabled={Boolean(busy) || classification.source !== "override"} onClick={() => void onClear(item)}>{busy === `clear-${item.transaction_id}` ? "מנקים…" : "ניקוי תיקון"}</Button></div>
            </form>}
          </article>;
        })}
      </div>
      <div className={styles.pagination}><Button variant="outline" disabled={!queueHistory.length || loading} onClick={() => { const previous = [...queueHistory]; const cursor = previous.pop(); setQueueHistory(previous); setQueueCursor(cursor); }}>הקודם</Button><Button variant="outline" disabled={!queue.nextCursor || loading} onClick={() => { setQueueHistory((previous) => [...previous, queueCursor]); setQueueCursor(queue.nextCursor || undefined); }}>הבא</Button></div>
    </Card>

    <Card className={styles.panel}>
      <div className={styles.panelHead}><div><h2>כלל סיווג חוזר</h2><p>התאמה מדויקת לפי מאפייני המקור, ללא שינוי ידני של עסקאות קיימות</p></div></div>
      <RuleFields draft={draft} update={updateDraft} />
      <div className={styles.actions}><Button type="button" variant="outline" disabled={Boolean(busy) || !draft.source_category.trim()} onClick={() => void onPreviewRule()}>{busy === "rule-preview" ? "בודקים…" : "תצוגה מקדימה"}</Button><Button type="button" disabled={Boolean(busy) || !preview || preview.fingerprint !== draftFingerprint} onClick={() => void onCreateRule()}>{busy === "rule-create" ? "יוצרים…" : "יצירת כלל"}</Button></div>
      {preview && preview.fingerprint === draftFingerprint && <div className={styles.preview} role="status"><strong>הכלל יתאים ל־{preview.value.count} עסקאות שהתקבלו.</strong><span>{preview.value.expected_current_rule_id === null ? "לא קיימת כרגע גרסה קודמת למפתח זה." : `הגרסה הנוכחית היא ${preview.value.expected_current_rule_id}; היצירה תיצור גרסה חדשה.`}</span></div>}
    </Card>

    <Card className={styles.panel}>
      <div className={styles.panelHead}><div><h2>היסטוריית כללים</h2><p>כלל פעיל הוא הגרסה העדכנית למפתח ההתאמה המדויק</p></div></div>
      {rules.items.length === 0 ? <EmptyState title="אין עדיין כללים חוזרים" description="אפשר ליצור כלל לאחר בדיקת מספר העסקאות שיתאימו לו." /> : <div className={styles.ruleHistory}>{rules.items.map((rule) => <article className={styles.ruleRow} key={rule.id}>
        <div><strong>{rule.source_category} · {rule.direction === "debit" ? "חיוב" : rule.direction === "credit" ? "זיכוי" : "אפס"} · {rule.currency}</strong><p>{rule.account_kind}{rule.source_movement_type ? ` · ${rule.source_movement_type}` : ""} · {classLabels[rule.economic_class]} · {behaviorLabels[rule.expense_behavior]}</p><small>גרסה {rule.revision} · מזהה {rule.id} · {rule.is_current ? rule.effective_active ? "פעילה" : "נוכחית ומושבתת" : "היסטורית"}{rule.reason ? ` · ${rule.reason}` : ""}</small></div>
        {rule.is_current && rule.effective_active && <Button type="button" variant="outline" size="sm" disabled={Boolean(busy)} onClick={() => void onDisableRule(rule)}>{busy === `rule-disable-${rule.id}` ? "מעדכנים…" : "השבתת כלל"}</Button>}
      </article>)}</div>}
      <div className={styles.pagination}><Button variant="outline" disabled={!ruleHistory.length || loading} onClick={() => { const previous = [...ruleHistory]; const cursor = previous.pop(); setRuleHistory(previous); setRuleCursor(cursor); }}>הקודם</Button><Button variant="outline" disabled={!rules.nextCursor || loading} onClick={() => { setRuleHistory((previous) => [...previous, ruleCursor]); setRuleCursor(rules.nextCursor || undefined); }}>הבא</Button></div>
    </Card>
    <p className={styles.concurrencyNote}>עריכה והפעלת כללים נבדקות מול הגרסה שנטענה. שינוי קודם יגרום לבקשת רענון לפני שמירה. אם החיבור נקטע בזמן שמירה, יש לטעון מחדש ולבדוק את התוצאה לפני ניסיון נוסף.</p>
  </div>;
}
