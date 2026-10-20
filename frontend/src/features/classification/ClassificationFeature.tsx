"use client";

import { MonthPicker } from "@/components/ui/month-picker";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { ComponentProps, SelectHTMLAttributes } from "react";
import { classificationExplanation, formatAmount, issueLabel } from "@/lib/display";
import { accountKindLabel, formatDate } from "@/features/dashboard/format";
import { ApiRequestError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/async-state";
import { FormField } from "@/components/ui/form-patterns";
import { Input } from "@/components/ui/input";
import { clearOverride, createRule, disableRule, getAnalysisCategories, getCoverage, getReviewQueue, getRules, previewRule, saveOverride } from "./api";
import type { ClassificationRule, Coverage, EconomicClass, ExpenseBehavior, ResolutionValues, ReviewItem, RuleDraft, RulePreview } from "./types";
import styles from "./classification.module.css";

const economicClasses: EconomicClass[] = ["income", "consumption", "refund", "internal_transfer", "savings_transfer", "credit_card_settlement", "debt_principal", "no_financial_effect", "unclassified"];
const behaviors: ExpenseBehavior[] = ["fixed", "variable", "unknown", "not_applicable"];
const sources = ["override", "reusable_rule", "builtin_rule", "unclassified"] as const;
const classLabels: Record<EconomicClass, string> = {
  income: "הכנסה", consumption: "צריכה", refund: "החזר", internal_transfer: "העברה פנימית",
  savings_transfer: "העברת חיסכון", credit_card_settlement: "סילוק כרטיס אשראי", debt_principal: "קרן חוב", no_financial_effect: "נבדק - ללא השפעה כספית", unclassified: "לא מסווג",
};
const behaviorLabels: Record<ExpenseBehavior, string> = { fixed: "קבועה", variable: "משתנה", unknown: "לא ידוע", not_applicable: "לא רלוונטי" };
const sourceLabels: Record<(typeof sources)[number], string> = { override: "תיקון ידני", reusable_rule: "כלל חוזר", builtin_rule: "כלל מערכת", unclassified: "לא מסווג" };

type PageState<T> = { items: T[]; nextCursor?: string | null };
type CategoryChoices = { values: string[]; loading: boolean; failed: boolean };

function CategoryField({ id, listId, choices, value, defaultValue, onValueChange, ...inputProps }: {
  id: string; listId: string; choices?: CategoryChoices; value?: string;
  defaultValue?: string; onValueChange?: (value: string) => void;
} & Omit<ComponentProps<typeof Input>, "value" | "defaultValue" | "onChange">) {
  const [text, setText] = useState(defaultValue ?? "");
  const [showChoices, setShowChoices] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const categories = choices?.values ?? [];
  const updateValue = (next: string) => { setText(next); onValueChange?.(next); };
  const hint = choices?.failed
    ? "לא ניתן לטעון הצעות כרגע. אפשר להקליד שם קטגוריה."
    : !choices || choices.loading
      ? "טוענים הצעות… אפשר גם להקליד שם חדש."
      : choices?.values.length
        ? "אפשר לבחור קטגוריה קיימת או להקליד שם חדש."
        : "אין עדיין קטגוריות במטבע זה. אפשר להקליד שם חדש.";
  return <FormField id={id} label="קטגוריית ניתוח" hint={hint}>
    <Input {...inputProps} ref={inputRef} id={id} list={listId} value={value ?? text} onChange={(event) => updateValue(event.target.value)} maxLength={200} autoComplete="off" placeholder="קטגוריה קיימת או שם חדש" aria-describedby={`${id}-hint`} />
    {categories.length > 0 && <>
      <Button type="button" variant="ghost" size="sm" className={styles.categoryToggle} aria-expanded={showChoices} aria-controls={`${id}-suggestions`} onClick={() => setShowChoices((current) => !current)}>בחירה מקטגוריות קיימות ({categories.length})</Button>
      {showChoices && <div id={`${id}-suggestions`} className={styles.categorySuggestions} role="group" aria-label="קטגוריות ניתוח קיימות">
        {categories.map((category) => <Button type="button" key={category} variant="outline" size="sm" onClick={() => { updateValue(category); setShowChoices(false); inputRef.current?.focus(); }}>{category}</Button>)}
      </div>}
    </>}
  </FormField>;
}

function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className="control-input" {...props} />;
}

