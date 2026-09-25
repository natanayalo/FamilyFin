import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExpensesFeature } from "@/features/dashboard/expenses";
import { OverviewFeature } from "@/features/dashboard/overview";

const requestId = "fixture-dashboard-request";
const completeness = {
  source_period_complete: false,
  classification_complete: true,
  complete: false,
  source_coverage: "unknown",
  open_reconciliation_count: 1,
  unclassified_transaction_count: 0,
  unclassified_absolute_amount: "0",
  issues: ["SOURCE_PERIOD_INCOMPLETE"],
};
const metrics = {
  month: "2026-09-01",
  currency: "ILS",
  classification_policy_version: "fixture-policy",
  source_period_completeness: completeness,
  completeness,
  unclassified_transaction_count: 0,
  unclassified_absolute_amount: "0",
  data_freshness_date: "2026-09-30",
  gross_income: "1000.00",
  gross_consumption: "17.40",
  refunds: "0",
  net_consumption: "17.40",
  operating_surplus_or_deficit: "982.60",
  savings_rate: null,
  savings_contributions: "0",
  savings_withdrawals: "0",
  net_observed_savings_transfers: "0",
  fixed_consumption: "0",
  variable_consumption: "17.40",
  unknown_behavior_consumption: "0",
  spending_by_category: { food: "17.40" },
  historical_monthly_averages: {},
  rolling_three_month_averages: { gross_income: null, net_consumption: null, operating_surplus_or_deficit: null },
  rolling_six_month_averages: { gross_income: null, net_consumption: null, operating_surplus_or_deficit: null },
  month_over_month_changes: {},
  year_over_year_changes: {},
  breakdowns: {
    gross_income: { name: "gross_income", value: "1000.00", contributor_transaction_ids: [11], currency: "ILS" },
    net_consumption: { name: "net_consumption", value: "17.40", contributor_transaction_ids: [12], currency: "ILS" },
    "spending_by_category:food": { name: "spending_by_category:food", value: "17.40", contributor_transaction_ids: [12], currency: "ILS" },
    variable_consumption: { name: "variable_consumption", value: "17.40", contributor_transaction_ids: [12], currency: "ILS" },
  },
};
const point = { month: "2026-09-01", currency: "ILS", complete: false, issue_codes: ["SOURCE_PERIOD_INCOMPLETE"], metrics };
const filters = { start_month: "2026-09-01", end_month: "2026-09-01", currency: "ILS" };
const overview = {
  filters,
  selected_month: point,
  series: [point],
  headline: {
    income: "1000.00",
    net_consumption: "17.40",
    operating_surplus_or_deficit: "982.60",
    savings_rate: null,
    net_observed_savings_transfers: "0",
  },
  comparisons: [
    { metric: "gross_income", current: "1000.00", previous: null, delta: null, available: false, reason: "No prior month" },
    { metric: "gross_income:yoy", current: "1000.00", previous: null, delta: null, available: false, reason: "No prior year" },
  ],
  freshness_date: "2026-09-30",
  source_coverage: "unknown",
  currency: "ILS",
};
const expenses = {
  filters,
  selected_month: point,
  series: [point],
  categories: [{ category: "food", amount: "17.40", contributor_transaction_ids: [12] }],
  behavior_totals: { fixed: "0", variable: "17.40", unknown: "0" },
  category_comparisons: [
    { metric: "food:mom", current: "17.40", previous: null, delta: null, available: false, reason: "The comparison month is outside the selected range." },
    { metric: "food:yoy", current: "17.40", previous: null, delta: null, available: false, reason: "Prior year is unavailable" },
  ],
  potential_recurring_spending: [{
    label: "Potential pattern",
    normalized_description: "monthly market",
    analysis_category: "food",
    currency: "ILS",
    account_kind: "credit_card",
    median_amount: "17.40",
    minimum_amount: "17.40",
    maximum_amount: "17.40",
    amount_range: ["17.40", "17.40"],
    occurrence_months: ["2026-09-01"],
    contributor_transaction_ids: [12],
  }],
  unusual_category_spending: [{
    label: "Potential pattern",
    month: "2026-09-01",
    category: "food",
    currency: "ILS",
    baseline_median: "5.00",
    target_total: "17.40",
    difference: "12.40",
    direction: "high",
    rule: "Synthetic baseline rule",
    contributor_transaction_ids: [12],
  }],
  currency: "ILS",
};
const contribution = {
  transaction_id: 12,
  booking_date: "2026-09-02",
  description: "Synthetic grocery",
  amount: "-17.40",
  currency: "ILS",
  source_category: "food",
  movement_type: "purchase",
  account_label: "Fixture account",
  account_kind: "credit_card",
  effective_classification: "consumption",
  classification_source: "builtin_rule",
  analysis_category: "food",
  expense_behavior: "variable",
};

