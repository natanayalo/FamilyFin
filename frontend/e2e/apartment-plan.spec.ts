import { expect, test } from "@playwright/test";

const session = {
  data: { user: { id: "fixture-user", display_name: "משתמשת בדיקה" }, csrf_token: "fixture-csrf" },
  meta: { request_id: "apartment-fixture" },
};

const forecast = {
  forecast_id: "forecast-1", name: "תחזית משפחתית", scenario_id: "scenario-1",
  source_revision_id: "plan-revision-1", source_revision_number: 1, currency: "ILS", horizon_months: 36,
  current_revision_number: 1, archived: false, clone_of_forecast_id: null,
  created_at: "2026-09-28T09:00:00Z", updated_at: "2026-09-28T09:00:00Z",
};
const forecastRevision = {
  forecast_id: "forecast-1", revision_id: "forecast-revision-1", revision_number: 1,
  assumption_hash: "forecast-hash-1", created_at: "2026-09-28T09:00:00Z", scenario_id: "scenario-1",
  source_revision_id: "plan-revision-1", source_revision_number: 1, currency: "ILS", horizon_months: 36,
  policy_version: "savings-forecast-v1", provisional_acknowledged: false, net_worth_snapshot_revision_id: null,
  starting_pools: [{ name: "קופת מזומן", pool_type: "cash", opening_balance: "90000.50", as_of_date: "2026-10-01" }],
  cases: [], notes: "",
};
const planningSource = {
  at_creation: { scenario_id: "scenario-1", revision_id: "plan-revision-1", revision_number: 1, provisional: false, issue_codes: [] },
  current: { scenario_id: "scenario-1", revision_id: "plan-revision-1", revision_number: 1, provisional: false, issue_codes: [] },
};

type Alternative = {
  name: string;
  forecast_role: "baseline";
  purchase_month: number;
  property_price: string;
  family_gift: string;
  purchase_costs: Array<{ label: string; amount: string }>;
  equity_requirement: { mode: "percentage" | "amount"; value: string };
  mortgage: { principal: string; annual_nominal_rate: string; term_months: number };
  pool_draws: Array<{ pool_name: string; amount: string }>;
  stopped_housing_line_ids: string[];
  housing_costs: Array<{ label: string; amount: string }>;
  confirmed: boolean;
};

function makeDraft(alternatives: Alternative[]) {
  return {
    assumption_hash: "apartment-draft-hash", source_quality_warning: false,
    comparison: { currency: "ILS", alternatives: alternatives.map((item) => ({
      alternative_name: item.name, purchase_month: item.purchase_month, purchase_price: item.property_price,
      forecast_role: "baseline", mortgage_payment: "1909.66", total_interest: "287476.80", closing_gap: "10000",
      remaining_liquidity: "12000", maximum_housing_ratio: "0.31", worst_monthly_cash_flow: "1500", month_36_balance: "25000",
    })) },
    projections: alternatives.map((item) => ({
      alternative_name: item.name, forecast_role: "baseline", purchase_month: item.purchase_month,
      purchase_price: item.property_price, purchase_costs: "10000", total_uses: "510000", proposed_equity: "100000",
      required_equity: "100000", mortgage_principal: item.mortgage.principal, family_gift: item.family_gift,
      requested_pool_draws: "100000", fulfilled_pool_draws: "100000", total_sources: "500000", funding_gap: "10000",
      available_pool_balances: { "קופת מזומן": "120000" }, remaining_liquidity_by_pool: { "קופת מזומן": "12000" },
      remaining_liquidity: "12000", mortgage_schedule: [], total_interest: "287476.80", total_repayment: "687476.80",
      monthly: [], readiness: { equity_requirement_met: true, sources_cover_uses: false, mortgage_within_required_equity: true,
        minimum_liquidity_met: true, housing_ratio_guardrail_met: true, ready: false, failures: ["Purchase sources do not fully cover purchase uses"] },
      maximum_housing_ratio: "0.31", worst_monthly_cash_flow: "1500", month_36_balance: "25000",
    })),
  };
}

function studySummary(revisionNumber: number) {
  return {
    study_id: "study-1", name: "מחקר דירה", forecast_id: "forecast-1", forecast_revision_id: "forecast-revision-1",
    forecast_revision_number: 1, forecast_assumption_hash: "forecast-hash-1", currency: "ILS",
    current_revision_number: revisionNumber, archived: false, clone_of_study_id: null,
    created_at: "2026-09-28T09:00:00Z", updated_at: "2026-09-28T09:00:00Z",
  };
}