function errorText(error: unknown) {
  if (error instanceof ApiRequestError && error.status === 0) return "תוצאת הפעולה לא ידועה. טענו מחדש ובדקו את המצב לפני ניסיון נוסף.";
  if (error instanceof ApiRequestError && error.apiError?.message) return error.apiError.message;
  return error instanceof Error ? error.message : "לא ניתן להשלים את הפעולה.";
}

function OverrideEditor({ item, busy, choices, listId, onSave, onClear }: {
  item: ReviewItem; busy: string; choices?: CategoryChoices; listId: string;
  onSave: (values: ResolutionValues) => void; onClear: () => void;
}) {
  const current = item.effective_classification;
  const saved = item.saved_override;
  const [economicClass, setEconomicClass] = useState(saved?.economic_class ?? current.economic_class);
  const [category, setCategory] = useState(saved?.analysis_category ?? current.analysis_category ?? "");
  const [behavior, setBehavior] = useState(saved?.expense_behavior ?? current.expense_behavior);
  const [correctAmount, setCorrectAmount] = useState(saved?.effective_amount != null);
  const [amount, setAmount] = useState(current.amount);
  const [reason, setReason] = useState(saved?.effective_amount != null ? saved.reason ?? "" : "תיקון סכום וכיוון לאחר בדיקת פרטי המקור");
  const proposedAmount = correctAmount ? amount : current.amount;
  const numeric = Number(proposedAmount);
  const validAmount = /^[+-]?\d+(?:\.\d{1,8})?$/.test(proposedAmount) && Number.isFinite(numeric);
  const invalidDirection = validAmount && (
    (["consumption", "credit_card_settlement", "debt_principal"].includes(economicClass) && numeric >= 0)
    || (["income", "refund"].includes(economicClass) && numeric <= 0)
    || (economicClass === "savings_transfer" && numeric === 0)
    || (economicClass === "no_financial_effect" && (numeric !== 0 || Number(current.imported_amount ?? current.amount) !== 0))
  );
  const zeroSource = Number(current.imported_amount ?? current.amount) === 0;
  const invalidReason = correctAmount && !reason.trim();
  const conflict = current.issues.some((issue) => ["INVALID_CLASS_SIGN", "STALE_AMOUNT_CORRECTION"].includes(issue.code));
  const changeDirection = (direction: string) => {
    if (direction) { setCorrectAmount(true); setAmount(`${direction === "debit" ? "-" : ""}${amount.replace(/^[+-]/, "")}`); }
  };
  return <form className={styles.overrideForm} onSubmit={(event) => {
    event.preventDefault();
    if (!validAmount || invalidDirection || invalidReason || busy) return;
    onSave({ economic_class: economicClass, analysis_category: category || null, expense_behavior: behavior,
      ...(correctAmount ? { effective_amount: amount, reason } : {}) });
  }}>
    <section className={styles.resolutionSource} aria-label="נתונים מיובאים">
      <h4>נתונים מיובאים · נשמרים ללא שינוי</h4>
      <dl><div><dt>סכום · הבסיס לדוחות</dt><dd><bdi dir="ltr">{formatAmount(current.imported_amount ?? item.amount, item.currency)}</bdi></dd></div>
        <div><dt>תנועה מקורית · מידע מהייצוא</dt><dd>{current.original_amount == null ? "לא נמסר" : <bdi dir="ltr">{formatAmount(current.original_amount, current.original_currency ?? item.currency)}</bdi>}</dd></div>
        <div><dt>קטגוריית מקור</dt><dd>{item.source_category}</dd></div></dl>
      <p>עמודת ״סכום״ קובעת את הסכום והכיוון בדוחות. ״תנועה מקורית״ נשמרת כמידע מהייצוא; הסימן שלה אינו קובע אם זו הכנסה או הוצאה.</p>
    </section>
    <div className={zeroSource ? styles.zeroDecisionClass : undefined}>
    <FormField id={`class-${item.transaction_id}`} label="סיווג כלכלי"><Select name="economic_class" id={`class-${item.transaction_id}`} value={economicClass} onChange={(event) => { const value = event.target.value as EconomicClass; setEconomicClass(value); if (value === "no_financial_effect") setBehavior("not_applicable"); }}>{economicClasses.map((value) => <option key={value} value={value} disabled={value === "no_financial_effect" && !zeroSource}>{classLabels[value]}</option>)}</Select></FormField>
    </div>
    {zeroSource && <p className={styles.zeroDecisionHelp}>אם אימתתם שלא נגבה סכום, בחרו ״נבדק - ללא השפעה כספית״ ושמרו. השורה תישמר ותצא מתור הבדיקה ללא שינוי סכום או הוספת הוצאה. אם הסכום ישתנה בייבוא מאוחר יותר, היא תחזור לבדיקה.</p>}
    <CategoryField id={`category-${item.transaction_id}`} name="analysis_category" listId={listId} choices={choices} value={category} onValueChange={setCategory} />
    <FormField id={`behavior-${item.transaction_id}`} label="התנהגות הוצאה"><Select name="expense_behavior" id={`behavior-${item.transaction_id}`} value={behavior} onChange={(event) => setBehavior(event.target.value as ExpenseBehavior)}>{behaviors.map((value) => <option key={value} value={value}>{behaviorLabels[value]}</option>)}</Select></FormField>
    <details className={styles.amountCorrection} open={conflict || correctAmount || undefined}>
      <summary>תיקון סכום וכיוון</summary>
      <p>תקנו סכום רק אם בדקתם שעמודת ״סכום״ שגויה. סימן שונה ב״תנועה מקורית״ אינו סיבה להפוך את הכיוון. התיקון יחול על העסקה הזו בדוחות ויישמר בהיסטוריית התיקונים.</p>
      <label className={styles.checkFilter}><input type="checkbox" checked={correctAmount} disabled={Boolean(busy) || saved?.effective_amount != null} onChange={(event) => setCorrectAmount(event.target.checked)} />לתקן את הסכום לחישוב</label>
      <div className={styles.correctionFields}>
        <FormField id={`direction-${item.transaction_id}`} label="כיוון מאומת"><Select id={`direction-${item.transaction_id}`} value={correctAmount ? Number(amount) < 0 ? "debit" : Number(amount) > 0 ? "credit" : "" : ""} onChange={(event) => changeDirection(event.target.value)}><option value="">בחרו כיוון</option><option value="debit">חיוב - כסף שיצא</option><option value="credit">זיכוי - כסף שנכנס</option></Select></FormField>
        <FormField id={`amount-${item.transaction_id}`} label="סכום לחישוב" hint="חיוב בסכום שלילי; זיכוי בסכום חיובי."><Input id={`amount-${item.transaction_id}`} inputMode="decimal" dir="ltr" value={amount} maxLength={34} disabled={!correctAmount} onChange={(event) => setAmount(event.target.value)} /></FormField>
        {correctAmount && <FormField id={`reason-${item.transaction_id}`} label="סיבת התיקון" required><Input id={`reason-${item.transaction_id}`} value={reason} maxLength={500} required onChange={(event) => setReason(event.target.value)} /></FormField>}
      </div>
      {saved?.effective_amount != null && <p>לביטול תיקון הסכום השתמשו ב״ביטול תיקון וחזרה למקור״.</p>}
    </details>
    <div className={styles.resolutionPreview} role={invalidDirection || !validAmount || invalidReason ? "alert" : "status"}>
      <strong>תצוגה מקדימה לדוחות</strong>
      {!validAmount ? <p>יש להזין סכום תקין, עם עד 8 ספרות אחרי הנקודה.</p> : invalidDirection ? <p>הסכום לחישוב אינו מתאים לסיווג ״{classLabels[economicClass]}״. יש לבחור כיוון מאומת או סיווג מתאים לפני השמירה.</p> : invalidReason ? <p>יש למלא סיבה לתיקון הסכום.</p> : <p>{economicClass === "unclassified" ? "העסקה תישאר לבדיקה ולא תיכלל במדדי הכנסה וצריכה." : economicClass === "no_financial_effect" ? "השורה תסומן כנבדקה, תצא מתור הבדיקה ולא תוסיף הכנסה או הוצאה. הסכום יישאר אפס." : <>בדוחות תירשם {classLabels[economicClass]} של <bdi>{formatAmount(proposedAmount.replace(/^[+-]/, ""), item.currency)}</bdi>{category ? ` בקטגוריית ${category}` : ""}.</>}</p>}
      {correctAmount && validAmount && <p>סכום לחישוב: <bdi>{formatAmount(current.amount, item.currency)}</bdi> ← <bdi>{formatAmount(amount, item.currency)}</bdi></p>}
    </div>
    <div className={styles.actions}><Button type="submit" disabled={Boolean(busy) || !validAmount || invalidDirection || invalidReason}>{busy === `override-${item.transaction_id}` ? "שומרים…" : "שמירת תיקון"}</Button><Button type="button" variant="outline" disabled={Boolean(busy) || current.source !== "override"} onClick={onClear}>{busy === `clear-${item.transaction_id}` ? "מבטלים…" : "ביטול תיקון וחזרה למקור"}</Button></div>
  </form>;
}

