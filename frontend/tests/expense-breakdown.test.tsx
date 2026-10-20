import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExpenseBreakdown } from "@/features/dashboard/expense-breakdown";
import type { DashboardExpenses, TransactionContribution } from "@/features/dashboard/types";

function transaction(id: number, category: string, classification = "consumption"): TransactionContribution {
  return { transaction_id: id, booking_date: "2026-09-02", description: `Transaction ${id}`, amount: classification === "refund" ? "20.00" : "-100.00", currency: "ILS", source_category: category, analysis_category: null, effective_classification: classification, account_label: "Test account", account_kind: "card", movement_type: null, classification_source: "test", expense_behavior: "unknown" };
}
const fixtures = [transaction(1, "food"), { ...transaction(2, "legacy", "refund"), analysis_category: "food", amount: "-20.00" }, transaction(3, "bills"), transaction(4, "travel", "refund")];
function report(rows = fixtures, month = "2026-09"): DashboardExpenses {
  const categories = [...new Set(rows.filter((row) => row.effective_classification === "consumption").map((row) => row.analysis_category || row.source_category))].map((category) => ({ category, amount: "100.00", contributor_transaction_ids: rows.filter((row) => row.effective_classification === "consumption" && (row.analysis_category || row.source_category) === category).map((row) => row.transaction_id) }));
  // The component only reads the month scope, category summary and contributor IDs.
  return { currency: "ILS", filters: { start_month: `${month}-01`, end_month: `${month}-01`, currency: "ILS" }, categories, selected_month: { metrics: { breakdowns: { net_consumption: { contributor_transaction_ids: rows.map((row) => row.transaction_id) } } } } } as unknown as DashboardExpenses;
}
function response(rows: TransactionContribution[], status = 200) {
  return new Response(JSON.stringify(status === 200 ? { data: rows } : { error: { message: "שגיאת טעינה לבדיקה", request_id: "test-error" } }), { status });
}
function serve(rows = fixtures) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    expect(String(input)).toContain("/dashboard/contributors/query");
    const ids: number[] = JSON.parse(String(init?.body)).transaction_ids;
    return response(rows.filter((row) => ids.includes(row.transaction_id)));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
afterEach(() => vi.unstubAllGlobals());

describe("unified expense category and transaction flow", () => {
  it("filters one automatically loaded table by category and transaction type without refetching", async () => {
    const fetchMock = serve();
    render(<ExpenseBreakdown data={report()} />);
    const table = await screen.findByRole("table", { name: "עסקאות החודש לפי הסינון שנבחר" });
    expect(within(table).getAllByRole("row")).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: "עסקאות בקטגוריה food (1)" }));
    expect(screen.getByRole("heading", { name: "עסקאות החודש" })).toHaveFocus();
    expect(screen.getByText("Transaction 1")).toBeVisible();
    expect(screen.getByText("Transaction 2")).toBeVisible();
    expect(screen.queryByText("Transaction 3")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "החזרים בלבד" }));
    expect(screen.queryByText("Transaction 1")).not.toBeInTheDocument();
    expect(screen.getByText("Transaction 2")).toBeVisible(); // Negative refund amounts still use their classification.
    expect(screen.queryByText("Transaction 4")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "ניקוי סינון קטגוריה" }));
    expect(screen.getByText("Transaction 4")).toBeVisible(); // Refund-only categories remain reachable.
    expect(screen.getByRole("button", { name: "החזרים בלבד" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "הוצאות בלבד" }));
    expect(screen.getByText("Transaction 3")).toBeVisible();
    expect(screen.queryByText("Transaction 2")).not.toBeInTheDocument();
    expect(screen.getAllByRole("table")).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows a scoped empty state instead of falling back to another category", async () => {
    serve();
    render(<ExpenseBreakdown data={report()} />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "עסקאות בקטגוריה bills (1)" }));
    fireEvent.click(screen.getByRole("button", { name: "החזרים בלבד" }));
    expect(screen.getByText("אין עסקאות מהסוג שנבחר בקטגוריה זו בחודש זה.")).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "עסקאות בקטגוריה bills (1)" })).toHaveAttribute("aria-pressed", "true");
  });

  it("batches contributor requests within the API limit and paginates the filtered rows", async () => {
    const rows = Array.from({ length: 201 }, (_, index) => transaction(index + 1, index < 2 ? "food" : "bills"));
    const fetchMock = serve(rows);
    render(<ExpenseBreakdown data={report(rows)} />);
    const table = await screen.findByRole("table");
    expect(fetchMock.mock.calls.map(([, init]) => JSON.parse(String(init?.body)).transaction_ids.length)).toEqual([100, 100, 1]);
    expect(within(table).getAllByRole("row")).toHaveLength(11);
    expect(screen.getByText("Transaction 201")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "הבא" }));
    expect(screen.getByText("עמוד 2 מתוך 21")).toBeVisible();
    expect(screen.getByText("Transaction 191")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "עסקאות בקטגוריה food (2)" }));
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(screen.queryByRole("navigation", { name: "עמודי עסקאות" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("discards a partial batch on failure and retries the full month", async () => {
    const rows = Array.from({ length: 101 }, (_, index) => transaction(index + 1, "food"));
    const fetchMock = vi.fn().mockResolvedValueOnce(response(rows.slice(0, 100))).mockResolvedValueOnce(response([], 503)).mockResolvedValueOnce(response(rows.slice(0, 100))).mockResolvedValueOnce(response(rows.slice(100)));
    vi.stubGlobal("fetch", fetchMock);
    render(<ExpenseBreakdown data={report(rows)} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("שגיאת טעינה לבדיקה");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "לנסות שוב" }));
    expect(await screen.findByRole("table")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("does not display a late response from the previous report month", async () => {
    let resolveOld!: (response: Response) => void;
    const oldRequest = new Promise<Response>((resolve) => { resolveOld = resolve; });
    const newRows = [transaction(8, "new")];
    vi.stubGlobal("fetch", vi.fn().mockReturnValueOnce(oldRequest).mockResolvedValue(response(newRows)));
    const { rerender } = render(<ExpenseBreakdown key="september" data={report()} />);
    rerender(<ExpenseBreakdown key="october" data={report(newRows, "2026-10")} />);
    expect(await screen.findByText("Transaction 8")).toBeVisible();
    await act(async () => resolveOld(response(fixtures)));
    await waitFor(() => expect(screen.queryByText("Transaction 1")).not.toBeInTheDocument());
    expect(screen.getByText(/אוקטובר 2026 בלבד/)).toBeVisible();
  });
});
