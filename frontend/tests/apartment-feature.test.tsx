import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError } from "@/lib/api";
import { getForecastRevisions, getForecasts } from "@/features/forecasts/api";
import {
  cloneApartmentStudy,
  createApartmentStudy,
  getApartmentOptions,
  getApartmentPoolBalances,
  getApartmentRevisionProjection,
  getApartmentRevisions,
  getApartmentStudies,
  previewApartment,
  saveApartmentRevision,
} from "@/features/apartment/api";
import type { ApartmentAlternative, ApartmentDraft, ApartmentSavedProjection, ApartmentSourceOptions, ApartmentStudy } from "@/features/apartment/types";
import { ApartmentFeature } from "@/features/apartment/apartment-feature";

vi.mock("@/lib/api", () => ({
  ApiRequestError: class ApiRequestError extends Error {
    status: number;
    apiError?: { code?: string; message?: string };
    constructor(message: string, status: number, apiError?: { code?: string; message?: string }) {
      super(message); this.status = status; this.apiError = apiError;
    }
  },
  apiRequest: vi.fn(),
}));

vi.mock("@/features/forecasts/api", () => ({ getForecasts: vi.fn(), getForecastRevisions: vi.fn() }));
vi.mock("@/features/apartment/api", () => ({
  cloneApartmentStudy: vi.fn(),
  createApartmentStudy: vi.fn(),
  getApartmentOptions: vi.fn(),
  getApartmentPoolBalances: vi.fn(),
  getApartmentRevisionProjection: vi.fn(),
  getApartmentRevisions: vi.fn(),
  getApartmentStudies: vi.fn(),
  previewApartment: vi.fn(),
  restoreApartmentRevision: vi.fn(),
  saveApartmentRevision: vi.fn(),
  setApartmentArchived: vi.fn(),
}));

const forecast = {
  forecast_id: "forecast-1", name: "תחזית משפחתית", scenario_id: "scenario-1",
  source_revision_id: "plan-revision-1", source_revision_number: 1, currency: "ILS", horizon_months: 36,
  current_revision_number: 1, archived: false, clone_of_forecast_id: null, created_at: null, updated_at: null,
};
const forecastRevision = {
  forecast_id: "forecast-1", revision_id: "forecast-revision-1", revision_number: 1,
  assumption_hash: "forecast-hash-1", created_at: null, scenario_id: "scenario-1",
  source_revision_id: "plan-revision-1", source_revision_number: 1, currency: "ILS", horizon_months: 36,
  policy_version: "savings-forecast-v1", provisional_acknowledged: false, net_worth_snapshot_revision_id: null,
  starting_pools: [{ name: "קופת מזומן", pool_type: "cash" as const, opening_balance: "90000.50", as_of_date: "2026-10-01" }],
  cases: [], notes: "",
};
const sourceOptions: ApartmentSourceOptions = {
  forecast,
  forecast_revision: forecastRevision,
  planning_source: {
    at_creation: { scenario_id: "scenario-1", revision_id: "plan-revision-1", revision_number: 1, provisional: false, issue_codes: [] },
    current: { scenario_id: "scenario-1", revision_id: "plan-revision-1", revision_number: 1, provisional: false, issue_codes: [] },
  },
  expense_lines: [],
};
const study: ApartmentStudy = {
  study_id: "study-1", name: "דירת החלומות", forecast_id: "forecast-1", forecast_revision_id: "forecast-revision-1",
  forecast_revision_number: 1, forecast_assumption_hash: "forecast-hash-1", currency: "ILS", current_revision_number: 1,
  archived: false, clone_of_study_id: null, created_at: null, updated_at: null,
};
const savedAlternative: ApartmentAlternative = {
  name: "חלופה 1", forecast_role: "baseline", purchase_month: 12, property_price: "500000", family_gift: "0",
  purchase_costs: [{ label: "מסים", amount: "10000" }], equity_requirement: { mode: "percentage", value: "0.2" },
  mortgage: { principal: "400000", annual_nominal_rate: "0.04", term_months: 360 },
  pool_draws: [{ pool_name: "קופת מזומן", amount: "100000" }], stopped_housing_line_ids: [],
  housing_costs: [{ label: "תחזוקה", amount: "800" }], confirmed: true,
};
const snapshot = {
  study_id: "study-1", revision_id: "study-revision-1", revision_number: 1, assumption_hash: "study-hash-1", created_at: null,
  forecast_id: "forecast-1", forecast_revision_id: "forecast-revision-1", forecast_revision_number: 1,
  forecast_assumption_hash: "forecast-hash-1", currency: "ILS", policy_version: "apartment-planning-v1",
  source_quality_acknowledged: false,
  guardrails: { minimum_remaining_liquidity: null, maximum_housing_cost_to_income_ratio: null },
  alternatives: [savedAlternative, { ...savedAlternative, name: "חלופה 2", property_price: "600000" }], notes: "saved",
};
const revision = {
  revision_id: "study-revision-1", study_id: "study-1", revision_number: 1,
  forecast_id: "forecast-1", forecast_revision_id: "forecast-revision-1", forecast_revision_number: 1,
  forecast_assumption_hash: "forecast-hash-1", policy_version: "apartment-planning-v1", assumption_hash: "study-hash-1", created_at: null, notes: "saved",
};

