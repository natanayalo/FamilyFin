import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ForecastsFeature } from "@/features/forecasts/ForecastsFeature";
import { getForecasts, getForecastProjection, getForecastRevisions, previewForecast } from "@/features/forecasts/api";
import { getScenarios, getRevision, getRevisions } from "@/features/planning/api";
import { getSnapshots } from "@/features/net-worth/api";
import type { PlanningRevision, PlanningScenario } from "@/features/planning/types";

vi.mock("@/features/forecasts/api", () => ({
  cloneForecast: vi.fn(), createForecast: vi.fn(), getForecastProjection: vi.fn(), getForecastRevisions: vi.fn(),
  getForecasts: vi.fn(), getNetWorthSeeds: vi.fn(), previewForecast: vi.fn(), restoreForecastRevision: vi.fn(),
  saveForecastRevision: vi.fn(), setForecastArchived: vi.fn(),
}));
vi.mock("@/features/planning/api", () => ({ getScenarios: vi.fn(), getRevision: vi.fn(), getRevisions: vi.fn() }));
vi.mock("@/features/net-worth/api", () => ({ getRevisions: vi.fn(), getSnapshots: vi.fn() }));
const scenario: PlanningScenario = { scenario_id: "s", name: "תכנון בדיקה", start_month: "2026-09-01", end_month: "2027-08-01", currency: "ILS", current_revision_number: 1, archived: false, clone_of_scenario_id: null, created_at: null, updated_at: null };
const revision: PlanningRevision = { scenario_id: "s", revision_id: "r", revision_number: 1, provisional: false, issue_codes: [], completeness_snapshot: [], expense_notes: [], notes: "", created_at: null,
  items: [{ id: "saving", kind: "savings_contribution", label: "חיסכון", amount: "250.25", category: null, frequency: "monthly", start_month: "2026-09-01", end_month: "2027-08-01", occurrence_month: null, origin: "manual", source_range: null, source_row: null, policy_version: "planning-v1", completeness_codes: [], contributor_transaction_ids: [], provenance: {}, notes: [] }] };

beforeEach(() => {
  vi.mocked(getForecasts).mockResolvedValue([]);
  vi.mocked(getSnapshots).mockResolvedValue([]);
  vi.mocked(getScenarios).mockResolvedValue({ data: [scenario] });
  vi.mocked(getRevisions).mockResolvedValue({ data: [revision] });
  vi.mocked(getRevision).mockResolvedValue({ data: revision });
  vi.mocked(previewForecast).mockRejectedValue(new Error("Intentional request-only test"));
});

it("preserves pool input focus and routes when renaming, and sends calendar dates as forecast month offsets", async () => {
  render(<ForecastsFeature />);
  fireEvent.click(await screen.findByRole("button", { name: "יצירת תחזית" }));
  await waitFor(() => expect(screen.getByRole("textbox", { name: "שם התחזית" })).toHaveFocus());
  fireEvent.click(screen.getByRole("button", { name: "המשך ליתרות פתיחה" }));
  const poolName = screen.getByRole("textbox", { name: "שם קופה 1" });
  poolName.focus();
  fireEvent.change(poolName, { target: { value: "קרן משפחתית" } });
  expect(poolName).toHaveFocus();
  expect(screen.getByRole("textbox", { name: "שם קופה 1" })).toBe(poolName);
  fireEvent.change(screen.getByRole("textbox", { name: "יתרת פתיחה קופה 1" }), { target: { value: "1000.25" } });
  fireEvent.click(screen.getByRole("button", { name: "המשך למקרי תחזית" }));
  const baseline = within(screen.getByRole("article", { name: "בסיסי" }));
  expect(baseline.getByRole("combobox", { name: "ניתוב בסיסי חיסכון" })).toHaveValue("קרן משפחתית");
  fireEvent.click(baseline.getByText("אירועים חד־פעמיים או העברות (0)"));
  fireEvent.click(baseline.getByRole("button", { name: "הוספת אירוע" }));
  fireEvent.click(baseline.getByRole("button", { name: "חודש אירוע 1 · בסיסי" }));
  fireEvent.click(await screen.findByRole("button", { name: "נובמבר 2026" }));
  fireEvent.click(screen.getByRole("button", { name: "חישוב תצוגה מקדימה" }));
  await waitFor(() => expect(previewForecast).toHaveBeenCalled());
  const payload = vi.mocked(previewForecast).mock.calls.at(-1)![0];
  expect(payload.starting_pools[0].opening_balance).toBe("1000.25");
  expect(payload.cases.every((item) => item.routes[0].pool_name === "קרן משפחתית")).toBe(true);
  expect(payload.cases.find((item) => item.role === "baseline")!.events[0].month).toBe(3);
});

it("returns focus on editor close and leaves the guided first-use state available", async () => {
  render(<ForecastsFeature />);
  fireEvent.click(await screen.findByRole("button", { name: "יצירת תחזית" }));
  await screen.findByRole("textbox", { name: "שם התחזית" });
  fireEvent.click(screen.getByRole("button", { name: "סגירת העורך" }));
  expect(screen.getByRole("button", { name: "תחזית חדשה" })).toHaveFocus();
  expect(screen.getByRole("heading", { name: "איך החיסכון שלכם יכול להתפתח?" })).toBeVisible();
});

it("shows a retryable load failure instead of offering first-use setup for an existing forecast", async () => {
  vi.mocked(getForecasts).mockResolvedValue([{ forecast_id: "f", name: "תחזית שמורה", scenario_id: "s", source_revision_id: "r", source_revision_number: 1, currency: "ILS", horizon_months: 36, current_revision_number: 1, archived: false, clone_of_forecast_id: null, created_at: null, updated_at: null }]);
  vi.mocked(getForecastRevisions).mockResolvedValue([{ forecast_id: "f", revision_id: "fr", revision_number: 1, source_revision_id: "r", source_revision_number: 1, policy_version: "v1", assumption_hash: "h", created_at: null, notes: "" }]);
  vi.mocked(getForecastProjection).mockRejectedValue(new Error("QA load failure"));
  render(<ForecastsFeature />);
  expect(await screen.findByRole("heading", { name: "לא ניתן לטעון את גרסת התחזית" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "איך החיסכון שלכם יכול להתפתח?" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "לנסות שוב" })).toBeEnabled();
});
