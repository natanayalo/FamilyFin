import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  compareActual,
  compareScenarios,
  getCategories,
  getProjection,
  getRevisions,
  getScenario,
  getScenarios,
  getSuggestedStartMonth,
} from "@/features/planning/api";
import { PlanningPage } from "@/features/planning/planning-page";

vi.mock("@/features/planning/api", () => ({
  setArchived: vi.fn(), cloneScenario: vi.fn(), commitCsvSeed: vi.fn(), commitHistorySeed: vi.fn(),
  compareActual: vi.fn(), compareScenarios: vi.fn(), createScenario: vi.fn(), getCategories: vi.fn(),
  getProjection: vi.fn(), getRevisions: vi.fn(), getScenario: vi.fn(), getScenarios: vi.fn(),
  getSuggestedStartMonth: vi.fn(), postProjection: vi.fn(), previewCsvSeed: vi.fn(), previewHistorySeed: vi.fn(),
  restoreRevision: vi.fn(), saveRevision: vi.fn(),
}));

const scenario = {
  scenario_id: "scenario-1", name: "תקציב משפחתי", currency: "ILS", start_month: "2026-09-01",
  end_month: "2027-08-01", current_revision_number: 1, archived: false,
  clone_of_scenario_id: null, created_at: null, updated_at: null,
};
const revision = {
  revision_id: "revision-1", scenario_id: "scenario-1", revision_number: 1, items: [], notes: "",
  created_at: "2026-09-20T12:00:00Z", provisional: false, issue_codes: [],
  completeness_snapshot: [], expense_notes: [],
};

