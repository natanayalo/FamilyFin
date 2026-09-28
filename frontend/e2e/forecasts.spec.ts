import { expect, test } from "@playwright/test";

const session = {
  data: { user: { id: "fixture-user", display_name: "משתמשת בדיקה" }, csrf_token: "fixture-csrf" },
  meta: { request_id: "forecast-fixture" },
};

const sourceItem = {
  id: "saving-item-1", kind: "savings_contribution", label: "הפקדה חודשית", category: null, amount: "250.00",
  frequency: "monthly", start_month: "2026-10-01", end_month: "2027-09-01", occurrence_month: null,
  origin: "manual", source_range: null, source_row: null, policy_version: "planning-v1",
  completeness_codes: [], contributor_transaction_ids: [], provenance: {}, notes: [],
};

const planningScenario = {
  scenario_id: "scenario-1", name: "תכנון משפחתי", currency: "ILS", start_month: "2026-10-01", end_month: "2027-09-01",
  current_revision_number: 1, archived: false, clone_of_scenario_id: null,
  created_at: "2026-09-28T09:00:00Z", updated_at: "2026-09-28T09:00:00Z",
};

const planningRevision = {
  revision_id: "planning-revision-1", scenario_id: "scenario-1", revision_number: 1,
  items: [sourceItem], notes: "", created_at: "2026-09-28T09:00:00Z", provisional: false,
  issue_codes: [], completeness_snapshot: [], expense_notes: [],
};

const roles = ["conservative", "baseline", "optimistic"] as const;

function cases() {
  return roles.map((role) => ({
    role, annual_return_rate: role === "conservative" ? "0" : role === "baseline" ? "0.08" : "0.16",
    routes: [{ source_item_id: sourceItem.id, pool_name: "מזומן משפחתי" }], sweep_enabled: true,
    sweep_pool_name: "מזומן משפחתי", adjustments: [], events: [], confirmed: true,
  }));
}

function forecastSummary(revisionNumber: number) {
  return {
    forecast_id: "forecast-1", name: "תכנון משפחתי · תחזית חיסכון", scenario_id: "scenario-1",
    source_revision_id: "planning-revision-1", source_revision_number: 1, currency: "ILS", horizon_months: 36,
    current_revision_number: revisionNumber, archived: false, clone_of_forecast_id: null,
    created_at: "2026-09-28T09:00:00Z", updated_at: "2026-09-28T09:00:00Z",
  };
}

function forecastSnapshot(revisionNumber: number, opening: string) {
  return {
    forecast_id: "forecast-1", revision_id: `forecast-revision-${revisionNumber}`, revision_number: revisionNumber,
    assumption_hash: `hash-${revisionNumber}`, created_at: `2026-09-${String(revisionNumber).padStart(2, "0")}T09:00:00Z`,
    scenario_id: "scenario-1", source_revision_id: "planning-revision-1", source_revision_number: 1,
    currency: "ILS", horizon_months: 36, policy_version: "savings-forecast-v1", provisional_acknowledged: false,
    net_worth_snapshot_revision_id: null,
    starting_pools: [{ name: "מזומן משפחתי", pool_type: "cash", opening_balance: opening, as_of_date: "2026-10-01" }],
    cases: cases(), notes: "",
  };
}

