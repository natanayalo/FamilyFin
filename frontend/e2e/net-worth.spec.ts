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

  await page.goto("/net-worth");
  await expect(page.getByRole("heading", { name: "תמונת מצב נבחרת" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "רשימת חשבונות" })).toBeVisible();
  await expect(page.getByText("מזומן", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/900\.25/).first()).toBeVisible();
  await expect(page.getByText("ממתין למודול התחזית")).toBeVisible();
});