function RuleFields({ draft, update, categoryListId, categoryChoices }: { draft: RuleDraft; update: <K extends keyof RuleDraft>(key: K, value: RuleDraft[K]) => void; categoryListId: string; categoryChoices?: CategoryChoices }) {
  return <div className={styles.ruleFields}>
    <FormField id="rule-account" label="סוג חשבון" required><Input id="rule-account" value={draft.account_kind} maxLength={64} onChange={(event) => update("account_kind", event.target.value)} /></FormField>
    <FormField id="rule-direction" label="כיוון"><Select id="rule-direction" value={draft.direction} onChange={(event) => update("direction", event.target.value as RuleDraft["direction"])}><option value="debit">חיוב</option><option value="credit">זיכוי</option><option value="zero">אפס</option></Select></FormField>
    <FormField id="rule-currency" label="מטבע" required><Input id="rule-currency" value={draft.currency} maxLength={8} onChange={(event) => update("currency", event.target.value.toUpperCase())} /></FormField>
    <FormField id="rule-class" label="סיווג כלכלי"><Select id="rule-class" value={draft.economic_class} onChange={(event) => update("economic_class", event.target.value as EconomicClass)}>{economicClasses.map((value) => <option key={value} value={value}>{classLabels[value]}</option>)}</Select></FormField>
    <FormField id="rule-source-category" label="קטגוריית מקור" required><Input id="rule-source-category" value={draft.source_category} maxLength={200} onChange={(event) => update("source_category", event.target.value)} /></FormField>
    <FormField id="rule-movement" label="סוג תנועה במקור"><Input id="rule-movement" value={draft.source_movement_type ?? ""} maxLength={200} onChange={(event) => update("source_movement_type", event.target.value || null)} /></FormField>
    <CategoryField id="rule-analysis-category" listId={categoryListId} choices={categoryChoices} value={draft.analysis_category ?? ""} onValueChange={(value) => update("analysis_category", value || null)} />
    <FormField id="rule-behavior" label="התנהגות הוצאה"><Select id="rule-behavior" value={draft.expense_behavior ?? ""} onChange={(event) => update("expense_behavior", event.target.value ? event.target.value as ExpenseBehavior : null)}><option value="">ברירת מחדל של השירות</option>{behaviors.map((value) => <option key={value} value={value}>{behaviorLabels[value]}</option>)}</Select></FormField>
    <FormField id="rule-reason" label="סיבה"><Input id="rule-reason" value={draft.reason} maxLength={500} onChange={(event) => update("reason", event.target.value)} /></FormField>
  </div>;
}

