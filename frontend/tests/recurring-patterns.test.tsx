import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RecurringPatterns } from "@/features/dashboard/recurring-patterns";
import type { DashboardExpenses, PotentialRecurringSpending, RecurringPatternReview } from "@/features/dashboard/types";

const pattern: PotentialRecurringSpending = {
  pattern_id: "pattern-fixture", label: "Potential pattern", normalized_description: "מנוי בדיקה",
  analysis_category: "תקשורת", account_kind: "card", currency: "ILS", median_amount: "50.00",
  minimum_amount: "49.90", maximum_amount: "50.00", amount_range: ["49.90", "50.00"],
  occurrence_months: ["2026-07-01", "2026-08-01", "2026-09-01"], contributor_transaction_ids: [1, 2, 3],
};
const filters = { start_month: "2026-07-01", end_month: "2026-09-01", currency: "ILS" };
function data(reviews: RecurringPatternReview[] = [], detected = [pattern]): DashboardExpenses {
  return { filters, currency: "ILS", potential_recurring_spending: detected, recurring_pattern_reviews: reviews } as DashboardExpenses;
}
function saved(status: RecurringPatternReview["status"]): RecurringPatternReview {
  return { pattern, status, updated_at: "2026-10-17T01:00:00Z" };
}
afterEach(() => vi.unstubAllGlobals());

describe("recurring pattern decisions", () => {
  it("saves approval before moving a suggestion, can stop tracking, and can restore review", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      new Response(JSON.stringify({ data: saved(JSON.parse(String(init?.body)).status) })));
    vi.stubGlobal("fetch", fetchMock);
    render(<RecurringPatterns data={data()} />);
    fireEvent.click(screen.getByRole("button", { name: "אישור כהוצאה חוזרת" }));
    await screen.findByText("ההוצאה אושרה ונוספה להוצאות המאושרות.");
    await waitFor(() => expect(screen.getByRole("status")).toHaveFocus());
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/insights/recurring-patterns/pattern-fixture");
    expect(fetchMock.mock.calls[0][1]?.method).toBe("PUT");
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ ...filters, status: "approved" });
    expect(screen.queryByRole("button", { name: "אישור כהוצאה חוזרת" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "הוצאות מאושרות (1)" }));
    expect(screen.getByText("הוצאה חוזרת מאושרת")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "הפסקת מעקב" }));
    await screen.findByText("המעקב הופסק. ההחלטה נשמרה בהחלטות קודמות.");
    fireEvent.click(screen.getByRole("button", { name: "החלטות קודמות (1)" }));
    expect(screen.getByText("המעקב הופסק")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "החזרה לבדיקה" }));
    await screen.findByText("הדפוס הוחזר לרשימת הבדיקה.");
    fireEvent.click(screen.getByRole("button", { name: "לבדיקה (1)" }));
    expect(screen.getByRole("button", { name: "אישור כהוצאה חוזרת" })).toBeVisible();
  });

  it("keeps dismissed patterns out of suggestions and restores saved decisions after a reload", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ data: saved("dismissed") }))));
    const { unmount } = render(<RecurringPatterns data={data()} />);
    fireEvent.click(screen.getByRole("button", { name: "לא הוצאה חוזרת" }));
    await screen.findByText("הדפוס נדחה. אפשר להחזיר אותו לבדיקה דרך החלטות קודמות.");
    expect(screen.getByRole("button", { name: "לבדיקה (0)" })).toBeVisible();
    unmount();
    render(<RecurringPatterns data={data([saved("dismissed")])} />);
    expect(screen.queryByRole("button", { name: "אישור כהוצאה חוזרת" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "החלטות קודמות (1)" }));
    expect(screen.getByRole("button", { name: "החזרה לבדיקה" })).toBeVisible();
  });

  it("retains approved expenses outside the detector window and distinguishes saved evidence", () => {
    render(<RecurringPatterns data={data([saved("approved")], [])} />);
    fireEvent.click(screen.getByRole("button", { name: "הוצאות מאושרות (1)" }));
    expect(screen.getByRole("heading", { name: "הוצאה חוזרת: מנוי בדיקה" })).toBeVisible();
    expect(screen.getByText(/מוצגים פרטי הזיהוי השמורים/)).toBeVisible();
    expect(screen.getByText(/אינם מעידים שהחיוב עדיין פעיל/)).toBeVisible();
  });

  it("blocks duplicate submissions and leaves the suggestion available after a failed save", async () => {
    let fail!: (response: Response) => void;
    const fetchMock = vi.fn(() => new Promise<Response>((resolve) => { fail = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    render(<RecurringPatterns data={data()} />);
    const approve = screen.getByRole("button", { name: "אישור כהוצאה חוזרת" });
    fireEvent.click(approve); fireEvent.click(approve);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "לא הוצאה חוזרת" })).toBeDisabled();
    fail(new Response(JSON.stringify({ error: { message: "synthetic failure" } }), { status: 500 }));
    await screen.findByRole("alert");
    await waitFor(() => expect(approve).toBeEnabled());
    expect(screen.getByRole("button", { name: "לבדיקה (1)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("הוצאה חוזרת מאושרת")).not.toBeInTheDocument();
  });
});
