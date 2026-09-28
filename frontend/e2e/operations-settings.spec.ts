import { expect, test } from "@playwright/test";

const session = {
  data: { user: { id: "fixture-user", display_name: "משתמשת בדיקה" }, csrf_token: "fixture-csrf" },
  meta: { request_id: "fixture-request" },
};

test("mobile operations and settings workflows keep backup gate and session controls usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/v1/auth/session", async (route) => {
    if (route.request().method() === "GET") await route.fulfill({ status: 200, json: session });
    else await route.fulfill({ status: 204 });
  });
  await page.route("**/api/v1/automation/status", (route) => route.fulfill({ status: 200, json: { data: {
    inbox: { inbox_file_count: 1, review_file_count: 0 },
    operations: {
      audit: { passed: true, checks: [{ name: "sqlite_integrity", passed: true, issue_codes: [] }] },
      backup: { configured: false, status: "not_configured", last_verified_at: null },
      run_now_allowed: false, run_now_block_reason: "AUTOMATION_BACKUP_NOT_CONFIGURED",
      warnings: ["AUTOMATION_BACKUP_NOT_CONFIGURED"],
    },
    latest_run: null,
  } } }));
  await page.route("**/api/v1/automation/runs*", async (route) => {
    if (route.request().method() === "POST") await route.fulfill({ status: 200, json: { data: {
      id: "run-1", status: "dry_run", dry_run: true, audit_passed: true, backup_created: false,
      counts: { ready: 1 }, issue_codes: [], started_at: "2026-09-28T10:00:00Z", finished_at: "2026-09-28T10:00:01Z", items: [],
    } } });
    else await route.fulfill({ status: 200, json: { data: { items: [] } } });
  });
  await page.route("**/api/v1/insights/preferences", (route) => route.fulfill({ status: 200, json: { data: {
    planning_scenario_id: null, planning_revision_id: null, forecast_id: null, forecast_revision_id: null,
    forecast_role: null, apartment_study_id: null, apartment_revision_id: null,
    apartment_alternative_name: null, updated_at: null,
  } } }));
  await page.route("**/api/v1/insights/preferences/options", (route) => route.fulfill({ status: 200, json: { data: {
    planning_scenarios: [], forecasts: [], apartment_studies: [],
  } } }));
  await page.route("**/api/v1/insights/alerts*", (route) => route.fulfill({ status: 200, json: { data: { items: [] } } }));
  await page.route("**/api/v1/insights/monthly-summaries*", (route) => route.fulfill({ status: 200, json: { data: { items: [] } } }));

  const settingsData = {
    preferences: { default_currency: "ILS", default_months: 12, updated_at: null },
    freshness: {
      familybiz: { last_import_at: null, latest_transaction_date: null, age_days: null },
      planning: { last_import_at: null, age_days: null }, net_worth: { last_import_at: null, age_days: null },
    },
    operations: {
      audit: { passed: true, checks: [] }, backup: { configured: false, status: "not_configured", last_verified_at: null },
      run_now_allowed: false, run_now_block_reason: "AUTOMATION_BACKUP_NOT_CONFIGURED", warnings: [],
    },
    operational_warnings: ["AUTOMATION_BACKUP_NOT_CONFIGURED"],
    household: { member_count: 2, members: ["Sam", "Lee"], permissions: "equal" },
  };
  await page.route("**/api/v1/settings", (route) => route.fulfill({ status: 200, json: { data: settingsData } }));
  await page.route("**/api/v1/settings/sessions", (route) => route.fulfill({ status: 200, json: { data: { items: [
    { id: "private-current-session", current: true, created_at: "2026-09-28T10:00:00Z", expires_at: "2026-09-28T18:00:00Z" },
    { id: "private-other-session", current: false, created_at: "2026-09-27T10:00:00Z", expires_at: "2026-09-28T18:00:00Z" },
  ] } } }));
  await page.route("**/api/v1/settings/preferences", async (route) => {
    if (route.request().method() === "PUT") await route.fulfill({ status: 200, json: { data: {
      default_currency: "USD", default_months: 24, updated_at: "2026-09-28T10:00:00Z",
    } } });
  });
  await page.route("**/api/v1/settings/sessions/**", (route) => route.fulfill({ status: 204 }));

  await page.goto("/automation-insights");
  await expect(page.getByRole("heading", { name: "מצב תהליכים" })).toBeVisible();
  await expect(page.getByRole("button", { name: "הפעלה עכשיו" })).toBeDisabled();
  await page.getByRole("button", { name: "בדיקת תיבה ללא שינויים" }).click();
  await expect(page.getByText(/לא נשמרו נתונים ולא הועברו קבצים/)).toBeVisible();
  expect(await page.locator("html").evaluate((element) => element.scrollWidth <= window.innerWidth)).toBe(true);

  await page.getByRole("button", { name: "עוד" }).click();
  await page.getByRole("link", { name: /הגדרות/ }).click();
  await expect(page.getByRole("heading", { name: "חשבונות וחיבורים" })).toBeVisible();
  await page.getByLabel("מטבע ברירת מחדל").selectOption("USD");
  await page.getByRole("button", { name: "שמירת העדפות" }).click();
  await expect(page.getByText("העדפות התצוגה נשמרו לחשבון שלך.")).toBeVisible();
  await expect(page.getByRole("button", { name: "ביטול חיבור" })).toBeVisible();
  expect(await page.locator("html").evaluate((element) => element.scrollWidth <= window.innerWidth)).toBe(true);
});