export function ClassificationFeature() {
  const [month, setMonth] = useState("");
  const [filtersReady, setFiltersReady] = useState(false);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const monthValue = params.get("month");
    const currencyValue = params.get("currency");
    const classValue = params.get("economic_class");
    if (params.get("include_resolved") === "true") setIncludeResolved(true);
    if (monthValue && /^\d{4}-(0[1-9]|1[0-2])$/.test(monthValue)) setMonth(monthValue);
    if (currencyValue && /^[A-Z]{3}$/.test(currencyValue)) setCurrency(currencyValue);
    if (classValue && economicClasses.includes(classValue as EconomicClass)) setEconomicClass(classValue);
    setFiltersReady(true);
  }, []);
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
  const [decisionFeedback, setDecisionFeedback] = useState<{ transactionId: number; text: string; applied: boolean } | null>(null);
  const [busy, setBusy] = useState("");
  const [refreshIndex, setRefreshIndex] = useState(0);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [draft, setDraft] = useState<RuleDraft>({
    account_kind: "bank", direction: "debit", source_category: "", source_movement_type: null,
    currency: "ILS", economic_class: "consumption", analysis_category: null,
    expense_behavior: "unknown", reason: "נשמר מסקירת הסיווג",
  });
  const [preview, setPreview] = useState<{ value: RulePreview; fingerprint: string } | null>(null);
  const categoryListPrefix = useId();
  const [categoryChoices, setCategoryChoices] = useState<Record<string, CategoryChoices>>({});
  const ruleCurrency = draft.currency.trim().toUpperCase();
  const expandedCurrency = queue.items.find((item) => item.transaction_id === expanded)?.currency;
  const categoryCurrencyKey = JSON.stringify([...new Set([ruleCurrency, expandedCurrency].filter((value): value is string => Boolean(value)))].sort());
  useEffect(() => {
    const currencies: string[] = JSON.parse(categoryCurrencyKey);
    let active = true;
    setCategoryChoices((current) => ({ ...current, ...Object.fromEntries(currencies.map((currency) => [currency, { values: [], loading: true, failed: false }])) }));
    void Promise.allSettled(currencies.map(getAnalysisCategories)).then((results) => {
      if (!active) return;
      setCategoryChoices((current) => ({ ...current, ...Object.fromEntries(results.map((result, index) => [currencies[index], {
        values: result.status === "fulfilled" ? result.value.data : [],
        loading: false,
        failed: result.status === "rejected",
      }])) }));
    });
    return () => { active = false; };
  }, [categoryCurrencyKey, refreshIndex]);
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
    if (!filtersReady) return;
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
  }, [filtersReady, month, accountKind, currency, issue, economicClass, source, includeResolved, queueCursor, ruleCursor, refreshIndex]);

  function changeFilter(setter: (value: string) => void, value: string) {
    setDecisionFeedback(null);
    setter(value);
    setQueueCursor(undefined);
    setQueueHistory([]);
  }

  async function runAction(key: string, action: () => Promise<unknown>) {
    setError("");
    setDecisionFeedback(null);
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

  async function onOverride(item: ReviewItem, values: ResolutionValues) {
    const requested = values.economic_class as EconomicClass;
    await runAction(`override-${item.transaction_id}`, async () => {
      const response = await saveOverride(item, values);
      const result = response.data.result;
      const applied = result.economic_class !== "unclassified";
      const invalidSign = result.issues.some((issue) => issue.code === "INVALID_CLASS_SIGN");
      setDecisionFeedback({
        transactionId: item.transaction_id,
        applied,
        text: applied
          ? `התיקון לעסקה ${item.transaction_id} נשמר. הסיווג הפעיל: ${classLabels[result.economic_class]}.${values.effective_amount !== undefined ? ` הסכום לחישוב בדוחות: ${formatAmount(result.amount, item.currency)}.` : ""}`
          : invalidSign
            ? `התיקון לעסקה ${item.transaction_id} נשמר, אך הסיווג ״${classLabels[requested]}״ לא הוחל כי אינו מתאים לכיוון סכום העסקה. העסקה נשארה לא מסווגת; בדקו את פרטי המקור לפני בחירת סיווג אחר. שמירת סיווג אינה משנה את סכום העסקה.`
            : `התיקון לעסקה ${item.transaction_id} נשמר. העסקה עדיין לא מסווגת ואינה משלימה את סיווג החודש.`,
      });
      if (applied) setExpanded(null);
    });
  }

  async function onClear(item: ReviewItem) {
    await runAction(`clear-${item.transaction_id}`, async () => {
      const response = await clearOverride(item);
      const result = response.data.result;
      setExpanded(null);
      setDecisionFeedback({ transactionId: item.transaction_id, applied: true, text: `התיקון לעסקה ${item.transaction_id} בוטל. הסכום חזר למקור: ${formatAmount(result.amount, item.currency)}.${result.economic_class === "unclassified" ? " העסקה נשארה לבדיקה." : ""}` });
    });
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
    {Object.entries(categoryChoices).map(([currency, choices]) => <datalist key={currency} id={`${categoryListPrefix}-${currency}`}>{choices.values.map((category) => <option key={category} value={category} />)}</datalist>)}
    {error && <div className={styles.error} role="alert"><span>{error}</span><Button type="button" variant="outline" size="sm" onClick={refresh}>טעינה מחדש</Button></div>}
    {coverage && <section className={styles.coverage} aria-labelledby="classification-coverage-title">
      <Card className={styles.coverageCard}>
        <div className={styles.coverageHead}><div><h2 id="classification-coverage-title">כיסוי סיווג</h2><p>עסקאות שהתקבלו על ידי שירות הסיווג במסנן הנבחר</p></div><strong>{coverage.classification_coverage_percent === null ? "-" : `${coverage.classification_coverage_percent}%`}</strong></div>
        <progress aria-label="אחוז העסקאות המסווגות" max={100} value={Number(coverage.classification_coverage_percent ?? 0)} />
        <div className={styles.coverageStats}><span><b>{coverage.classified_count}</b> מסווגות</span><span><b>{coverage.unclassified_count}</b> לא מסווגות</span><span><b>{coverage.review_required_count}</b> דורשות בדיקה</span><span><b>{coverage.total_accepted}</b> התקבלו</span></div>
        <details className={styles.coverageDetails}><summary>פירוט כיסוי הסיווג</summary><div className={styles.coverageBreakdown}>
          <div><h3>לפי סיווג</h3>{Object.entries(coverage.by_economic_class).filter(([, count]) => count > 0).map(([name, count]) => <span key={name}>{classLabels[name as EconomicClass]} <b>{count}</b></span>)}</div>
          <div><h3>לפי מקור</h3>{Object.entries(coverage.by_source).filter(([, count]) => count > 0).map(([name, count]) => <span key={name}>{sourceLabels[name as keyof typeof sourceLabels]} <b>{count}</b></span>)}</div>
          {Object.keys(coverage.issue_counts).length > 0 && <div><h3>מה צריך לבדוק</h3>{Object.entries(coverage.issue_counts).map(([name, count]) => <span key={name}>{issueLabel(name)} <b>{count}</b></span>)}</div>}
        </div></details>
      </Card>
    </section>}

    <Card className={styles.panel}>
      <div className={styles.panelHead}><div><h2>תור בדיקה</h2><p>סינון הרשומות והחלטה על סיווג לכל עסקה</p></div><span className={styles.countPill}>{queue.items.length} בעמוד</span></div>
      <div className={`${styles.filters} ${styles.primaryFilters}`}>
        <FormField id="filter-month" label="חודש"><MonthPicker id="filter-month" label="חודש" value={month} onChange={(value) => changeFilter(setMonth, value)} allowClear clearLabel="כל החודשים" placeholder="כל החודשים" /></FormField>
        <FormField id="filter-currency" label="מטבע"><Input id="filter-currency" value={currency} maxLength={8} onChange={(event) => changeFilter(setCurrency, event.target.value.toUpperCase())} /></FormField>
        <label className={styles.checkFilter}><input type="checkbox" checked={includeResolved} onChange={(event) => { setIncludeResolved(event.target.checked); setQueueCursor(undefined); setQueueHistory([]); }} />הצגת עסקאות שכבר סווגו</label>
      </div>
      <details className={styles.advancedFilters}><summary>מסננים נוספים{[accountKind, issue, economicClass, source].filter(Boolean).length > 0 ? ` (${[accountKind, issue, economicClass, source].filter(Boolean).length} פעילים)` : ""}</summary><div className={styles.filters}>
        <FormField id="filter-account" label="סוג חשבון"><Input id="filter-account" value={accountKind} onChange={(event) => changeFilter(setAccountKind, event.target.value)} /></FormField>
        <FormField id="filter-issue" label="קוד בדיקה"><Input id="filter-issue" value={issue} onChange={(event) => changeFilter(setIssue, event.target.value)} /></FormField>
        <FormField id="filter-class" label="סיווג כלכלי"><Select id="filter-class" value={economicClass} onChange={(event) => changeFilter(setEconomicClass, event.target.value)}><option value="">הכול</option>{economicClasses.map((value) => <option key={value} value={value}>{classLabels[value]}</option>)}</Select></FormField>
        <FormField id="filter-source" label="מקור סיווג"><Select id="filter-source" value={source} onChange={(event) => changeFilter(setSource, event.target.value)}><option value="">הכול</option>{sources.map((value) => <option key={value} value={value}>{sourceLabels[value]}</option>)}</Select></FormField>
      </div></details>
      {decisionFeedback && !queue.items.some((item) => item.transaction_id === decisionFeedback.transactionId) && <p className={styles.decisionFeedback} role={decisionFeedback.applied ? "status" : "alert"}>{decisionFeedback.text}</p>}
      {loading && <LoadingState label="מעדכנים תוצאות…" />}
      {!loading && queue.items.length === 0 && <EmptyState title="אין עסקאות בתור הזה" description="אפשר לשנות את המסננים או להציג גם עסקאות שכבר סווגו." />}
      <div className={styles.queue}>
        {queue.items.map((item) => {
          const classification = item.effective_classification;
          return <article className={styles.reviewItem} key={`${item.transaction_id}-${item.expected_override_version}`}>
            <div className={styles.transactionHead}>
              <div><h3>{item.description || "עסקה ללא תיאור"}</h3><p><bdi>{formatDate(item.booking_date)}</bdi> · עסקה <bdi>{item.transaction_id}</bdi> · {accountKindLabel(item.account_kind)}</p></div>
              <div className={styles.amount} dir="ltr"><bdi>{formatAmount(item.amount, item.currency)}</bdi></div>
            </div>
            <div className={styles.chips}><span>{classLabels[classification.economic_class]}</span><span>{behaviorLabels[classification.expense_behavior]}</span>{classification.analysis_category && <span>{classification.analysis_category}</span>}</div>
            {expanded === item.transaction_id && <p className={styles.explanation}>{classificationExplanation(classification.explanation)}</p>}
            {classification.issues.some((issue) => issue.code === "INVALID_CLASS_SIGN") && <p className={styles.directionHelp}>הסיווג שנשמר אינו מתאים לסכום המיובא. פתחו את העורך, השוו לפרטי המקור ובחרו תיקון סכום וכיוון או סיווג מתאים.</p>}
            {classification.issues.some((issue) => issue.code === "STALE_AMOUNT_CORRECTION") && <p className={styles.directionHelp}>סכומי המקור השתנו מאז תיקון הסכום. התיקון הקודם אינו מחושב בדוחות עד שתאמתו ותשמרו החלטה מחדש.</p>}
            {decisionFeedback?.transactionId === item.transaction_id && <p className={styles.decisionFeedback} role={decisionFeedback.applied ? "status" : "alert"}>{decisionFeedback.text}</p>}
            {expanded === item.transaction_id && <details className={styles.sourceDetails}><summary>פרטי מקור ובדיקה{item.issues.length ? ` (${item.issues.length})` : ""}</summary>
              {item.issues.length > 0 && <ul className={styles.issues}>{item.issues.map((problem, index) => <li key={`${problem.code}-${index}`}>{issueLabel(problem.code)}<details><summary>פרטים טכניים</summary><bdi>{problem.code}</bdi> - {problem.message}</details></li>)}</ul>}
              <p>{classification.explanation}</p><p>קטגוריה: {item.source_category}{item.source_movement_type ? ` · סוג תנועה: ${item.source_movement_type}` : ""}</p><pre>{JSON.stringify(item.source_fields, null, 2)}</pre>
              {item.saved_override?.effective_amount != null && <p>תיקון סכום פעיל: <bdi>{formatAmount(item.saved_override.effective_amount, item.currency)}</bdi> · {item.saved_override.reason}</p>}
            </details>}
            <Button className={styles.rowEdit} type="button" variant="outline" size="sm" aria-controls={`classification-editor-${item.transaction_id}`} aria-expanded={expanded === item.transaction_id} onClick={() => setExpanded(expanded === item.transaction_id ? null : item.transaction_id)}>{expanded === item.transaction_id ? "סגירת עורך" : "עריכת סיווג"}</Button>
            {expanded === item.transaction_id && <div className={styles.editorRegion} id={`classification-editor-${item.transaction_id}`} role="region" aria-label={`עריכת העסקה: ${item.description || "עסקה ללא תיאור"}`}><OverrideEditor item={item} busy={busy} choices={categoryChoices[item.currency]} listId={`${categoryListPrefix}-${item.currency}`} onSave={(values) => void onOverride(item, values)} onClear={() => void onClear(item)} /></div>}
          </article>;
        })}
      </div>
      <div className={styles.pagination}><Button variant="outline" disabled={!queueHistory.length || loading} onClick={() => { const previous = [...queueHistory]; const cursor = previous.pop(); setQueueHistory(previous); setQueueCursor(cursor); }}>הקודם</Button><Button variant="outline" disabled={!queue.nextCursor || loading} onClick={() => { setQueueHistory((previous) => [...previous, queueCursor]); setQueueCursor(queue.nextCursor || undefined); }}>הבא</Button></div>
    </Card>

    <details className={styles.ruleTools}><summary>כללי סיווג חוזרים</summary><div className={styles.ruleToolsBody}>
    <Card className={styles.panel}>
      <div className={styles.panelHead}><div><h2>כלל סיווג חוזר</h2><p>התאמה מדויקת לפי מאפייני המקור, ללא שינוי ידני של עסקאות קיימות</p></div></div>
      <RuleFields draft={draft} update={updateDraft} categoryListId={`${categoryListPrefix}-${ruleCurrency}`} categoryChoices={categoryChoices[ruleCurrency]} />
      <div className={styles.actions}><Button type="button" variant="outline" disabled={Boolean(busy) || !draft.source_category.trim()} onClick={() => void onPreviewRule()}>{busy === "rule-preview" ? "בודקים…" : "תצוגה מקדימה"}</Button><Button type="button" disabled={Boolean(busy) || !preview || preview.fingerprint !== draftFingerprint} onClick={() => void onCreateRule()}>{busy === "rule-create" ? "יוצרים…" : "יצירת כלל"}</Button></div>
      {preview && preview.fingerprint === draftFingerprint && <div className={styles.preview} role="status"><strong>הכלל יתאים ל־{preview.value.count} עסקאות שהתקבלו.</strong><span>{preview.value.expected_current_rule_id === null ? "לא קיימת כרגע גרסה קודמת למפתח זה." : `הגרסה הנוכחית היא ${preview.value.expected_current_rule_id}; היצירה תיצור גרסה חדשה.`}</span></div>}
    </Card>

    <Card className={styles.panel}>
      <div className={styles.panelHead}><div><h2>היסטוריית כללים</h2><p>כלל פעיל הוא הגרסה העדכנית למפתח ההתאמה המדויק</p></div></div>
      {rules.items.length === 0 ? <EmptyState title="אין עדיין כללים חוזרים" description="אפשר ליצור כלל לאחר בדיקת מספר העסקאות שיתאימו לו." /> : <div className={styles.ruleHistory}>{rules.items.map((rule) => <article className={styles.ruleRow} key={rule.id}>
        <div><strong>{rule.source_category} · {rule.direction === "debit" ? "חיוב" : rule.direction === "credit" ? "זיכוי" : "אפס"} · {rule.currency}</strong><p>{accountKindLabel(rule.account_kind)}{rule.source_movement_type ? ` · ${rule.source_movement_type}` : ""} · {classLabels[rule.economic_class]} · {behaviorLabels[rule.expense_behavior]}</p><small>גרסה {rule.revision} · מזהה {rule.id} · {rule.is_current ? rule.effective_active ? "פעילה" : "נוכחית ומושבתת" : "היסטורית"}{rule.reason ? ` · ${rule.reason}` : ""}</small></div>
        {rule.is_current && rule.effective_active && <Button type="button" variant="outline" size="sm" disabled={Boolean(busy)} onClick={() => void onDisableRule(rule)}>{busy === `rule-disable-${rule.id}` ? "מעדכנים…" : "השבתת כלל"}</Button>}
      </article>)}</div>}
      <div className={styles.pagination}><Button variant="outline" disabled={!ruleHistory.length || loading} onClick={() => { const previous = [...ruleHistory]; const cursor = previous.pop(); setRuleHistory(previous); setRuleCursor(cursor); }}>הקודם</Button><Button variant="outline" disabled={!rules.nextCursor || loading} onClick={() => { setRuleHistory((previous) => [...previous, ruleCursor]); setRuleCursor(rules.nextCursor || undefined); }}>הבא</Button></div>
    </Card>
    </div></details>
    <p className={styles.concurrencyNote}>עריכה והפעלת כללים נבדקות מול הגרסה שנטענה. שינוי קודם יגרום לבקשת רענון לפני שמירה. אם החיבור נקטע בזמן שמירה, יש לטעון מחדש ולבדוק את התוצאה לפני ניסיון נוסף.</p>
  </div>;
}
