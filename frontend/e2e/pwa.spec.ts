import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const session = { data: { user: { id: "fixture-user", display_name: "משתמשת בדיקה" }, csrf_token: "fixture-csrf" }, meta: { request_id: "fixture-request" } };

async function mockSession(page: Page) {
  await page.route("**/api/v1/auth/session", async (route) => {
    if (route.request().method() === "GET") await route.fulfill({ status: 200, contentType: "application/json", headers: { "Cache-Control": "no-store" }, body: JSON.stringify(session) });
    else await route.fulfill({ status: 204, headers: { "Cache-Control": "no-store" } });
  });
}

test("sign-in is Hebrew RTL and reaches the authenticated shell", async ({ page }) => {
  await page.route("**/api/v1/auth/session", async (route) => {
    if (route.request().method() === "GET") await route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: { code: "UNAUTHENTICATED", message: "Sign in required" } }) });
    else await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(session) });
  });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("lang", "he");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { name: "התחברות ל‑FamilyFin" })).toBeVisible();
  await page.getByLabel("שם משתמש").fill("test-user");
  await page.getByLabel("סיסמה").fill("example-password");
  await page.getByRole("button", { name: "התחברות" }).click();
  await expect(page.getByRole("heading", { name: "סקירה כללית" })).toBeVisible();
  await expect(page.getByText("משתמשת בדיקה")).toBeVisible();
});

test("desktop navigation exposes the nine destinations in labeled groups", async ({ page }) => {
  await mockSession(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  const navigation = page.getByRole("navigation", { name: "ניווט ראשי" });
  await expect(navigation.getByRole("link")).toHaveCount(9);
  await expect(navigation.getByText("תמונה משפחתית")).toBeVisible();
  await expect(navigation.getByRole("link", { name: "תכנון", exact: true })).toBeVisible();
  await expect(navigation.getByText("בדיקה וניהול")).toBeVisible();
});

test("mobile navigation keeps four primary links and groups secondary pages under More", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  try {
    const page = await context.newPage();
    await mockSession(page);
    await page.goto("/");
    const navigation = page.getByRole("navigation", { name: "ניווט ראשי במכשיר נייד" });
    await expect(navigation.getByRole("link")).toHaveCount(4);
    const moreButton = navigation.getByRole("button", { name: "עוד" });
    const target = await moreButton.boundingBox();
    expect(target?.height).toBeGreaterThanOrEqual(48);
    expect(target?.width).toBeGreaterThanOrEqual(48);
    await moreButton.focus();
    await moreButton.press("Enter");
    await expect(moreButton).toHaveAttribute("aria-expanded", "true");
    const menu = page.locator("#mobile-more-panel");
    await expect(menu.getByRole("link")).toHaveCount(5);
    await expect(menu.getByRole("heading", { name: "בדיקה וסיווג" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(moreButton).toHaveAttribute("aria-expanded", "false");
    await expect(moreButton).toBeFocused();
    await page.touchscreen.tap(target!.x + target!.width / 2, target!.y + target!.height / 2);
    await expect(moreButton).toHaveAttribute("aria-expanded", "true");
    await menu.getByRole("link", { name: "איכות נתונים" }).click();
    await expect(page.getByRole("heading", { name: "איכות נתונים וייבוא" })).toBeVisible();
  } finally {
    await context.close();
  }
});

test("Data Quality previews, downloads its plan, and commits only after confirmation", async ({ page }) => {
  await mockSession(page);
  await page.route("**/api/v1/dashboard/quality", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: {
    accepted_rows: 2,
    freshness_date: "2026-09-19",
    covered_start: "2026-09-01",
    covered_end: "2026-09-19",
    currencies: { ILS: 2 },
    issue_counts: {},
    incomplete_months: ["2026-09-01"],
    open_reconciliation_cases: 0,
    unclassified_transaction_count: 0,
    unclassified_absolute_amount: "0",
    source_coverage: "unknown",
    latest_import: null,
  }, meta: { request_id: "quality-request" } }) }));
  await page.route("**/api/v1/imports/history**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: { items: [] }, meta: { request_id: "history-request", next_cursor: null, limit: 50 } }) }));
  await page.route("**/api/v1/reconciliation/cases**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: { items: [] }, meta: { request_id: "cases-request", next_cursor: null, limit: 50 } }) }));

  const fileHash = "a".repeat(64);
  const preview = {
    preview_token: "ephemeral-preview-token",
    inspection: {
      parser_version: "familybiz-v2", file_sha256: fileHash, filename: "synthetic.xlsx", compressed_bytes: 512,
      uncompressed_bytes: 2048, sheet_names: ["Sheet1"], section_count: 1, transaction_count: 1,
      report_start: "2026-09-01", report_end: "2026-09-30", min_booking_date: "2026-09-19",
      max_booking_date: "2026-09-19", currencies: { ILS: 1 }, account_kinds: { card: 1 }, issue_counts: {},
      freshness_as_of: "2026-09-25T12:00:00Z", preview_rows: [{ amount: "-17.4", currency: "ILS" }],
    },
    parser_version: "familybiz-v2", file_sha256: fileHash, baseline_batch_id: null,
    baseline_fingerprint: "baseline-fingerprint", matching_baseline_json: "{}", matcher_version: "familybiz-matcher-v3",
    decision_plan_version: "familybiz-decision-plan-v1", decision_plan_fingerprint: "plan-fingerprint",
    decision_plan_json: "{\"decisions\":[]}", candidate_count: 1, warning_count: 0, rejected_count: 0,
    issue_counts: {}, preview_rows: [{ amount: "-17.4", currency: "ILS" }],
    predicted_statistics: { total_records: 1, inserted: 1, unchanged: 0, updated: 0, rejected: 0, ambiguous: 0, unresolved: 0, duplicate_file: false, non_ils_records: 0 },
  };
  let previewCalls = 0;
  let commitCalls = 0;
  let commitHadIdempotencyKey = false;
  await page.route("**/api/v1/imports/familybiz/previews", async (route) => {
    previewCalls += 1;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: preview, meta: { request_id: "preview-request" } }) });
  });
  await page.route("**/api/v1/imports/familybiz/commits", async (route) => {
    commitCalls += 1;
    commitHadIdempotencyKey = Boolean(route.request().headers()["idempotency-key"]);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: {
      batch_id: "synthetic-batch", status: "committed", statistics: preview.predicted_statistics, issues: [],
    }, meta: { request_id: "commit-request" } }) });
  });

  await page.goto("/data-quality");
  await expect(page.getByRole("heading", { name: "העלאת קובץ FamilyBiz" })).toBeVisible();
  await expect(page.getByText("plan-fingerprint")).not.toBeVisible();
  await page.getByLabel("קובץ XLSX של FamilyBiz").setInputFiles({
    name: "synthetic.xlsx",
    mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.from("synthetic workbook bytes"),
  });
  await page.getByRole("button", { name: "בדיקה ותצוגה מקדימה" }).click();
  await expect(page.getByText("plan-fingerprint")).toBeVisible();
  expect(previewCalls).toBe(1);
  expect(commitCalls).toBe(0);

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "הורדת תכנית החלטות מלאה" }).click();
  expect((await downloadPromise).suggestedFilename()).toBe(`${fileHash}-import-plan.json`);

  await page.getByRole("button", { name: "אישור וייבוא" }).click();
  await expect(page.getByText(/מזהה אצווה: synthetic-batch/)).toBeVisible();
  expect(commitCalls).toBe(1);
  expect(commitHadIdempotencyKey).toBe(false);
});