function resultDraft(alternatives: ApartmentAlternative[] = [savedAlternative, { ...savedAlternative, name: "חלופה 2" }]): ApartmentDraft {
  return {
    assumption_hash: "draft-hash",
    source_quality_warning: false,
    comparison: { currency: "ILS", alternatives: alternatives.map((alternative) => ({
      alternative_name: alternative.name, purchase_month: alternative.purchase_month, purchase_price: alternative.property_price,
      forecast_role: alternative.forecast_role, mortgage_payment: "1900.00", total_interest: "250000.00", closing_gap: "0",
      remaining_liquidity: "1000", maximum_housing_ratio: "0.2", worst_monthly_cash_flow: "2000", month_36_balance: "22000",
    })) },
    projections: alternatives.map((alternative) => ({
      alternative_name: alternative.name, forecast_role: alternative.forecast_role, purchase_month: alternative.purchase_month,
      purchase_price: alternative.property_price, purchase_costs: "10000", total_uses: "510000", proposed_equity: "100000",
      required_equity: "100000", mortgage_principal: alternative.mortgage.principal, family_gift: alternative.family_gift,
      requested_pool_draws: "100000", fulfilled_pool_draws: "100000", total_sources: "500000", funding_gap: "10000",
      available_pool_balances: { "קופת מזומן": "120000" }, remaining_liquidity_by_pool: { "קופת מזומן": "20000" },
      remaining_liquidity: "20000", mortgage_schedule: [], total_interest: "250000", total_repayment: "650000",
      monthly: [], readiness: { equity_requirement_met: true, sources_cover_uses: false, mortgage_within_required_equity: true, minimum_liquidity_met: true, housing_ratio_guardrail_met: true, ready: false, failures: ["פער מימון"] },
      maximum_housing_ratio: "0.2", worst_monthly_cash_flow: "2000", month_36_balance: "22000",
    })),
  };
}

function savedProjection(): ApartmentSavedProjection {
  return {
    snapshot: snapshot as ApartmentSavedProjection["snapshot"], draft: resultDraft(),
    source_verification: sourceOptions.planning_source,
  };
}