function response(data: unknown, status = 200) {
  return new Response(JSON.stringify({ data, meta: { request_id: requestId } }), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "private, no-store" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("dashboard feature adapters", () => {
  it("shows exact overview values, provisional state, applies filters, and drills into contributors", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/dashboard/contributors/query")) return response([contribution]);
      if (url.includes("/dashboard/overview")) return response(overview);
      throw new Error(`Unexpected request ${url} ${init?.method ?? "GET"}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<OverviewFeature />);

    expect(await screen.findAllByText("1000.00 ש״ח")).not.toHaveLength(0);
    expect(screen.getByText("הנתונים זמניים; חלק מההשוואות אינן זמינות")).toBeVisible();
    expect(screen.getByText("SOURCE_PERIOD_INCOMPLETE")).toBeVisible();

    fireEvent.change(screen.getByLabelText("מתאריך"), { target: { value: "2026-08" } });
    fireEvent.change(screen.getByLabelText("עד תאריך"), { target: { value: "2026-09" } });
    fireEvent.change(screen.getByRole("textbox", { name: "מטבע" }), { target: { value: "usd" } });
    fireEvent.click(screen.getByRole("button", { name: "עדכון תצוגה" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("currency=USD"))).toBe(true));

    await waitFor(() => expect(screen.getByLabelText("מדד או קטגוריה")).toBeVisible());
    fireEvent.change(screen.getByLabelText("מדד או קטגוריה"), { target: { value: "spending_by_category:food" } });
    fireEvent.click(await screen.findByRole("button", { name: "הצגת עסקאות תורמות (1)" }));
    expect(await screen.findByText("Synthetic grocery")).toBeVisible();
    expect(screen.getByText("-17.40 ש״ח")).toBeVisible();
    const contributorRequest = fetchMock.mock.calls.find(([url]) => String(url).includes("/dashboard/contributors/query"));
    expect(contributorRequest?.[1]?.method).toBe("POST");
    expect(contributorRequest?.[1]?.body).toBe(JSON.stringify({ transaction_ids: [12] }));
  });

  it("provides an expandable chart table with the exact service values", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(overview)));
    render(<OverviewFeature />);

    const summary = await screen.findByText("הצגת נתונים בטבלה");
    const details = summary.closest("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");

    fireEvent.click(summary);
    expect(details).toHaveAttribute("open");
    const table = within(details as HTMLElement).getByRole("table", {
      name: "נתוני תרשים: מגמת הכנסה, צריכה נטו ועודף תפעולי",
    });
    expect(within(table).getAllByText("09/2026")).toHaveLength(3);
    expect(within(table).getByText("הכנסה")).toBeVisible();
    expect(within(table).getByText("1000.00")).toBeVisible();
    expect(within(table).getByText("צריכה נטו")).toBeVisible();
    expect(within(table).getByText("17.40")).toBeVisible();
    expect(within(table).getByText("עודף תפעולי")).toBeVisible();
    expect(within(table).getByText("982.60")).toBeVisible();
  });

  it("shows expense behavior, comparisons, and heuristic insight drill-downs", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/dashboard/contributors/query")) return response([contribution]);
      if (url.includes("/dashboard/expenses")) return response(expenses);
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ExpensesFeature />);

    expect(await screen.findByRole("heading", { name: "התפלגות לפי קטגוריה" })).toBeVisible();
    expect(screen.getAllByText("17.40 ש״ח")).not.toHaveLength(0);
    expect(screen.getByText("לעומת חודש קודם אינה זמינה: חודש ההשוואה מחוץ לטווח שנבחר.")).toBeVisible();
    expect(screen.getByText("כל זיהוי הוא היוריסטי בלבד ואינו סיווג חשבונאי.")).toBeVisible();
    expect(screen.getByText("Synthetic baseline rule")).toBeVisible();
    expect(screen.getByText(/קטגוריות ההוצאות מבוססות על קטגוריית הניתוח \(analysis_category\), ובהיעדרה על קטגוריית המקור \(source_category\)/)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "הצגת העסקאות בדפוס (1)" }));
    expect(await screen.findByText("Synthetic grocery")).toBeVisible();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/dashboard/contributors/query"))).toBe(true);
  });
});