test("theme can switch while keeping preference separate from finance state", async ({ page }) => {
  await mockSession(page);
  await page.goto("/");
  const themeButton = page.getByRole("button", { name: /החלפה לערכת/ });
  await expect(themeButton).toBeEnabled();
  await themeButton.click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual(["familyfin-theme"]);
  await page.getByRole("button", { name: "החלפה לערכת יום" }).click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
});

test("the in-app offline banner appears on disconnect and clears after reconnect", async ({ page, context }) => {
  await mockSession(page);
  await page.goto("/");
  await expect(page.getByText("מחובר", { exact: true })).toBeVisible();
  await expect(page.getByText("משתמשת בדיקה")).toBeVisible();

  await context.setOffline(true);
  const banner = page.locator(".offline-banner");
  await expect(banner).toContainText("החיבור נותק");
  await expect(page.getByText("מנותק", { exact: true })).toBeVisible();
  await expect.poll(() => banner.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe("rgb(252, 245, 231)");

  await context.setOffline(false);
  await expect(page.getByText("מחובר", { exact: true })).toBeVisible();
  await expect(banner).toBeHidden();
});

test("the offline shell and service worker cache only static assets", async ({ page, context }) => {
  await mockSession(page);
  await page.goto("/");
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload();
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);
  const manifest = await page.evaluate(async () => {
    const link = document.querySelector<HTMLLinkElement>('link[rel="manifest"]');
    return link ? fetch(link.href).then((response) => response.json()) : null;
  });
  expect(manifest).toMatchObject({ name: "FamilyFin", lang: "he", dir: "rtl", display: "standalone" });
  for (const icon of manifest.icons) {
    const response = await page.request.get(icon.src);
    expect(response.ok()).toBe(true);
    expect(response.headers()["content-type"]).toContain("image/svg+xml");
  }
  await page.evaluate(() => fetch("/api/v1/auth/session", { credentials: "same-origin", cache: "no-store" }));
  const cachedPaths = await page.evaluate(async () => {
    const names = await caches.keys();
    const keys = await Promise.all(names.map(async (name) => (await caches.open(name)).keys()));
    return keys.flat().map((request) => new URL(request.url).pathname);
  });
  expect(cachedPaths.some((path) => path.startsWith("/api/"))).toBe(false);
  expect(cachedPaths.some((path) => path === "/" || path === "/expenses")).toBe(false);
  expect(cachedPaths.every((path) => path.startsWith("/_next/static/") || path.startsWith("/icons/") || path === "/offline.html" || path === "/manifest.webmanifest")).toBe(true);
  await context.setOffline(true);
  await page.goto("/expenses");
  await expect(page.getByRole("heading", { name: "אין חיבור לאינטרנט" })).toBeVisible();
});

test("core workspace has no serious accessibility violations", async ({ page }) => {
  await mockSession(page);
  await page.goto("/");
  const axe = () => new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect((await axe()).violations.map((violation) => violation.id)).toEqual([]);
  await page.getByRole("button", { name: /החלפה לערכת/ }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  const darkResults = await axe();
  expect(darkResults.violations.map((violation) => violation.id)).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("navigation", { name: "ניווט ראשי במכשיר נייד" }).getByRole("button", { name: "עוד" }).click();
  expect((await axe()).violations.map((violation) => violation.id)).toEqual([]);
});

test("sign-in form has no serious accessibility violations", async ({ page }) => {
  await page.route("**/api/v1/auth/session", (route) => route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: { code: "UNAUTHENTICATED", message: "Sign in required" } }) }));
  await page.goto("/");
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(results.violations.map((violation) => `${violation.id}: ${violation.help}`)).toEqual([]);
});
