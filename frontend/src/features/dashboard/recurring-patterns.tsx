"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiRequestError, apiRequest } from "@/lib/api";
import { ContributorDrilldown } from "./shared";
import { accountKindLabel, formatAmount, formatMonth } from "./format";
import type { DashboardExpenses, PotentialRecurringSpending, RecurringPatternReview } from "./types";

type ReviewStatus = RecurringPatternReview["status"];
type View = "pending" | "approved" | "previous";
const statusLabels: Record<ReviewStatus, string> = {
  pending: "ממתין לבדיקה", approved: "הוצאה חוזרת מאושרת", dismissed: "נדחה", stopped: "המעקב הופסק",
};

export function RecurringPatterns({ data, onSaved }: { data: DashboardExpenses; onSaved?: (review: RecurringPatternReview) => void }) {
  const [reviews, setReviews] = useState(data.recurring_pattern_reviews ?? []);
  const [view, setView] = useState<View>("pending");
  const [saving, setSaving] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const noticeRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    setReviews(data.recurring_pattern_reviews ?? []);
  }, [data.recurring_pattern_reviews]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (notice) noticeRef.current?.focus(); }, [notice]);

  const detected = new Map(data.potential_recurring_spending.map((item) => [item.pattern_id, item]));
  const decisions = new Map(reviews.map((review) => [review.pattern.pattern_id, review]));
  const pending = data.potential_recurring_spending.filter((item) => !decisions.has(item.pattern_id) || decisions.get(item.pattern_id)?.status === "pending");
  const approved = reviews.filter((review) => review.status === "approved");
  const previous = reviews.filter((review) => review.status === "dismissed" || review.status === "stopped");
  const items = view === "pending" ? pending : (view === "approved" ? approved : previous).map((review) => detected.get(review.pattern.pattern_id) ?? review.pattern);

  async function save(pattern: PotentialRecurringSpending, status: ReviewStatus) {
    if (saving) return;
    setSaving(pattern.pattern_id); setNotice(null); setError(null);
    try {
      const response = await apiRequest<RecurringPatternReview>(`/insights/recurring-patterns/${pattern.pattern_id}`, {
        method: "PUT",
        body: JSON.stringify({ ...data.filters, status, expected_updated_at: decisions.get(pattern.pattern_id)?.updated_at ?? null }),
      });
      // Finish server writes when navigating away. Update the parent report's
      // cache too, so changing the report month cannot resurrect an old suggestion.
      onSaved?.(response.data);
      if (!mounted.current) return;
      setReviews((current) => [...current.filter((item) => item.pattern.pattern_id !== pattern.pattern_id), response.data]);
      const messages: Record<ReviewStatus, string> = {
        approved: "ההוצאה אושרה ונוספה להוצאות המאושרות.",
        dismissed: "הדפוס נדחה. אפשר להחזיר אותו לבדיקה דרך החלטות קודמות.",
        stopped: "המעקב הופסק. ההחלטה נשמרה בהחלטות קודמות.",
        pending: detected.has(pattern.pattern_id) ? "הדפוס הוחזר לרשימת הבדיקה." : "ההחלטה בוטלה. הדפוס יוצג לבדיקה כשיזוהה בטווח שנבחר.",
      };
      setNotice(messages[status]);
    } catch (cause) {
      if (mounted.current) setError(cause instanceof ApiRequestError && cause.apiError?.code === "STALE_RECURRING_REVIEW"
        ? "ההחלטה השתנתה מאז שהעמוד נטען. רעננו את העמוד ובדקו את ההחלטה העדכנית לפני שמירה."
        : cause instanceof ApiRequestError && cause.status === 404
        ? "הדפוס כבר אינו זמין לבדיקה. רעננו את העמוד כדי לעדכן את הרשימה."
        : "לא התקבל אישור לשמירת ההחלטה. נסו שוב או רעננו את העמוד.");
    } finally {
      if (mounted.current) setSaving(null);
    }
  }

  return <div className="expense-recurring">
    <p className="expense-help">הזיהוי מבוסס על עסקאות בעלות תיאור דומה, פעם בחודש במשך שלושה חודשים לפחות. בדקו את העסקאות לפני אישור. הוצאה חוזרת אינה בהכרח הוצאה קבועה.</p>
    <p className="expense-help">ההחלטות נשמרות למשפחה. אישור מוסיף לרשימת ההוצאות החוזרות בלבד; הוא אינו משנה עסקאות, סיווגים או תחזיות.</p>
    <div className="expense-pattern-views" role="group" aria-label="מצב דפוסים חוזרים">
      {([
        ["pending", "לבדיקה", pending.length], ["approved", "הוצאות מאושרות", approved.length], ["previous", "החלטות קודמות", previous.length],
      ] as const).map(([value, label, count]) => <button key={value} type="button" aria-pressed={view === value} onClick={() => { setView(value); setError(null); }} disabled={saving !== null}>{label} ({count})</button>)}
    </div>
    {view !== "pending" && <p className="expense-help">ההחלטות השמורות מוצגות גם אם הדפוס לא זוהה בטווח המגמה הנוכחי.</p>}
    {notice && <p className="expense-review-notice" role="status" tabIndex={-1} ref={noticeRef}>{notice}</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {items.length === 0 ? <div className="dashboard-empty">{view === "approved" ? "עדיין לא אושרו הוצאות חוזרות." : view === "previous" ? "אין דפוסים שנדחו או שהמעקב אחריהם הופסק." : data.potential_recurring_spending.length ? "כל הדפוסים שזוהו כבר נבדקו." : "לא נמצאו דפוסים חוזרים בטווח שנבחר."}</div>
      : <div className="dashboard-insight-list">{items.map((item) => {
        const status = decisions.get(item.pattern_id)?.status ?? "pending";
        return <article className="dashboard-insight" aria-label={item.normalized_description} key={item.pattern_id}>
          <span className="expense-pattern-status">{statusLabels[status]}</span>
          <h4>{status === "approved" ? "הוצאה חוזרת" : "דפוס אפשרי"}: {item.normalized_description}</h4>
          <p>קטגוריה: {item.analysis_category} · חשבון: {accountKindLabel(item.account_kind)} · מטבע: {item.currency}</p>
          <p>חציון: {formatAmount(item.median_amount, item.currency)} · טווח: {formatAmount(item.minimum_amount, item.currency)}–{formatAmount(item.maximum_amount, item.currency)}</p>
          <p>חודשים: {item.occurrence_months.map(formatMonth).join(" · ")}</p>
          {!detected.has(item.pattern_id) && <p className="expense-pattern-snapshot">לא זוהה בטווח הנוכחי. מוצגים פרטי הזיהוי השמורים, שאינם מעידים שהחיוב עדיין פעיל.</p>}
          <ContributorDrilldown transactionIds={item.contributor_transaction_ids} currency={item.currency} label="הצגת העסקאות בדפוס" />
          <div className="expense-pattern-actions" aria-busy={saving === item.pattern_id}>
            {status === "pending" ? <>
              <Button size="sm" disabled={saving !== null} onClick={() => void save(item, "approved")}>אישור כהוצאה חוזרת</Button>
              <Button size="sm" variant="outline" disabled={saving !== null} onClick={() => void save(item, "dismissed")}>לא הוצאה חוזרת</Button>
            </> : <Button size="sm" variant="outline" disabled={saving !== null} onClick={() => void save(item, status === "approved" ? "stopped" : "pending")}>{status === "approved" ? "הפסקת מעקב" : "החזרה לבדיקה"}</Button>}
            {saving === item.pattern_id && <small role="status">שומרים החלטה…</small>}
          </div>
        </article>;
      })}</div>}
  </div>;
}