function setBaseMocks(existingStudy = false) {
  vi.mocked(getForecasts).mockResolvedValue([forecast]);
  vi.mocked(getForecastRevisions).mockResolvedValue([{
    revision_id: "forecast-revision-1", forecast_id: "forecast-1", revision_number: 1,
    source_revision_id: "plan-revision-1", source_revision_number: 1, policy_version: "savings-forecast-v1",
    assumption_hash: "forecast-hash-1", created_at: null, notes: "",
  }]);
  vi.mocked(getApartmentStudies).mockResolvedValue(existingStudy ? [study] : []);
  vi.mocked(getApartmentOptions).mockResolvedValue(sourceOptions);
  vi.mocked(getApartmentPoolBalances).mockResolvedValue({ "קופת מזומן": "120000" });
  vi.mocked(getApartmentRevisions).mockResolvedValue([revision]);
  vi.mocked(getApartmentRevisionProjection).mockResolvedValue(savedProjection());
  vi.mocked(previewApartment).mockImplementation(async (input) => resultDraft(input.alternatives));
}

async function previewAndConfirm() {
  fireEvent.click(screen.getByRole("button", { name: "חישוב / רענון טיוטה" }));
  const confirmBoxes = await screen.findAllByRole("checkbox", { name: /עיינתי בחלופה הזו/ });
  await waitFor(() => expect(confirmBoxes[0]).toBeEnabled());
  fireEvent.click(confirmBoxes[0]);
  fireEvent.click(confirmBoxes[1]);
  await waitFor(() => expect(vi.mocked(previewApartment)).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.getByRole("button", { name: "יצירת מחקר" })).toBeEnabled());
}

