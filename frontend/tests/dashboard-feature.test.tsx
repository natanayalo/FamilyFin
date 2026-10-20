import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExpensesFeature } from "@/features/dashboard/expenses";
import { SeriesChart } from "@/features/dashboard/shared";
import { OverviewFeature } from "@/features/dashboard/overview";
import { resetDashboardFilters } from "@/features/dashboard/filter-state";

vi.mock("@/features/dashboard/recent-transactions", () => ({ RecentTransactions: () => null }));

async function chooseMonth(label: string, month: string) {
  fireEvent.click(screen.getByRole("button", { name: label }));
  fireEvent.click(await screen.findByRole("button", { name: month }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
}

function openExpenseDetails(title?: string) {
  const outer = screen.getByText("תובנות ופירוט נוסף").closest("details")!;
  if (!outer.open) fireEvent.click(outer.querySelector("summary")!);
  if (title) {
    const details = within(outer).getByText(title, { exact: true }).closest("details")!;
    if (!details.open) fireEvent.click(details.querySelector("summary")!);
  }
}

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
  accepted_transaction_count: 2,
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
    pattern_id: "monthly-market-fixture",
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

afterEach(() => { vi.unstubAllGlobals(); resetDashboardFilters(); });

describe("dashboard feature adapters", () => {
  it("leads with three monthly figures, keeps detail collapsed, and scopes the review task", async () => {
    const selected = { ...point, metrics: { ...metrics, completeness: { ...completeness, unclassified_transaction_count: 2 } } };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => { expect(String(input)).toContain("/dashboard/overview"); return response({ ...overview, selected_month: selected }); });
    vi.stubGlobal("fetch", fetchMock);
    render(<OverviewFeature />);
    await screen.findByText("סה״כ הכנסות");
    const headline = document.querySelector(".dashboard-headlines")!;
    expect(headline.children).toHaveLength(3);
    const trend = screen.getByRole("heading", { name: "הכנסות והוצאות בחודשים האחרונים" });
    expect(headline.compareDocumentPosition(trend) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: "סקירת עסקאות (2)" })).toHaveAttribute("href", "/classification?month=2026-09&currency=ILS&economic_class=unclassified");
    expect(screen.getByText("כיסוי ואיכות הנתונים").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("סטטיסטיקה והשוואות").closest("details")).not.toHaveAttribute("open");
    fireEvent.click(screen.getByRole("button", { name: "חודש לסקירה: החודש הקודם" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("end_month=2026-08"))).toBe(true));
  });

  it("shows exact overview values, provisional state, applies filters, and drills into contributors", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/dashboard/contributors/query")) return response([contribution]);
      if (url.includes("/dashboard/overview")) return response(overview);
      throw new Error(`Unexpected request ${url} ${init?.method ?? "GET"}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<OverviewFeature />);

    expect(await screen.findAllByText("\u2067\u20661,000.00\u2069 ש״ח\u2069")).not.toHaveLength(0);
    expect(await screen.findByText("סכומי החודש זמניים עד להשלמת הבדיקות")).toBeVisible();
    fireEvent.click(screen.getByText("כיסוי ואיכות הנתונים"));
    expect(screen.getByText("הנתונים זמניים; חלק מההשוואות אינן זמינות")).toBeVisible();
    expect(screen.getAllByText("תקופת המקור אינה מלאה").length).toBeGreaterThan(0);
    expect(document.querySelectorAll('a[href="#month-quality"]')).toHaveLength(1);
    fireEvent.click(screen.getByText("פרטים טכניים"));
    expect(screen.getAllByText("תקופת המקור אינה מלאה").length).toBeGreaterThan(0);
    expect(screen.getByText("SOURCE_PERIOD_INCOMPLETE")).not.toBeVisible();
    fireEvent.click(screen.getByText("קוד לזיהוי תקלה"));
    expect(screen.getByText("SOURCE_PERIOD_INCOMPLETE")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /תקופת הדוח/ }));
    await chooseMonth("חודש התחלה", "אוגוסט 2026");
    await chooseMonth("חודש סיום", "ספטמבר 2026");
    expect(screen.queryByRole("textbox", { name: "מטבע" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "עדכון גרף" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("start_month=2026-08") && String(url).includes("currency=ILS"))).toBe(true));

    fireEvent.click(screen.getByText("בדיקת העסקאות שמרכיבות את הסיכום"));
    await waitFor(() => expect(screen.getByLabelText("מדד או קטגוריה")).toBeVisible());
    fireEvent.change(screen.getByLabelText("מדד או קטגוריה"), { target: { value: "spending_by_category:food" } });
    fireEvent.click(await screen.findByRole("button", { name: "הצגת עסקאות תורמות (1)" }));
    expect(await screen.findByText("Synthetic grocery")).toBeVisible();
    expect(screen.getByText("\u2067\u2066-17.40\u2069 ש״ח\u2069")).toBeVisible();
    const contributorRequest = fetchMock.mock.calls.find(([url]) => String(url).includes("/dashboard/contributors/query"));
    expect(contributorRequest?.[1]?.method).toBe("POST");
    expect(contributorRequest?.[1]?.body).toBe(JSON.stringify({ transaction_ids: [12] }));
  });

  it("shows Hebrew diagnostics first and keeps known and unknown codes behind their disclosure", async () => {
    const issues = ["FUTURE_ISSUE_CODE", "SOURCE_PERIOD_PARTIAL_OR_UNKNOWN", "UNCLASSIFIED_TRANSACTIONS"];
    const unknown = { ...point, issue_codes: issues, metrics: {
      ...metrics, completeness: { ...completeness, issues },
    } };
    vi.stubGlobal("fetch", vi.fn(async () => response({ ...overview, selected_month: unknown, series: [unknown] })));
    render(<OverviewFeature />);
    await screen.findByText("סה״כ הכנסות");
    fireEvent.click(screen.getByText("כיסוי ואיכות הנתונים"));
    expect(screen.getAllByText("נדרשת בדיקת נתונים")).not.toHaveLength(0);
    expect(screen.getAllByText("כיסוי תקופת המקור חלקי או לא ידוע").length).toBeGreaterThan(0);
    expect(screen.getAllByText("קיימות עסקאות ללא סיווג").length).toBeGreaterThan(0);
    for (const issue of issues) expect(screen.getByText(issue)).not.toBeVisible();
    fireEvent.click(screen.getByText("פרטים טכניים"));
    for (const issue of issues) expect(screen.getByText(issue)).not.toBeVisible();
    const diagnostics = screen.getByText("פרטים טכניים").closest("details")!;
    const codes = within(diagnostics).getAllByText("קוד לזיהוי תקלה");
    for (let index = 0; index < issues.length; index += 1) {
      fireEvent.click(codes[index]);
      expect(screen.getByText(issues[index])).toBeVisible();
    }
  });

  it("provides a chronological, scrollable chart matrix with exact values and distinct missing and zero months", async () => {
    const zero = { ...point, month: "2026-07-01", complete: true, issue_codes: [], metrics: {
      ...metrics, month: "2026-07-01", accepted_transaction_count: 0,
      source_period_completeness: { ...completeness, source_period_complete: true, complete: true },
      completeness: { ...completeness, complete: true },
      gross_income: "0.0000", net_consumption: "0.0000", operating_surplus_or_deficit: "0.0000", breakdowns: {},
    } };
    const missing = { ...point, month: "2026-08-01", complete: false, issue_codes: [], metrics: {
      ...metrics, month: "2026-08-01", accepted_transaction_count: 0, breakdowns: {},
    } };
    vi.stubGlobal("fetch", vi.fn(async () => response({ ...overview, series: [point, missing, zero] })));
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
    expect(Array.from(table.querySelectorAll("thead th")).map((cell) => cell.textContent?.trim())).toEqual(["07/2026", "08/2026", "09/2026", "מדד"]);
    const incomeRow = within(table).getByRole("rowheader", { name: "הכנסה" }).closest("tr")!;
    expect(within(incomeRow).getByText("\u2067\u20660.0000\u2069 ש״ח\u2069")).toBeVisible();
    expect(within(incomeRow).getByText("אין נתונים")).toBeVisible();
    expect(within(incomeRow).getByText("\u2067\u20661,000.00\u2069 ש״ח\u2069")).toBeVisible();
    const consumptionRow = within(table).getByRole("rowheader", { name: "צריכה נטו" }).closest("tr")!;
    expect(within(consumptionRow).getByText("\u2067\u206617.40\u2069 ש״ח\u2069")).toBeVisible();
    const surplusRow = within(table).getByRole("rowheader", { name: "עודף תפעולי" }).closest("tr")!;
    expect(within(surplusRow).getByText("\u2067\u2066982.60\u2069 ש״ח\u2069")).toBeVisible();
    const scrollRegion = within(details as HTMLElement).getByRole("region", { name: "גלילת נתוני התרשים" });
    expect(scrollRegion).toHaveAttribute("tabindex", "0");
  });

  it("switches period statistics populations, explains them, and formats service values exactly", async () => {
    const periodStatistics = {
      observed: {
        included_months: ["2026-08-01", "2026-09-01"], partial_months: ["2026-09-01"], excluded_months: [], sample_count: 2,
        metrics: {
          gross_income: { mean: "1500.0000", p25: "1250.0000", median: "1500.0000", p75: "1750.0000" },
          net_consumption: { mean: "25.0000", p25: "20.0000", median: "25.0000", p75: "30.0000" },
          operating_surplus_or_deficit: { mean: "1475.0000", p25: "1230.0000", median: "1475.0000", p75: "1720.0000" },
        },
      },
      complete: {
        included_months: ["2026-08-01"], partial_months: [], excluded_months: ["2026-09-01"], sample_count: 1,
        metrics: {
          gross_income: { mean: "2000.0000", p25: "2000.0000", median: "2000.0000", p75: "2000.0000" },
          net_consumption: { mean: "40.0000", p25: "40.0000", median: "40.0000", p75: "40.0000" },
          operating_surplus_or_deficit: { mean: "1960.0000", p25: "1960.0000", median: "1960.0000", p75: "1960.0000" },
        },
      },
    };
    vi.stubGlobal("fetch", vi.fn(async () => response({ ...overview, filters: { start_month: "2026-08-01", end_month: "2026-09-01", currency: "ILS" }, period_statistics: periodStatistics })));
    render(<OverviewFeature />);

    await screen.findAllByText("\u2067\u20661,000.00\u2069 ש״ח\u2069");
    fireEvent.click(screen.getByText("סטטיסטיקה והשוואות"));
    const statisticsPanel = (await screen.findByRole("heading", { name: "ממוצע לחודש בתקופה" })).closest("section")!;
    expect(within(statisticsPanel).getByText(/לפי תקופת הגרף/)).toBeVisible();
    expect(within(statisticsPanel).getAllByText(/אוגוסט 2026 עד ספטמבר 2026/).length).toBeGreaterThan(0);
    const populationCount = statisticsPanel.querySelector(".dashboard-period-statistics-count");
    expect(populationCount).toHaveTextContent("2 חודשים");
    expect(within(statisticsPanel).getByText(/כולל 1 חודש עם נתונים חלקיים/)).toBeVisible();
    fireEvent.click(within(statisticsPanel).getByText("חציון, אחוזונים ואופן החישוב"));
    expect(within(statisticsPanel).getAllByText("\u2067\u20661,500.0000\u2069 ש״ח\u2069").length).toBeGreaterThan(0);
    expect(within(statisticsPanel).getByText(/כל חודש בחישוב מקבל משקל שווה/)).toBeVisible();
    fireEvent.click(within(statisticsPanel).getByRole("radio", { name: /חודשים מלאים בלבד/ }));
    expect(populationCount).toHaveTextContent("1 חודש");
    expect(within(statisticsPanel).getAllByText("\u2067\u20662,000.0000\u2069 ש״ח\u2069").length).toBeGreaterThan(0);
    expect(within(statisticsPanel).getByText(/1 חודש עם נתונים חלקיים לא נכלל/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /תקופת הדוח/ }));
    await chooseMonth("חודש סיום", "אוקטובר 2026");
    fireEvent.click(screen.getByRole("button", { name: "עדכון גרף" }));
    await waitFor(() => expect(screen.getByRole("radio", { name: /חודשים מלאים בלבד/ })).toBeChecked());
  });

  it("shows a clear empty state when the service returns no statistics sample", async () => {
    const emptyPopulation = {
      included_months: [], partial_months: [], excluded_months: ["2026-09-01"], sample_count: 0,
      metrics: {
        gross_income: { mean: null, p25: null, median: null, p75: null },
        net_consumption: { mean: null, p25: null, median: null, p75: null },
        operating_surplus_or_deficit: { mean: null, p25: null, median: null, p75: null },
      },
    };
    vi.stubGlobal("fetch", vi.fn(async () => response({ ...overview, period_statistics: { observed: emptyPopulation, complete: emptyPopulation } })));
    render(<OverviewFeature />);
    fireEvent.click(screen.getByText("סטטיסטיקה והשוואות"));
    expect(await screen.findByText("אין חודשים עם נתונים לחישוב")).toBeVisible();
  });

  it("keeps the reporting month independent of the graph range and hides missing-month zeros", async () => {
    const missing = { ...point, month: "2026-10-01", metrics: { ...metrics, month: "2026-10-01", accepted_transaction_count: 0, breakdowns: {} } };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      if (url.searchParams.get("end_month") === "2026-10") return response({ ...overview, selected_month: missing, series: [point, missing], headline: { income: "0", net_consumption: "0", operating_surplus_or_deficit: "0", savings_rate: null, net_observed_savings_transfers: "0" } });
      return response(overview);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<OverviewFeature />);
    await screen.findByRole("heading", { name: /סקירת חודש · 09\/2026/ });
    await screen.findAllByText("\u2067\u20661,000.00\u2069 ש״ח\u2069");
    fireEvent.click(screen.getByRole("button", { name: /תקופת הדוח/ }));
    await chooseMonth("חודש סיום", "אוקטובר 2026");
    fireEvent.click(screen.getByRole("button", { name: "עדכון גרף" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("end_month=2026-10"))).toBe(true));
    expect(screen.getByRole("button", { name: "חודש לסקירה" })).toHaveTextContent("ספטמבר 2026");
    expect(screen.getAllByText("\u2067\u20661,000.00\u2069 ש״ח\u2069").length).toBeGreaterThan(0);
    await chooseMonth("חודש לסקירה", "אוקטובר 2026");
    expect(await screen.findByText(/אין נתונים לחודש זה במטבע שנבחר/)).toBeVisible();
    expect(screen.queryByRole("heading", { name: "סה״כ הכנסות" })).not.toBeInTheDocument();
    expect(document.querySelectorAll(".dashboard-chart-dot")).toHaveLength(1);
    expect(document.querySelectorAll(".dashboard-chart rect")).toHaveLength(2);
  });

  it("labels the latest complete rolling windows while the reporting month is partial", async () => {
    const averages = { gross_income: "1000.00", net_consumption: "17.40", operating_surplus_or_deficit: "982.60" };
    const prior = { ...point, month: "2026-08-01", complete: true, metrics: { ...metrics, month: "2026-08-01", rolling_three_month_averages: averages, rolling_six_month_averages: averages } };
    vi.stubGlobal("fetch", vi.fn(async () => response({ ...overview, series: [prior, point] })));
    render(<OverviewFeature />);
    await screen.findAllByText("\u2067\u20661,000.00\u2069 ש״ח\u2069");
    fireEvent.click(screen.getByText("סטטיסטיקה והשוואות"));
    expect(await screen.findByText("יוני 2026 עד אוגוסט 2026")).toBeVisible();
    expect(screen.getByText("מרץ 2026 עד אוגוסט 2026")).toBeVisible();
    const table = screen.getByRole("heading", { name: "ממוצע ברצף חודשים מלאים" }).closest("section")!;
    expect(within(table).getAllByText("\u2067\u20661,000.00\u2069 ש״ח\u2069")).toHaveLength(2);
    fireEvent.click(within(table).getByText("איך נבחר הרצף, ומה חסר?"));
    expect(within(table).getByText(/מחברים את הסכומים בחלון ומחלקים במספר החודשים/)).toBeVisible();
    expect(within(table).getByText(/בשונה מסיכום תקופת הגרף/)).toBeVisible();
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
    expect(screen.getAllByText("\u2067\u206617.40\u2069 ש״ח\u2069")).not.toHaveLength(0);
    openExpenseDetails("השוואת קטגוריות");
    openExpenseDetails("דפוסי הוצאה חוזרים אפשריים");
    openExpenseDetails("שינויים חריגים בקטגוריות");
    expect(screen.getByText("לעומת חודש קודם: חודש ההשוואה מחוץ לטווח שנבחר.")).toBeVisible();
    expect(screen.getByText(/ההחלטות נשמרות למשפחה/)).toBeVisible();
    fireEvent.click(screen.getByText("כלל הזיהוי"));
    expect(screen.getByText("Synthetic baseline rule")).toBeVisible();
    expect(screen.getByText(/ההוצאות מקובצות לפי הקטגוריה שנקבעה בסיווג/)).toBeVisible();

    expect(screen.queryByLabelText("מדד או קטגוריה")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "הוצאות והחזרים" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "הצגת העסקאות בדפוס (1)" }));
    const patterns = screen.getByText("דפוסי הוצאה חוזרים אפשריים", { exact: true }).closest("details")!;
    expect(await within(patterns).findByText("Synthetic grocery")).toBeVisible();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/dashboard/contributors/query"))).toBe(true);
  });

  it("keeps secondary analysis collapsed while warnings and their direct quality link stay visible", async () => {
    const withUnknownBehavior = { ...expenses, behavior_totals: { unknown: "17.40" } };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => response(String(input).includes("/contributors/query") ? [contribution] : withUnknownBehavior)));
    render(<ExpensesFeature />);
    await screen.findByRole("heading", { name: "התפלגות לפי קטגוריה" });
    const outer = screen.getByText("תובנות ופירוט נוסף").closest("details")!;
    expect(outer).not.toHaveAttribute("open");
    expect(screen.getByText("הסיווג לקבועות ומשתנות טרם הושלם")).toBeVisible();
    expect(screen.getByText("נתונים זמניים לפי העסקאות שהתקבלו. הוצאות שטרם סווגו עשויות לשנות את הסיכום.")).toBeVisible();
    expect(screen.getByRole("button", { name: "הצגת העסקאות בדפוס (1)" })).not.toBeVisible();
    expect(screen.getByRole("region", { name: "מגמות לאורך זמן" })).toBeVisible();
    fireEvent.click(screen.getByRole("link", { name: "פרטי כיסוי ואיכות" }));
    expect(outer).toHaveAttribute("open");
    expect(screen.getByText("כיסוי ואיכות הנתונים").closest("details")).toHaveAttribute("open");
    expect(screen.getByText("התאמות פתוחות: 1")).toBeVisible();
    expect(screen.getByText("דפוסי הוצאה חוזרים אפשריים").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("השוואת קטגוריות").closest("details")).not.toHaveAttribute("open");
    fireEvent.click(outer.querySelector("summary")!);
    expect(outer).not.toHaveAttribute("open");
    expect(screen.getByRole("link", { name: "פרטי כיסוי ואיכות" })).toBeVisible();
  });

  it("reconciles gross spending, refunds, and negative net spending using the selected month's service values", async () => {
    const refundedPoint = { ...point, metrics: { ...metrics, refunds: "25.00", net_consumption: "-7.60", unknown_behavior_consumption: "17.40" } };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => response(String(input).includes("/contributors/query") ? [] : { ...expenses, selected_month: refundedPoint, series: [refundedPoint], behavior_totals: { fixed: "0", variable: "0", unknown: "17.40" } })));
    render(<ExpensesFeature />);
    const summary = await screen.findByRole("region", { name: "סיכום הוצאות חודשי" });
    for (const [label, value] of [["הוצאות לפני החזרים", "17.40"], ["החזרים", "25.00"], ["הוצאות נטו", "-7.60"]]) {
      const card = within(summary).getByRole("heading", { name: label }).closest("article")!;
      expect(within(card).getByText(`\u2067\u2066${value}\u2069 ש״ח\u2069`)).toBeVisible();
    }
    expect(screen.getByText("הסיווג לקבועות ומשתנות טרם הושלם")).toBeVisible();
    expect(screen.getByRole("link", { name: "לסיווג ההוצאות" })).toHaveAttribute("href", "/classification?month=2026-09&currency=ILS&economic_class=consumption&include_resolved=true");
  });

  it("filters the shared table from a category and groups identical unavailable comparisons", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/dashboard/contributors/query")) {
        const ids: number[] = JSON.parse(String(init?.body)).transaction_ids;
        return response(ids.includes(12) ? [contribution] : []);
      }
      return response({ ...expenses, categories: [...expenses.categories, { category: "rent", amount: "10", contributor_transaction_ids: [13] }], category_comparisons: [...expenses.category_comparisons, ...expenses.category_comparisons.map((item) => ({ ...item, metric: item.metric.replace("food:", "rent:") }))] });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ExpensesFeature />);
    fireEvent.click(await screen.findByRole("button", { name: "עסקאות בקטגוריה food (1)" }));
    expect(await screen.findByText("Synthetic grocery")).toBeVisible();
    const request = fetchMock.mock.calls.find(([url]) => String(url).includes("/dashboard/contributors/query"));
    expect(JSON.parse((request?.[1] as RequestInit).body as string)).toEqual({ transaction_ids: [12] });
    expect(screen.getAllByText("לעומת חודש קודם: חודש ההשוואה מחוץ לטווח שנבחר.")).toHaveLength(1);
    expect(screen.queryByRole("columnheader", { name: "לעומת חודש קודם" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "עסקאות בקטגוריה food (1)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("heading", { name: "עסקאות החודש" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "עסקאות בקטגוריה rent (1)" }));
    expect(screen.queryByText("Synthetic grocery")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "ניקוי סינון קטגוריה" }));
    expect(screen.getByText("Synthetic grocery")).toBeVisible();
    expect(screen.getAllByRole("table", { name: "עסקאות החודש לפי הסינון שנבחר" })).toHaveLength(1);
  });

  it("keeps available category comparisons visible alongside a compact unavailable-year explanation", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => response(String(input).includes("/contributors/query") ? [] : { ...expenses, category_comparisons: [{ metric: "food:mom", current: "17.40", previous: "10.00", delta: "7.40", available: true, reason: null }, expenses.category_comparisons[1]] })));
    render(<ExpensesFeature />);
    await screen.findByRole("heading", { name: "התפלגות לפי קטגוריה" });
    openExpenseDetails("השוואת קטגוריות");
    expect(screen.getByRole("columnheader", { name: "לעומת חודש קודם" })).toBeVisible();
    expect(screen.getByText(/לעומת חודש קודם · הפרש:/)).toHaveTextContent("7.40");
    expect(screen.queryByRole("columnheader", { name: "לעומת שנה קודמת" })).not.toBeInTheDocument();
  });

  it("explains unavailable comparisons with scoped actions and clarifies expense behavior", async () => {
    const selected = { ...point, metrics: { ...metrics, completeness: { ...completeness, unclassified_transaction_count: 2 } } };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => response(String(input).includes("/contributors/query") ? [] : { ...expenses, selected_month: selected })));
    render(<ExpensesFeature />);
    await screen.findByRole("heading", { name: "התפלגות לפי קטגוריה" });
    openExpenseDetails("השוואת קטגוריות");
    expect(screen.getByText("אין עדיין השוואה זמינה")).toBeVisible();
    expect(screen.getByText("כיסוי המקורות לחודש מלא עדיין לא אושר.")).toBeVisible();
    expect(screen.getByText("2 עסקאות עדיין ללא סיווג.")).toBeVisible();
    expect(screen.getByRole("link", { name: "לסיווג העסקאות החסרות" })).toHaveAttribute("href", "/classification?month=2026-09&currency=ILS&economic_class=unclassified");
    expect(screen.getByRole("link", { name: "לבדיקת איכות הנתונים והמקורות" })).toHaveAttribute("href", "/data-quality");
    fireEvent.click(screen.getByRole("link", { name: "לפרטי הכיסוי של החודש" }));
    expect(screen.getByText("כיסוי ואיכות הנתונים").closest("details")).toHaveAttribute("open");
    openExpenseDetails("סיווג לקבועות ומשתנות");
    expect(screen.getByText(/כמו שכר דירה או מנוי/)).toBeVisible();
    expect(screen.getByText(/כמו קניות בסופר או מסעדות/)).toBeVisible();
    expect(screen.getByText(/גם הוצאה משתנה יכולה לחזור בכל חודש/)).toBeVisible();
    expect(screen.getByRole("link", { name: "לעדכון סיווג קבועות ומשתנות" })).toHaveAttribute("href", "/classification?month=2026-09&currency=ILS&economic_class=consumption&include_resolved=true");
  });

  it("retains a saved recurring decision when only the report month changes", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/insights/recurring-patterns/")) return response({ pattern: expenses.potential_recurring_spending[0], status: "approved", updated_at: "2026-10-17T01:00:00Z" });
      return response(String(input).includes("/contributors/query") ? [] : { ...expenses, recurring_pattern_reviews: [] });
    }));
    render(<ExpensesFeature />);
    await screen.findByRole("heading", { name: "התפלגות לפי קטגוריה" });
    openExpenseDetails("דפוסי הוצאה חוזרים אפשריים");
    fireEvent.click(screen.getByRole("button", { name: "אישור כהוצאה חוזרת" }));
    await screen.findByText("ההוצאה אושרה ונוספה להוצאות המאושרות.");
    fireEvent.click(screen.getByRole("button", { name: "חודש להצגה: החודש הקודם" }));
    await screen.findByRole("heading", { name: "ההוצאות של אוגוסט 2026" });
    openExpenseDetails("דפוסי הוצאה חוזרים אפשריים");
    fireEvent.click(screen.getByRole("button", { name: "הוצאות מאושרות (1)" }));
    expect(screen.getByRole("heading", { name: "הוצאה חוזרת: monthly market" })).toBeVisible();
    expect(screen.getByRole("button", { name: "לבדיקה (0)" })).toBeVisible();
  });

  it("does not present a missing month as zero spending", async () => {
    const emptyPoint = { ...point, metrics: { ...metrics, accepted_transaction_count: 0, breakdowns: {}, gross_consumption: "0", refunds: "0", net_consumption: "0" } };
    vi.stubGlobal("fetch", vi.fn(async () => response({ ...expenses, selected_month: emptyPoint, series: [emptyPoint], categories: [], behavior_totals: {}, category_comparisons: [] })));
    render(<ExpensesFeature />);
    const summary = await screen.findByRole("region", { name: "סיכום הוצאות חודשי" });
    expect(within(summary).getAllByText("לא זמין")).toHaveLength(3);
    expect(within(summary).getByText("אין נתוני עסקאות לחודש שנבחר. הסכומים אינם זמינים.")).toBeVisible();
    expect(screen.queryByText("סיווג לקבועות ומשתנות")).not.toBeInTheDocument();
  });

  it("keeps the report month, categories, and transactions independent of the trend range", async () => {
    resetDashboardFilters();
    const august = { ...point, month: "2026-08-01", metrics: { ...metrics, month: "2026-08-01", gross_consumption: "90", refunds: "10", net_consumption: "80", spending_by_category: { food: "60", august: "30" } } };
    const july = { ...august, month: "2026-07-01", metrics: { ...august.metrics, month: "2026-07-01" } };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/contributors/query")) return response([contribution]);
      const url = new URL(String(input), "https://testserver");
      const start = url.searchParams.get("start_month") ?? "2026-07";
      const end = url.searchParams.get("end_month") ?? "2026-09";
      const selected = end === "2026-08" ? august : point;
      const categories = end === "2026-08" ? [{ category: "food", amount: "60", contributor_transaction_ids: [23] }, { category: "august", amount: "30", contributor_transaction_ids: [22] }] : expenses.categories;
      return response({ ...expenses, filters: { start_month: `${start}-01`, end_month: `${end}-01`, currency: "ILS" }, selected_month: selected, series: start === end ? [selected] : end === "2026-08" ? [july, august] : [july, august, point], categories });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ExpensesFeature />);
    await screen.findByRole("heading", { name: "ההוצאות של ספטמבר 2026" });
    const summary = screen.getByRole("region", { name: "סיכום הוצאות חודשי" });
    const reportForm = screen.getByRole("region", { name: "בחירת חודש להוצאות" });
    const trend = screen.getByRole("region", { name: "מגמות לאורך זמן" });
    const monthlyCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).includes("start_month=2026-09&end_month=2026-09")).length;
    const initialMonthlyCalls = monthlyCalls();
    fireEvent.click(within(trend).getByRole("button", { name: /טווח המגמה/ }));
    await chooseMonth("חודש סיום", "אוגוסט 2026");
    fireEvent.click(within(trend).getByRole("button", { name: "עדכון מגמה" }));
    await waitFor(() => expect(within(trend).getByRole("img")).not.toHaveTextContent("09/2026"));
    expect(within(summary).getAllByText("\u2067\u206617.40\u2069 ש״ח\u2069")).toHaveLength(2);
    expect(within(reportForm).getByRole("button", { name: "חודש להצגה" })).toHaveTextContent("ספטמבר 2026");
    expect(screen.getByRole("button", { name: "עסקאות בקטגוריה food (1)" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "עסקאות בקטגוריה august (1)" })).not.toBeInTheDocument();
    expect(monthlyCalls()).toBe(initialMonthlyCalls);
    expect(screen.getByRole("region", { name: "התפלגות לפי קטגוריה" })).toHaveTextContent("ספטמבר 2026 בלבד");
    expect(screen.queryByRole("combobox", { name: "חודש" })).not.toBeInTheDocument();

    await chooseMonth("חודש להצגה", "אוגוסט 2026");
    await screen.findByRole("heading", { name: "ההוצאות של אוגוסט 2026" });
    expect(within(screen.getByRole("region", { name: "סיכום הוצאות חודשי" })).getByText("\u2067\u206680\u2069 ש״ח\u2069")).toBeVisible();
    expect(screen.getByRole("button", { name: "עסקאות בקטגוריה august (1)" })).toBeVisible();
    expect(within(screen.getByRole("region", { name: "מגמות לאורך זמן" })).getByRole("button", { name: "חודש התחלה" })).toHaveTextContent("יולי 2026");
    expect(screen.getByRole("region", { name: "התפלגות לפי קטגוריה" })).toHaveTextContent("אוגוסט 2026 בלבד");
  });

  it("shows an absent report month as unavailable while retaining the historical range", async () => {
    resetDashboardFilters();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/contributors/query")) return response([contribution]);
      if (String(input).includes("start_month=2026-10&end_month=2026-10")) return response({ ...expenses, filters: { ...filters, start_month: "2026-10-01", end_month: "2026-10-01" }, selected_month: null, series: [], categories: [], behavior_totals: {}, category_comparisons: [] });
      return response(expenses);
    }));
    render(<ExpensesFeature />);
    await screen.findByRole("heading", { name: "ההוצאות של ספטמבר 2026" });
    await chooseMonth("חודש להצגה", "אוקטובר 2026");
    await screen.findByRole("heading", { name: "ההוצאות של אוקטובר 2026" });
    expect(within(screen.getByRole("region", { name: "סיכום הוצאות חודשי" })).getAllByText("לא זמין")).toHaveLength(3);
    expect(within(screen.getByRole("region", { name: "מגמות לאורך זמן" })).getByRole("button", { name: "חודש סיום" })).toHaveTextContent("ספטמבר 2026");
    expect(screen.getByRole("region", { name: "תובנות מטווח המגמה" })).not.toBeVisible();
    openExpenseDetails();
    expect(screen.getByRole("region", { name: "תובנות מטווח המגמה" })).toBeVisible();
  });
});

it("leaves space before the final chart-month label at intermediate widths", () => {
  const points = Array.from({ length: 12 }, (_, index) => ({ ...point, month: `${2026}-${String(index + 1).padStart(2, "0")}-01` }));
  const { container } = render(<SeriesChart points={points} lines={[{ key: "gross_income", label: "הכנסה", value: (point) => point.metrics.gross_income }]} title="בדיקת חודשים" />);
  const labels = [...container.querySelectorAll("svg text")].filter((element) => /^(?:0[1-9]|1[0-2])\/2026$/.test(element.textContent ?? ""));
  expect(labels.at(-1)).toHaveTextContent("12/2026");
  expect(labels.some((element) => element.textContent === "11/2026")).toBe(false);
  for (let index = 1; index < labels.length; index += 1) {
    expect(Number(labels[index].getAttribute("x")) - Number(labels[index - 1].getAttribute("x"))).toBeGreaterThan(70);
  }
});
