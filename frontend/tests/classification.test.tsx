import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ClassificationFeature } from "@/features/classification/ClassificationFeature";

const result = {
  transaction_id: 1,
  booking_date: "2026-09-09",
  amount: "-75",
  currency: "ILS",
  account_kind: "bank",
  source_category: "food",
  source_movement_type: "purchase",
  economic_class: "consumption",
  expense_behavior: "unknown",
  analysis_category: "food",
  source: "builtin_rule",
  policy_version: "classification-v1",
  explanation: "Ordinary negative bank or card purchase.",
  issues: [],
  override_ids: [],
};
const queueItem = {
  transaction_id: 1,
  booking_date: "2026-09-09",
  amount: "-75",
  currency: "ILS",
  description: "Synthetic market",
  account_kind: "bank",
  source_category: "food",
  source_movement_type: "purchase",
  effective_classification: result,
  source_fields: { normalized: { source: "fixture" } },
  issues: [],
  expected_override_version: 12,
  expected_classification_state: "a".repeat(64),
};
const coverage = {
  month: "2026-09",
  currency: "ILS",
  total_accepted: 3,
  classified_count: 2,
  unclassified_count: 1,
  review_required_count: 1,
  classification_coverage_percent: "66.7",
  by_economic_class: { income: 0, consumption: 2, refund: 0, internal_transfer: 0, savings_transfer: 0, credit_card_settlement: 0, debt_principal: 0, unclassified: 1 },
  by_source: { override: 0, reusable_rule: 0, builtin_rule: 2, unclassified: 1 },
  issue_counts: { UNCLASSIFIED_TRANSACTION: 1 },
};

function response(data: unknown, meta: Record<string, unknown> = {}) {
  return new Response(JSON.stringify({ data, meta }), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("classification feature", () => {
  it("shows service coverage and submits an override against the loaded version", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/classification/coverage")) return response(coverage);
      if (url.includes("/classification/review-queue")) return response([queueItem]);
      if (url.includes("/classification/rules")) return response([]);
      if (url.includes("/transactions/1/override") && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        expect(body.expected_override_version).toBe(12);
        expect(body.expected_classification_state).toBe("a".repeat(64));
        expect(body.reason).toBe("Saved from classification review");
        return response({ result: { ...result, source: "override" }, override_version: 15, expected_classification_state: "b".repeat(64) });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ClassificationFeature />);
    expect(await screen.findByText("66.7%")).toBeInTheDocument();
    expect(screen.getByText("כיסוי סיווג")).toBeInTheDocument();
    expect(screen.getByText("Synthetic market")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "עריכת סיווג" }));
    const save = screen.getByRole("button", { name: "שמירת תיקון" });
    const form = save.closest("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form!);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/classification/transactions/1/override"),
      expect.objectContaining({ method: "POST" }),
    ));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url, init]) =>
      String(url).includes("/transactions/1/override") && init?.method === "POST",
    )).toHaveLength(1));
  });

  it("keeps the rule create disabled until a matching preview and sends its revision precondition", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/classification/coverage")) return response(coverage);
      if (url.includes("/classification/review-queue")) return response([]);
      if (url.includes("/classification/rules/previews")) {
        return response({ count: 2, rule: {}, expected_current_rule_id: 8 });
      }
      if (url.endsWith("/classification/rules") && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        expect(body.expected_current_rule_id).toBe(8);
        return response({ id: 9, revision: 2 });
      }
      if (url.includes("/classification/rules")) return response([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ClassificationFeature />);
    await screen.findByText("כיסוי סיווג");
    const create = screen.getByRole("button", { name: "יצירת כלל" });
    expect(create).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/קטגוריית מקור/), { target: { value: "food" } });
    fireEvent.click(screen.getByRole("button", { name: "תצוגה מקדימה" }));
    expect(await screen.findByText("הכלל יתאים ל־2 עסקאות שהתקבלו.")).toBeInTheDocument();
    expect(create).toBeEnabled();
    fireEvent.click(create);
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) =>
      String(url).endsWith("/classification/rules") && init?.method === "POST",
    )).toBe(true));
  });
});
