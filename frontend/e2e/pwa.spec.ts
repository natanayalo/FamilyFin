import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const session = { data: { user: { id: "fixture-user", display_name: "משתמשת בדיקה" }, csrf_token: "fixture-csrf" }, meta: { request_id: "fixture-request" } };

async function mockSession(page: Page) {
  await page.route("**/api/v1/auth/session", async (route) => {
    if (route.request().method() === "GET") await route.fulfill({ status: 200, contentType: "application/json", headers: { "Cache-Control": "no-store" }, body: JSON.stringify(session) });
    else await route.fulfill({ status: 204, headers: { "Cache-Control": "no-store" } });
  });
  await page.route("**/api/v1/dashboard/overview**", async (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    headers: { "Cache-Control": "private, no-store" },
    body: JSON.stringify({
      data: {
        filters: { start_month: "2026-09-01", end_month: "2026-09-01", currency: "ILS" },
        selected_month: null,
        series: [],
        headline: {},
        comparisons: [],
        freshness_date: null,
        source_coverage: "unknown",
        currency: "ILS",
      },
      meta: { request_id: "fixture-empty-dashboard" },
    }),
  }));
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

test("overview and expenses routes show service metrics and contributor drill-downs", async ({ page }) => {
  await mockSession(page);
  await page.setViewportSize({ width: 390, height: 844 });
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
  const point = {
    month: "2026-09-01",
    currency: "ILS",
    complete: false,
    issue_codes: ["SOURCE_PERIOD_INCOMPLETE"],
    metrics: {
      month: "2026-09-01",
      currency: "ILS",
      completeness,
      source_period_completeness: {
        source_period_complete: false,
        classification_complete: true,
        complete: false,
        source_coverage: "unknown",
        issues: ["SOURCE_PERIOD_INCOMPLETE"],
      },
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
      rolling_three_month_averages: { gross_income: null, net_consumption: null, operating_surplus_or_deficit: null },
      rolling_six_month_averages: { gross_income: null, net_consumption: null, operating_surplus_or_deficit: null },
      breakdowns: {
        gross_income: { name: "gross_income", value: "1000.00", contributor_transaction_ids: [11], currency: "ILS" },
        net_consumption: { name: "net_consumption", value: "17.40", contributor_transaction_ids: [12], currency: "ILS" },
        "spending_by_category:food": { name: "spending_by_category:food", value: "17.40", contributor_transaction_ids: [12], currency: "ILS" },
      },
    },
  };
  const filters = { start_month: "2026-09-01", end_month: "2026-09-01", currency: "ILS" };
  const envelope = (data: unknown) => JSON.stringify({ data, meta: { request_id: "fixture-dashboard" } });
  await page.route("**/api/v1/dashboard/overview**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: envelope({
    filters, selected_month: point, series: [point],
    headline: { income: "1000.00", net_consumption: "17.40", operating_surplus_or_deficit: "982.60", savings_rate: null, net_observed_savings_transfers: "0" },
    comparisons: [], freshness_date: "2026-09-30", source_coverage: "unknown", currency: "ILS",
  }) }));
  await page.route("**/api/v1/dashboard/expenses**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: envelope({
    filters, selected_month: point, series: [point],
    categories: [{ category: "food", amount: "17.40", contributor_transaction_ids: [12] }],
    behavior_totals: { fixed: "0", variable: "17.40", unknown: "0" }, category_comparisons: [],
    potential_recurring_spending: [{ label: "Potential pattern", normalized_description: "monthly market", analysis_category: "food", currency: "ILS", account_kind: "card", median_amount: "17.40", minimum_amount: "17.40", maximum_amount: "17.40", amount_range: ["17.40", "17.40"], occurrence_months: ["2026-09-01"], contributor_transaction_ids: [12] }],
    unusual_category_spending: [], currency: "ILS",
  }) }));
  await page.route("**/api/v1/dashboard/contributors/query", async (route) => {
    expect(route.request().postDataJSON()).toEqual({ transaction_ids: [12] });
    await route.fulfill({ status: 200, contentType: "application/json", body: envelope([{
      transaction_id: 12, booking_date: "2026-09-02", description: "Synthetic grocery", amount: "-17.40", currency: "ILS",
      source_category: "food", movement_type: "purchase", account_label: "Synthetic account", account_kind: "card",
      effective_classification: "consumption", classification_source: "builtin_rule", analysis_category: "food", expense_behavior: "variable",
    }]) });
  });

  await page.goto("/dashboard");
  await expect(page.getByText("הנתונים זמניים; חלק מההשוואות אינן זמינות")).toBeVisible();
  await expect(page.getByText("1000.00 ש״ח").first()).toBeVisible();
  const chartData = page.locator(".dashboard-chart-data");
  await chartData.getByText("הצגת נתונים בטבלה").click();
  const chartTable = chartData.getByRole("table", { name: "נתוני תרשים: מגמת הכנסה, צריכה נטו ועודף תפעולי" });
  await expect(chartTable.getByText("1000.00", { exact: true })).toBeVisible();
  await expect(chartTable.getByText("17.40", { exact: true })).toBeVisible();
  const axe = () => new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect((await axe()).violations.map((violation) => violation.id)).toEqual([]);
  await page.getByLabel("מדד או קטגוריה").selectOption("spending_by_category:food");
  await page.getByRole("button", { name: "הצגת עסקאות תורמות (1)" }).click();
  await expect(page.getByText("Synthetic grocery")).toBeVisible();

  await page.goto("/expenses");
  await expect(page.getByRole("heading", { name: "התפלגות לפי קטגוריה" })).toBeVisible();
  await expect(page.getByText("כל זיהוי הוא היוריסטי בלבד ואינו סיווג חשבונאי.")).toBeVisible();
  await expect(page.getByText(/קטגוריות ההוצאות מבוססות על קטגוריית הניתוח \(analysis_category\), ובהיעדרה על קטגוריית המקור \(source_category\)/)).toBeVisible();
  expect((await axe()).violations.map((violation) => violation.id)).toEqual([]);
  await page.getByRole("button", { name: "הצגת העסקאות בדפוס (1)" }).click();
  await expect(page.getByText("Synthetic grocery")).toBeVisible();
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