describe("Planning feature presentation", () => {
  beforeEach(() => {
    vi.mocked(getScenarios).mockResolvedValue({ data: [scenario] });
    vi.mocked(getScenario).mockResolvedValue({ data: scenario });
    vi.mocked(getRevisions).mockResolvedValue({ data: [revision] });
    vi.mocked(getProjection).mockResolvedValue({ data: {
      scenario_id: scenario.scenario_id, revision_number: 1, currency: "ILS", provisional: false, issue_codes: [],
      months: [{
        month: "2026-09-01", currency: "ILS", income: "10000", expenses: "7000", savings_contributions: "1000",
        savings_withdrawals: "0", operating_surplus: "3000", net_planned_savings: "1000",
        cash_remaining_after_savings: "2000", expenses_by_category: {}, income_by_category: {},
        contributor_item_ids: {}, unmapped_expense_categories: [],
      }],
    } });
    vi.mocked(getCategories).mockResolvedValue({ data: [] });
    vi.mocked(getSuggestedStartMonth).mockResolvedValue({ data: "2026-09-01" });
    vi.mocked(compareActual).mockResolvedValue({ data: {
      scenario_id: "scenario-1", revision_number: 1, currency: "ILS", months: [],
    } });
    vi.mocked(compareScenarios).mockResolvedValue({ data: { currency: "ILS", months: [], scenarios: [] } });
  });

  it("leads with the selected month and keeps annual and management tools collapsed", async () => {
    render(<PlanningPage />);
    await screen.findByRole("heading", { name: "תקציב משפחתי" });
    const month = screen.getByRole("region", { name: "התכנון לספטמבר 2026" });
    expect(within(month).getByText("נשאר לאחר החיסכון")).toBeVisible();
    expect(within(month).getByText(/2,000/)).toBeVisible();
    const annual = document.querySelector('details[aria-label="התכנון לכל השנה"]')!;
    const tools = document.querySelector('details[aria-label="כלי תכנון נוספים"]')!;
    expect(annual).not.toHaveAttribute("open");
    expect(tools).not.toHaveAttribute("open");
    expect(month.compareDocumentPosition(annual) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("button", { name: "חודש התכנון" })).toHaveTextContent("ספטמבר 2026");
    expect(screen.getByText("תכנון מול ביצוע · ספטמבר 2026")).toBeVisible();
  });
  it("focuses and describes invalid assumption fields, including repeated attempts", async () => {
    vi.mocked(getScenarios).mockResolvedValue({ data: [] });
    render(<PlanningPage />);
    fireEvent.click(await screen.findByRole("button", { name: "תרחיש חדש" }));
    const label = await screen.findByLabelText("שם ההנחה");
    const next = screen.getByRole("button", { name: "המשך" });
    fireEvent.click(next);
    expect(label).toHaveFocus();
    expect(label).toHaveAttribute("aria-invalid", "true");
    expect(label).toHaveAccessibleDescription("הוסיפו שם להנחה 1.");
    next.focus();
    fireEvent.click(next);
    expect(label).toHaveFocus();
    fireEvent.change(label, { target: { value: "שכירות" } });
    const amount = screen.getByLabelText(/סכום במטבע התרחיש/);
    fireEvent.change(amount, { target: { value: "-100" } });
    fireEvent.click(next);
    expect(amount).toHaveFocus();
    expect(amount).toHaveAttribute("aria-invalid", "true");
    expect(label).not.toHaveAttribute("aria-invalid");
    fireEvent.change(amount, { target: { value: "100" } });
    fireEvent.click(next);
    const end = screen.getByLabelText("עד חודש");
    fireEvent.click(end);
    expect(await screen.findByRole("button", { name: "השנה הבאה" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "ספטמבר 2027" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "אוגוסט 2027" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "אוגוסט 2027" }));
    expect(end).toHaveTextContent("אוגוסט 2027");
    fireEvent.click(end);
    fireEvent.click(await screen.findByRole("button", { name: "השנה הקודמת" }));
    fireEvent.click(screen.getByRole("button", { name: "ספטמבר 2026" }));
    const start = screen.getByRole("button", { name: "מחודש" });
    fireEvent.click(start);
    fireEvent.click(await screen.findByRole("button", { name: "אוקטובר 2026" }));
    fireEvent.click(screen.getByRole("button", { name: "המשך" }));
    expect(start).toHaveFocus();
    expect(start).toHaveAttribute("aria-invalid", "true");
    expect(start).toHaveAccessibleDescription(/טווח החודשים בהנחה 1 צריך להיכלל/);

  });

  it("changes planned totals with the shared month picker and flags a funding gap", async () => {
    const data = (await getProjection("scenario-1")).data;
    const second = { ...data.months[0], month: "2026-10-01", expenses: "12000.25", cash_remaining_after_savings: "-3000.25" };
    vi.mocked(getProjection).mockResolvedValue({ data: { ...data, months: [...data.months, second] } });
    render(<PlanningPage />);
    await screen.findByRole("heading", { name: "תקציב משפחתי" });
    fireEvent.click(screen.getByRole("button", { name: "חודש התכנון" }));
    fireEvent.click(await screen.findByRole("button", { name: "אוקטובר 2026" }));
    const month = screen.getByRole("region", { name: "התכנון לאוקטובר 2026" });
    expect(within(month).getByText(/12,000.25/)).toBeVisible();
    expect(within(month).getByText(/-3,000.25/)).toBeVisible();
    expect(within(month).getByText("חסר לאחר החיסכון")).toBeVisible();
    expect(screen.getByText("תכנון מול ביצוע · אוקטובר 2026")).toBeVisible();
  });

  it("keeps missing actuals unavailable and labels partial observed data", async () => {
    const planned = (await getProjection("scenario-1")).data.months[0];
    vi.mocked(compareActual).mockResolvedValue({ data: {
      scenario_id: "scenario-1", revision_number: 1, currency: "ILS", months: [{
        month: planned.month, planned, complete: false, issue_codes: ["SOURCE_PERIOD_PARTIAL_OR_UNKNOWN"],
        actual_income: null, actual_expenses: "17.40", actual_surplus: null, actual_net_savings: null,
        expense_variances: null, category_variance_unavailable: [], income_variance: null,
        surplus_variance: null, savings_variance: null,
      }],
    } });
    render(<PlanningPage />);
    fireEvent.click(await screen.findByRole("button", { name: "טעינת השוואה לביצוע" }));
    const table = await screen.findByRole("table", { name: "תכנון וביצוע לחודש הנבחר" });
    expect(within(table).getByRole("columnheader", { name: "ביצוע חלקי" })).toBeVisible();
    expect(within(table).getByText(/17.40/)).toBeVisible();
    expect(within(table).getAllByText("לא זמין")).toHaveLength(3);
    expect(screen.queryByText(/הפרש בהכנסות:/)).not.toBeInTheDocument();
  });

  it("shows signed differences only for a complete, matching revision", async () => {
    const planned = (await getProjection("scenario-1")).data.months[0];
    vi.mocked(compareActual).mockResolvedValue({ data: {
      scenario_id: "scenario-1", revision_number: 1, currency: "ILS", months: [{
        month: planned.month, planned, complete: true, issue_codes: [], actual_income: "11000",
        actual_expenses: "7500", actual_surplus: "3500", actual_net_savings: "1000",
        expense_variances: {}, category_variance_unavailable: [], income_variance: "1000",
        surplus_variance: "500", savings_variance: "0",
      }],
    } });
    render(<PlanningPage />);
    fireEvent.click(await screen.findByRole("button", { name: "טעינת השוואה לביצוע" }));
    expect(await screen.findByText("נתוני הביצוע מלאים לחודש זה.")).toBeVisible();
    expect(screen.getByText(/הפרש = ביצוע פחות תכנון/)).toBeVisible();
    expect(screen.getByText(/הפרש בהכנסות:/)).toBeVisible();
  });

  it("does not reload the scenario when toggling comparison choices", async () => {
    const other = { ...scenario, scenario_id: "scenario-2", name: "תכנון חלופי" };
    vi.mocked(getScenarios).mockResolvedValue({ data: [scenario, other] });
    render(<PlanningPage />);
    await screen.findByRole("heading", { name: "תקציב משפחתי" });
    const calls = vi.mocked(getScenarios).mock.calls.length;
    const tools = document.querySelector('details[aria-label="כלי תכנון נוספים"]')!;
    fireEvent.click(tools.querySelector("summary")!);
    fireEvent.click(screen.getByRole("checkbox", { name: /תכנון חלופי/ }));
    expect(screen.getByRole("button", { name: "השוואת הנבחרים (2)" })).toBeEnabled();
    await waitFor(() => expect(getScenarios).toHaveBeenCalledTimes(calls));
  });

  it("rejects actuals from a newer revision instead of mixing them with the displayed plan", async () => {
    vi.mocked(compareActual).mockResolvedValue({ data: { scenario_id: "scenario-1", revision_number: 2, currency: "ILS", months: [] } });
    render(<PlanningPage />);
    fireEvent.click(await screen.findByRole("button", { name: "טעינת השוואה לביצוע" }));
    expect(await screen.findByText("התכנון השתנה. רעננו את התרחיש לפני השוואה לביצוע.")).toBeVisible();
    expect(screen.queryByRole("table", { name: "תכנון וביצוע לחודש הנבחר" })).not.toBeInTheDocument();
  });

  it("uses the new scenario horizon rather than the selected saved scenario in timing controls", async () => {
    vi.mocked(getSuggestedStartMonth).mockResolvedValue({ data: "2028-02-01" });
    render(<PlanningPage />);
    await screen.findByRole("heading", { name: "תקציב משפחתי" });
    fireEvent.click(screen.getByRole("button", { name: "תרחיש חדש" }));
    const name = await screen.findByLabelText("שם ההנחה");
    fireEvent.change(name, { target: { value: "שכירות" } });
    fireEvent.change(screen.getByLabelText(/סכום במטבע התרחיש/), { target: { value: "5000.25" } });
    fireEvent.click(screen.getByRole("button", { name: "המשך" }));
    fireEvent.click(screen.getByRole("button", { name: "עד חודש" }));
    expect(await screen.findByRole("button", { name: "ינואר 2029" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "פברואר 2029" })).toBeDisabled();
  });

  it("ignores an actuals response after switching scenarios", async () => {
    let finish!: (value: Awaited<ReturnType<typeof compareActual>>) => void;
    vi.mocked(compareActual).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const other = { ...scenario, scenario_id: "scenario-2", name: "תכנון אחר" };
    vi.mocked(getScenarios).mockResolvedValue({ data: [scenario, other] });
    vi.mocked(getScenario).mockImplementation(async (id) => ({ data: id === other.scenario_id ? other : scenario }));
    render(<PlanningPage />);
    fireEvent.click(await screen.findByRole("button", { name: "טעינת השוואה לביצוע" }));
    fireEvent.change(screen.getByRole("combobox", { name: "התכנון הנבחר" }), { target: { value: other.scenario_id } });
    await screen.findByRole("heading", { name: "תכנון אחר" });
    finish({ data: { scenario_id: scenario.scenario_id, revision_number: 1, currency: "ILS", months: [] } });
    await waitFor(() => expect(screen.getByRole("button", { name: "טעינת השוואה לביצוע" })).toBeEnabled());
    expect(screen.queryByText("אין השוואת ביצוע זמינה לחודש הנבחר.")).not.toBeInTheDocument();
  });

  it("returns keyboard focus after cancelling the editor", async () => {
    vi.mocked(getScenarios).mockResolvedValue({ data: [] });
    render(<PlanningPage />);
    fireEvent.click(await screen.findByRole("button", { name: "בניית התכנון הראשון" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "שם התרחיש" })).toHaveFocus());
    fireEvent.click(screen.getByRole("button", { name: "ביטול וזריקת טיוטה" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "תרחיש חדש" })).toHaveFocus());
  });

});