test("apartment workflow stays usable at 360px RTL and saves a new immutable revision on desktop", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  let study: ReturnType<typeof studySummary> | null = null;
  let currentSnapshot: Record<string, unknown> | null = null;
  let currentRevisionNumber = 0;
  let savedAlternatives: Alternative[] = [];
  const envelope = (data: unknown) => ({ data, meta: { request_id: "apartment-fixture" } });

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    if (path === "/api/v1/auth/session" && method === "GET") return route.fulfill({ status: 200, json: session });
    if (path === "/api/v1/forecasts" && method === "GET") return route.fulfill({ status: 200, json: envelope([forecast]) });
    if (path === "/api/v1/forecasts/forecast-1/revisions" && method === "GET") return route.fulfill({ status: 200, json: envelope([{
      revision_id: "forecast-revision-1", forecast_id: "forecast-1", revision_number: 1, source_revision_id: "plan-revision-1",
      source_revision_number: 1, policy_version: "savings-forecast-v1", assumption_hash: "forecast-hash-1", created_at: null, notes: "",
    }]) });
    if (path === "/api/v1/apartment/studies" && method === "GET") return route.fulfill({ status: 200, json: envelope(study ? [study] : []) });
    if (path === "/api/v1/apartment/options" && method === "GET") return route.fulfill({ status: 200, json: envelope({
      forecast, forecast_revision: forecastRevision, planning_source: planningSource, expense_lines: [],
    }) });
    if (path === "/api/v1/apartment/pool-balances" && method === "GET") return route.fulfill({ status: 200, json: envelope({ "קופת מזומן": "120000" }) });
    if (path === "/api/v1/apartment/previews" && method === "POST") {
      const body = request.postDataJSON() as { alternatives: Alternative[] };
      return route.fulfill({ status: 200, json: envelope(makeDraft(body.alternatives)) });
    }
    if (path === "/api/v1/apartment/studies" && method === "POST") {
      const body = request.postDataJSON() as Record<string, unknown> & { alternatives: Alternative[] };
      savedAlternatives = body.alternatives;
      currentRevisionNumber = 1;
      currentSnapshot = {
        ...body, study_id: "study-1", revision_id: "study-revision-1", revision_number: 1,
        assumption_hash: "apartment-hash-1", currency: "ILS", policy_version: "apartment-planning-v1",
        forecast_revision_id: "forecast-revision-1", forecast_assumption_hash: "forecast-hash-1", created_at: null,
      };
      study = studySummary(1);
      return route.fulfill({ status: 201, json: envelope(study) });
    }
    if (path === "/api/v1/apartment/studies/study-1/revisions" && method === "GET") {
      return route.fulfill({ status: 200, json: envelope(Array.from({ length: currentRevisionNumber }, (_item, index) => ({
        revision_id: `study-revision-${index + 1}`, study_id: "study-1", revision_number: index + 1,
        forecast_id: "forecast-1", forecast_revision_id: "forecast-revision-1", forecast_revision_number: 1,
        forecast_assumption_hash: "forecast-hash-1", policy_version: "apartment-planning-v1",
        assumption_hash: `apartment-hash-${index + 1}`, created_at: null, notes: "",
      }))) });
    }
    const projection = path.match(/^\/api\/v1\/apartment\/studies\/study-1\/revisions\/(\d+)\/projection$/);
    if (projection && method === "GET" && currentSnapshot) return route.fulfill({ status: 200, json: envelope({
      snapshot: currentSnapshot, draft: makeDraft(savedAlternatives), source_verification: planningSource,
    }) });
    if (path === "/api/v1/apartment/studies/study-1/revisions" && method === "POST") {
      const body = request.postDataJSON() as Record<string, unknown> & { alternatives: Alternative[] };
      savedAlternatives = body.alternatives;
      currentRevisionNumber += 1;
      currentSnapshot = { ...currentSnapshot, ...body, revision_id: `study-revision-${currentRevisionNumber}`, revision_number: currentRevisionNumber, assumption_hash: `apartment-hash-${currentRevisionNumber}` };
      study = studySummary(currentRevisionNumber);
      return route.fulfill({ status: 201, json: envelope(currentSnapshot) });
    }
    return route.fulfill({ status: 404, json: envelope({}) });
  });

  await page.goto("/apartment-plan");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { name: "מחקר רכישת דירה חדש" })).toBeVisible();
  await page.getByLabel("מחיר הנכס").first().fill("500000");
  await page.getByRole("button", { name: "חישוב / רענון טיוטה" }).click();
  await expect(page.getByText("מקורות, שימושים ומוכנות").first()).toBeVisible();
  const mobileWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(mobileWidth).toBeLessThanOrEqual(360);
  const mobileConfirmations = page.getByRole("checkbox", { name: /עיינתי בחלופה הזו/ });
  await expect(mobileConfirmations).toHaveCount(2);
  await mobileConfirmations.nth(0).check();
  await mobileConfirmations.nth(1).check();
  await expect(page.getByRole("button", { name: "יצירת מחקר" })).toBeEnabled();
  await page.getByRole("button", { name: "יצירת מחקר" }).click();
  await expect(page.getByRole("heading", { name: "מחקר דירה" })).toBeVisible();
  await expect(page.getByText("גרסה 1 · forecast-h")).toBeVisible();

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByLabel("מחיר הנכס").first().fill("510000");
  const desktopConfirmations = page.getByRole("checkbox", { name: /עיינתי בחלופה הזו/ });
  await desktopConfirmations.nth(0).check();
  await desktopConfirmations.nth(1).check();
  await expect(page.getByRole("button", { name: "שמירת גרסה חדשה" })).toBeEnabled();
  await page.getByRole("button", { name: "שמירת גרסה חדשה" }).click();
  await expect(page.getByLabel("גרסת מחקר לעיון")).toHaveValue("2");
  expect(currentRevisionNumber).toBe(2);
  expect(savedAlternatives[0].property_price).toBe("510000");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1440);
});