describe("Apartment plan feature", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    vi.clearAllMocks();
    setBaseMocks();
  });

  it("previews with exact decimal and percent strings, then creates only after both confirmations", async () => {
    const created = { ...study, study_id: "new-study", name: "תחזית משפחתית · תכנון דירה" };
    vi.mocked(createApartmentStudy).mockResolvedValue(created);
    vi.mocked(getApartmentStudies).mockResolvedValue([created]);
    render(<ApartmentFeature />);
    await screen.findByRole("heading", { name: "מחקר רכישת דירה חדש" });

    fireEvent.change(screen.getAllByLabelText("ריבית שנתית נומינלית (%)")[0], { target: { value: "7.5" } });
    fireEvent.change(screen.getAllByLabelText("מחיר הנכס")[0], { target: { value: "500000.123456789" } });
    fireEvent.click(screen.getByRole("button", { name: "חישוב / רענון טיוטה" }));
    const initialConfirmations = await screen.findAllByRole("checkbox", { name: /עיינתי בחלופה הזו/ });
    await waitFor(() => expect(initialConfirmations[0]).toBeEnabled());
    const initialInput = vi.mocked(previewApartment).mock.calls.at(-1)?.[0];
    expect(initialInput?.alternatives[0].mortgage.annual_nominal_rate).toBe("0.075");
    expect(initialInput?.alternatives[0].property_price).toBe("500000.123456789");

    const confirms = screen.getAllByRole("checkbox", { name: /עיינתי בחלופה הזו/ });
    fireEvent.click(confirms[0]);
    fireEvent.click(confirms[1]);
    await waitFor(() => expect(vi.mocked(previewApartment)).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "יצירת מחקר" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "יצירת מחקר" }));
    await waitFor(() => expect(createApartmentStudy).toHaveBeenCalled());
    const createInput = vi.mocked(createApartmentStudy).mock.calls[0][0];
    expect(createInput.alternatives.every((item) => item.confirmed)).toBe(true);
    expect(createInput.alternatives[0].property_price).toBe("500000.123456789");
  });

  it("keeps create locked after a lost response until list refresh and explicit closure", async () => {
    vi.mocked(createApartmentStudy).mockRejectedValue(new ApiRequestError("lost response", 0));
    render(<ApartmentFeature />);
    await screen.findByRole("heading", { name: "מחקר רכישת דירה חדש" });
    await previewAndConfirm();
    const createButton = screen.getByRole("button", { name: "יצירת מחקר" });
    fireEvent.click(createButton);
    await screen.findByText("תוצאת היצירה אינה ידועה.");
    expect(createButton).toBeDisabled();
    const closeButton = await screen.findByRole("button", { name: "בדקתי את הרשימה — סגירת הפעולה הממתינה" });
    expect(createButton).toBeDisabled();
    fireEvent.click(closeButton);
    await waitFor(() => expect(screen.queryByText("תוצאת היצירה אינה ידועה.")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "יצירת מחקר" })).toBeEnabled();
    expect(createApartmentStudy).toHaveBeenCalledTimes(1);
  });

  it("keeps clone locked after a lost response until reconciliation and explicit closure", async () => {
    setBaseMocks(true);
    vi.mocked(cloneApartmentStudy).mockRejectedValue(new ApiRequestError("server unavailable", 503));
    render(<ApartmentFeature />);
    await screen.findByRole("heading", { name: "מחקר רכישת דירה חדש" });
    fireEvent.change(screen.getByLabelText("מחקר דירה"), { target: { value: "study-1" } });
    await screen.findByRole("heading", { name: "דירת החלומות" });
    const cloneButton = await screen.findByRole("button", { name: "שכפול למחקר חדש" });
    fireEvent.click(cloneButton);
    await screen.findByText("תוצאת השכפול אינה ידועה.");
    expect(cloneButton).toBeDisabled();
    const closeButton = await screen.findByRole("button", { name: "בדקתי את הרשימה — סגירת הפעולה הממתינה" });
    fireEvent.click(closeButton);
    await waitFor(() => expect(screen.queryByText("תוצאת השכפול אינה ידועה.")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "שכפול למחקר חדש" })).toBeEnabled();
    expect(cloneApartmentStudy).toHaveBeenCalledTimes(1);
  });

  it("blocks a stale revision draft until the latest saved revision is reopened", async () => {
    setBaseMocks(true);
    vi.mocked(saveApartmentRevision).mockRejectedValue(new ApiRequestError("stale", 409, {
      code: "STALE_REVISION", message: "The apartment study changed",
    }));
    render(<ApartmentFeature />);
    await screen.findByRole("heading", { name: "מחקר רכישת דירה חדש" });
    fireEvent.change(screen.getByLabelText("מחקר דירה"), { target: { value: "study-1" } });
    await screen.findByRole("heading", { name: "דירת החלומות" });
    const confirmations = await screen.findAllByRole("checkbox", { name: /עיינתי בחלופה הזו/ });
    fireEvent.click(confirmations[0]); fireEvent.click(confirmations[1]);
    await waitFor(() => expect(screen.getByRole("button", { name: "שמירת גרסה חדשה" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "שמירת גרסה חדשה" }));
    await screen.findByText("נשמרה גרסה חדשה בזמן העבודה. רעננו את המחקר ופתחו גרסה עדכנית לפני שמירה.");
    expect(screen.getByRole("button", { name: "שמירת גרסה חדשה" })).toBeDisabled();

    vi.mocked(getApartmentStudies).mockResolvedValue([{ ...study, current_revision_number: 2 }]);
    vi.mocked(getApartmentRevisions).mockResolvedValue([revision, {
      ...revision, revision_id: "study-revision-2", revision_number: 2, assumption_hash: "study-hash-2",
    }]);
    vi.mocked(getApartmentRevisionProjection).mockResolvedValue({
      ...savedProjection(),
      snapshot: { ...snapshot, revision_number: 2 } as ApartmentSavedProjection["snapshot"],
    });
    fireEvent.click(screen.getByRole("button", { name: "טעינת הגרסה העדכנית" }));
    await waitFor(() => expect(getApartmentRevisionProjection).toHaveBeenLastCalledWith("study-1", 2));
    await waitFor(() => expect(screen.getByLabelText("גרסת מחקר לעיון")).toHaveValue("2"));
    expect(screen.getByRole("button", { name: "שמירת גרסה חדשה" })).toBeDisabled();
  });
});
