import { expect, test } from "@playwright/test";

const session = {
  data: { user: { id: "fixture-user", display_name: "משתמשת בדיקה" }, csrf_token: "fixture-csrf" },
  meta: { request_id: "fixture-request" },
};

test("authenticated Net Worth route shows observed account history and exact service totals", async ({ page }) => {
  await page.route("**/api/v1/auth/session", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(session) });
    } else {
      await route.fulfill({ status: 204 });
    }
  });

  const balance = {
    account_key: "cash", amount_ils: "1200.50", valuation_date: "2026-08-31", notes: "",
    account_name: "מזומן", side: "asset", category: "cash", liquidity: "liquid", owner_label: null,
    stale_after_days: 45, snapshot_date: "2026-08-31", stale: false,
  };
  const revision = {
    snapshot_id: "snapshot-1", revision_id: "revision-1", revision_number: 1,
    snapshot_date: "2026-08-31", origin: "manual", notes: "", quality_issues: [],
    quality_acknowledged: false, content_hash: "sha256-fixture", active_account_keys: ["cash"],
    source_file_id: null, balances: [balance], created_at: "2026-09-01T00:00:00Z",
    stale_account_keys: [], complete: true,
  };

  await page.route("**/api/v1/net-worth/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/net-worth/forecast-comparisons") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      expect(body).toMatchObject({ forecast_id: "forecast-1", forecast_revision_number: 1, role: "baseline", observed_snapshot_revision_id: "revision-1" });
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: {
        forecast_id: "forecast-1", forecast_revision_id: "forecast-revision-1", forecast_revision_number: 1,
        role: "baseline", observed_snapshot_revision_id: "revision-1", observed_snapshot_date: "2026-08-31",
        projected_month: "2026-08-01", account_deltas: { cash: "300.25" },
        projected_by_account: { cash: "900.25" }, observed_by_account: { cash: "1200.50" },
        projected_total: "900.25", observed_total: "1200.50", aggregate_delta: "300.25",
        timing_warning: null, valuation_date_warning: null,
      }, meta: { request_id: "fixture-request" } }) });
      return;
    }
    const responses: Record<string, unknown> = {
      "/api/v1/net-worth/accounts": [{
        id: "account-1", account_key: "cash", display_name: "מזומן", side: "asset", category: "cash",
        liquidity: "liquid", owner_label: null, active_from: "2020-01-01", active_to: null,
        stale_after_days: 45, created_at: null, updated_at: null,
      }],
      "/api/v1/net-worth/snapshots": [{
        snapshot_id: "snapshot-1", snapshot_date: "2026-08-31", current_revision_number: 1,
        archived: false, created_at: null, updated_at: null,
      }],
      "/api/v1/net-worth/snapshots/snapshot-1/revisions": [revision],
      "/api/v1/net-worth/trend": [{
        snapshot_date: "2026-08-31", revision_id: "revision-1", total_assets: "1200.50",
        total_liabilities: "300.25", net_worth: "900.25", liquid_assets: "1200.50",
        restricted_assets: "0", illiquid_assets: "0",
      }],
    };
    if (path === "/api/v1/net-worth/summary") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        data: {
          revision_id: "revision-1", snapshot_id: "snapshot-1", snapshot_date: "2026-08-31", revision_number: 1,
          total_assets: "1200.50", total_liabilities: "300.25", net_worth: "900.25", liquid_assets: "1200.50",
          restricted_assets: "0", illiquid_assets: "0", stale_account_keys: [], snapshot_freshness_days: 25,
          by_category: { cash: "1200.50" }, by_liquidity: { liquid: "1200.50" }, by_owner: { Shared: "1200.50" },
          by_account: { cash: "1200.50" },
        }, meta: { request_id: "fixture-request" },
      }) });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "Cache-Control": "private, no-store" },
      body: JSON.stringify({ data: responses[path] ?? [], meta: { request_id: "fixture-request" } }),
    });
  });
  await page.route("**/api/v1/forecasts**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const data = path === "/api/v1/forecasts"
      ? [{ forecast_id: "forecast-1", name: "תחזית משפחתית", scenario_id: "scenario-1", source_revision_id: "plan-revision-1", source_revision_number: 1, currency: "ILS", horizon_months: 36, current_revision_number: 2, archived: false, clone_of_forecast_id: null, created_at: null, updated_at: null }]
      : [{ revision_id: "forecast-revision-1", forecast_id: "forecast-1", revision_number: 1, source_revision_id: "plan-revision-1", source_revision_number: 1, policy_version: "savings-forecast-v1", assumption_hash: "hash-1", created_at: "2026-08-01T00:00:00Z", notes: "" }, { revision_id: "forecast-revision-2", forecast_id: "forecast-1", revision_number: 2, source_revision_id: "plan-revision-1", source_revision_number: 1, policy_version: "savings-forecast-v1", assumption_hash: "hash-2", created_at: "2026-08-31T00:00:00Z", notes: "" }];
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data, meta: { request_id: "fixture-request" } }) });
  });

  await page.goto("/net-worth");
  await expect(page.getByRole("heading", { name: "תמונת מצב נבחרת" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "רשימת חשבונות" })).toBeVisible();
  await expect(page.getByText("מזומן", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/900\.25/).first()).toBeVisible();
  await page.getByLabel("גרסה להשוואה").selectOption("1");
  await page.getByRole("button", { name: "השוואה לתחזית" }).click();
  await expect(page.getByText(/300\.25/).first()).toBeVisible();
  await expect(page.getByText("מזומן", { exact: true }).last()).toBeVisible();
});