function projection(role: (typeof roles)[number], opening: string) {
  const months = Array.from({ length: 36 }, (_, index) => {
    const value = String(Number(opening) + (index + 1) * 250);
    return {
      month_number: index + 1, month: `2026-${String((index + 9) % 12 + 1).padStart(2, "0")}-01`,
      income: "10000", expenses: "4000", contributions: "250", requested_withdrawals: "0",
      fulfilled_withdrawals: "0", unmet_funding_gap: "0", swept_surplus: "0", estimated_returns: "0",
      cash_before_sweep: "6000", cash_after_sweep: "6000", ending_balance: value,
      requested_capital_draws: "0", fulfilled_capital_draws: "0",
      pools: [{ month_number: index + 1, month: `2026-${String((index + 9) % 12 + 1).padStart(2, "0")}-01`,
        pool_id: "pool-1", pool_name: "מזומן משפחתי", pool_type: "cash", opening_balance: opening,
        estimated_return: "0", contributions: "250", swept_surplus: "0", requested_withdrawal: "0",
        fulfilled_withdrawal: "0", unmet_funding_gap: "0", requested_capital_draw: "0",
        fulfilled_capital_draw: "0", closing_balance: value }],
    };
  });
  return {
    forecast_id: "forecast-1", scenario_id: "scenario-1", source_revision_id: "planning-revision-1",
    source_revision_number: 1, currency: "ILS", months, provisional: false, issue_codes: [],
    first_shortfall_month: null, assumption_hash: "hash", methodology: {
      policy_version: "savings-forecast-v1", source_plan_revision_id: "planning-revision-1",
      source_plan_revision_number: 1, calculation_order: ["החלת תשואה", "הפקדות"],
      projection_disclaimer: "תחזית לצורכי תכנון בלבד.",
    },
  };
}

function draft(opening: string) {
  return {
    projections: {
      conservative: projection("conservative", opening),
      baseline: projection("baseline", opening),
      optimistic: projection("optimistic", opening),
    },
    comparison: { currency: "ILS", checkpoints: Object.fromEntries(roles.map((role) => [role,
      [12, 24, 36].map((horizon) => ({ horizon_month: horizon, ending_balance: String(Number(opening) + horizon * 250), contributions: String(horizon * 250), swept_surplus: "0", withdrawals: "0", estimated_returns: "0", funding_gap: "0" })),
    ])) },
    assumption_hash: "hash", validation_errors: [],
    source_verification: {
      at_creation: { scenario_id: "scenario-1", revision_id: "planning-revision-1", revision_number: 1, provisional: false, issue_codes: [] },
      current: { scenario_id: "scenario-1", revision_id: "planning-revision-1", revision_number: 1, provisional: false, issue_codes: [] },
    },
  };
}

