import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { ForecastResults } from "@/features/forecasts/ForecastsFeature";
import type { ForecastDraft, ForecastMonth, ForecastRole } from "@/features/forecasts/types";

export function forecastDraft(): ForecastDraft {
  const months: ForecastMonth[] = Array.from({ length: 36 }, (_, index) => {
    const date = new Date(Date.UTC(2026, 8 + index, 1));
    const month = `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-01`;
    return { month, month_number: index + 1, income: "1000", expenses: "500", contributions: "250", requested_withdrawals: "0",
      fulfilled_withdrawals: "0", unmet_funding_gap: "0", swept_surplus: "12", estimated_returns: "10",
      cash_before_sweep: "250", cash_after_sweep: "238", ending_balance: index === 11 ? "4300.35" : index === 23 ? "7600.35" : "10900.35",
      requested_capital_draws: "0", fulfilled_capital_draws: "0", pools: [
        { month, month_number: index + 1, pool_id: "a", pool_name: "חיסכון", pool_type: "cash", opening_balance: "1000.25",
          estimated_return: "10", contributions: "250", swept_surplus: "12", requested_withdrawal: "0", fulfilled_withdrawal: "0",
          unmet_funding_gap: "0", requested_capital_draw: "0", fulfilled_capital_draw: "0", closing_balance: "1272.25" },
        { month, month_number: index + 1, pool_id: "b", pool_name: "השקעות", pool_type: "investment", opening_balance: "200.10",
          estimated_return: "0", contributions: "0", swept_surplus: "0", requested_withdrawal: "0", fulfilled_withdrawal: "0",
          unmet_funding_gap: "0", requested_capital_draw: "0", fulfilled_capital_draw: "0", closing_balance: "200.10" },
      ] };
  });
  const projection = { forecast_id: "f", scenario_id: "s", source_revision_id: "r", source_revision_number: 1, currency: "ILS",
    months, provisional: false, issue_codes: [], first_shortfall_month: null, assumption_hash: "h", methodology: null };
  const points = [
    { horizon_month: 12, ending_balance: "4300.35", contributions: "3000", swept_surplus: "144", withdrawals: "0", estimated_returns: "100", funding_gap: "0" },
    { horizon_month: 24, ending_balance: "7600.35", contributions: "6000", swept_surplus: "288", withdrawals: "0", estimated_returns: "400", funding_gap: "0" },
    { horizon_month: 36, ending_balance: "10900.35", contributions: "9000", swept_surplus: "432", withdrawals: "0", estimated_returns: "700", funding_gap: "0" },
  ];
  return { projections: { baseline: projection, conservative: structuredClone(projection), optimistic: { ...structuredClone(projection), months: months.map((month) => ({ ...month, ending_balance: "11900.35" })) } },
    comparison: { currency: "ILS", checkpoints: { baseline: points, conservative: points, optimistic: points } },
    assumption_hash: "h", validation_errors: [] };
}
function Results({ draft = forecastDraft() }: { draft?: ForecastDraft }) {
  const [horizon, setHorizon] = useState<12 | 24 | 36>(36);
  const [role, setRole] = useState<ForecastRole>("baseline");
  return <ForecastResults draft={draft} snapshot={null} horizon={horizon} setHorizon={setHorizon} selectedRole={role} setSelectedRole={setRole} />;
}

describe("Forecast results", () => {
  it("separates exact starting balances and cumulative deposits/returns from the ending balance", () => {
    render(<Results />);
    const summary = within(screen.getByLabelText("הרכב תחזית בסיסי"));
    expect(summary.getByText(/1,200.35/)).toBeVisible();
    expect(summary.getByText(/9,000/)).toBeVisible();
    expect(summary.getByText(/700/)).toBeVisible();
    fireEvent.change(screen.getByRole("combobox", { name: "אופק תחזית" }), { target: { value: "12" } });
    expect(summary.getByText(/3,000/)).toBeVisible();
    expect(summary.queryByText(/9,000/)).not.toBeInTheDocument();
    expect(summary.getByText(/4,300.35/)).toBeVisible();
  });
  it("updates the summary and detail when another assumption case is selected", () => {
    render(<Results />);
    fireEvent.click(screen.getByRole("button", { name: /אופטימי/ }));
    expect(screen.getByRole("button", { name: /אופטימי/ })).toHaveAttribute("aria-pressed", "true");
    expect(within(screen.getByLabelText("הרכב תחזית אופטימי")).getByText(/11,900.35/)).toBeVisible();
    expect(screen.getByText("תזרימים לפי ההנחות במקרה אופטימי.")).toBeVisible();
  });
  it("never substitutes one month's flows for unavailable cumulative checkpoints", () => {
    const draft = forecastDraft(); draft.comparison = null;
    render(<Results draft={draft} />);
    expect(within(screen.getByLabelText("הרכב תחזית בסיסי")).getAllByText("לא זמין")).toHaveLength(2);
    expect(within(screen.getByLabelText("הרכב תחזית בסיסי")).queryByText(/250/)).not.toBeInTheDocument();
  });
  it("shows a shortfall only inside the selected horizon", () => {
    const draft = forecastDraft(); draft.projections.baseline.first_shortfall_month = 24;
    render(<Results draft={draft} />);
    expect(screen.getByRole("status")).toHaveTextContent("אוגוסט 2028");
    fireEvent.change(screen.getByRole("combobox", { name: "אופק תחזית" }), { target: { value: "12" } });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
  it("browses months with bounded shared dates and distinguishes swept surplus by pool", async () => {
    render(<Results />);
    const picker = screen.getByRole("button", { name: "חודש בתחזית" });
    fireEvent.click(screen.getByRole("button", { name: "חודש בתחזית: החודש הבא" }));
    expect(picker).toHaveTextContent("אוקטובר 2026");
    fireEvent.change(screen.getByRole("combobox", { name: "אופק תחזית" }), { target: { value: "12" } });
    fireEvent.click(picker);
    fireEvent.click(await screen.findByRole("button", { name: "השנה הבאה" }));
    expect(screen.getByRole("button", { name: "אוגוסט 2027" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "ספטמבר 2027" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "אוגוסט 2027" }));
    expect(screen.getByText("חודש 12")).toBeVisible();
    expect(screen.getAllByText("עודף שהועבר").length).toBeGreaterThan(1);
  });
  it("keeps digits beyond floating point precision intact in opening totals", () => {
    const draft = forecastDraft();
    draft.projections.baseline.months[0].pools[0].opening_balance = "9007199254740993.01";
    draft.projections.baseline.months[0].pools[1].opening_balance = "0.09";
    render(<Results draft={draft} />);
    expect(within(screen.getByLabelText("הרכב תחזית בסיסי")).getByText(/9,007,199,254,740,993.10/)).toBeVisible();
  });
});