test("mobile RTL forecast flow creates, saves, and restores immutable revisions", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/v1/auth/session", async (route) => {
    if (route.request().method() === "GET") await route.fulfill({ status: 200, json: session });
    else await route.fulfill({ status: 204 });
  });
  await page.route("**/api/v1/planning/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const envelope = (data: unknown) => ({ data, meta: { request_id: "forecast-fixture" } });
    if (path.endsWith("/scenarios")) return route.fulfill({ status: 200, json: envelope([planningScenario]) });
    if (path.endsWith("/scenarios/scenario-1/revisions")) return route.fulfill({ status: 200, json: envelope([planningRevision]) });
    if (path.endsWith("/scenarios/scenario-1/revisions/1")) return route.fulfill({ status: 200, json: envelope(planningRevision) });
    return route.fulfill({ status: 200, json: envelope([]) });
  });
  await page.route("**/api/v1/net-worth/**", async (route) => {
    await route.fulfill({ status: 200, json: { data: [], meta: { request_id: "forecast-fixture" } } });
  });

  let currentRevision = 0;
  let secondOpening = "1250.00";
  const revisionSummaries = () => Array.from({ length: currentRevision }, (_, index) => ({
    revision_id: `forecast-revision-${index + 1}`, forecast_id: "forecast-1", revision_number: index + 1,
    source_revision_id: "planning-revision-1", source_revision_number: 1, policy_version: "savings-forecast-v1",
    assumption_hash: `hash-${index + 1}`, created_at: `2026-09-${String(index + 1).padStart(2, "0")}T09:00:00Z`, notes: "",
  }));
  const detail = (revisionNumber: number) => ({
    snapshot: forecastSnapshot(revisionNumber, revisionNumber === 1 ? "1000.00" : secondOpening),
    draft: draft(revisionNumber === 1 ? "1000.00" : secondOpening),
    source_verification: {
      at_creation: { scenario_id: "scenario-1", revision_id: "planning-revision-1", revision_number: 1, provisional: false, issue_codes: [] },
      current: { scenario_id: "scenario-1", revision_id: "planning-revision-1", revision_number: 1, provisional: false, issue_codes: [] },
    },
  });
  await page.route("**/api/v1/forecasts**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const envelope = (data: unknown) => ({ data, meta: { request_id: "forecast-fixture" } });
    if (path === "/api/v1/forecasts" && method === "GET") {
      return route.fulfill({ status: 200, json: envelope(currentRevision ? [forecastSummary(currentRevision)] : []) });
    }
    if (path === "/api/v1/forecasts" && method === "POST") {
      currentRevision = 1;
      return route.fulfill({ status: 201, json: envelope(forecastSummary(currentRevision)) });
    }
    if (path === "/api/v1/forecasts/previews" && method === "POST") {
      const payload = request.postDataJSON() as { starting_pools: Array<{ opening_balance: string }> };
      return route.fulfill({ status: 200, json: envelope(draft(payload.starting_pools[0].opening_balance)) });
    }
    if (path === "/api/v1/forecasts/forecast-1/revisions" && method === "GET") {
      return route.fulfill({ status: 200, json: envelope(revisionSummaries()) });
    }
    if (path === "/api/v1/forecasts/forecast-1/revisions" && method === "POST") {
      const payload = request.postDataJSON() as { starting_pools: Array<{ opening_balance: string }> };
      currentRevision = 2;
      secondOpening = payload.starting_pools[0].opening_balance;
      return route.fulfill({ status: 201, json: envelope(forecastSnapshot(2, secondOpening)) });
    }
    const projectionMatch = path.match(/\/api\/v1\/forecasts\/forecast-1\/revisions\/(\d+)\/projection$/);
    if (projectionMatch && method === "GET") {
      return route.fulfill({ status: 200, json: envelope(detail(Number(projectionMatch[1]))) });
    }
    const restoreMatch = path.match(/\/api\/v1\/forecasts\/forecast-1\/revisions\/(\d+)\/restore$/);
    if (restoreMatch && method === "POST") {
      currentRevision = 3;
      return route.fulfill({ status: 201, json: envelope(forecastSnapshot(3, "1000.00")) });
    }
    return route.fulfill({ status: 200, json: envelope(forecastSummary(currentRevision)) });
  });

  await page.goto("/savings-forecast");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { name: "תחזיות חיסכון" })).toBeVisible();
  await page.getByRole("button", { name: "תחזית חדשה" }).click();
  await page.getByRole("button", { name: "המשך ליתרות פתיחה" }).click();
  await page.getByLabel("יתרת פתיחה קופה 1", { exact: true }).fill("1000.00");
  await page.getByRole("button", { name: "המשך למקרי תחזית" }).click();
  await page.getByRole("button", { name: "חישוב תצוגה מקדימה" }).click();
  await expect(page.getByRole("heading", { name: "תצוגה מקדימה לאחר חישוב" })).toBeVisible();
  const confirmations = page.getByRole("checkbox", { name: /עברתי על ההנחות ואישרתי את המקרה/ });
  await expect(confirmations).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) await confirmations.nth(index).check();
  await page.getByRole("button", { name: "שמירת תחזית" }).click();
  await expect(page.getByRole("heading", { name: "תכנון משפחתי · תחזית חיסכון", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  await page.getByRole("button", { name: "עריכת הנחות" }).click();
  await page.getByRole("button", { name: "המשך ליתרות פתיחה" }).click();
  await page.getByLabel("יתרת פתיחה קופה 1", { exact: true }).fill("1250.00");
  await page.getByRole("button", { name: "המשך למקרי תחזית" }).click();
  await page.getByRole("button", { name: "חישוב תצוגה מקדימה" }).click();
  const editConfirmations = page.getByRole("checkbox", { name: /עברתי על ההנחות ואישרתי את המקרה/ });
  for (let index = 0; index < 3; index += 1) await editConfirmations.nth(index).check();
  await page.getByRole("button", { name: "שמירת גרסה חדשה" }).click();
  await expect(page.getByText("גרסת תחזית 2")).toBeVisible();

  const revisionPicker = page.getByLabel("גרסת תחזית לבדיקה");
  await revisionPicker.selectOption("1");
  await page.getByRole("button", { name: "שחזור כגרסה חדשה" }).click();
  await expect(revisionPicker).toHaveValue("3");
  await expect(page.getByText("גרסת תחזית 3")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
