import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

test("disconnected internet still allows real local auth, dashboard and multipart import", async ({ page, context }) => {
  const external: string[] = [];
  await context.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname !== "127.0.0.1") {
      external.push(url.origin);
      await route.abort();
    } else await route.continue();
  });
  await page.addInitScript(() => Object.defineProperty(navigator, "onLine", { get: () => false }));
  await page.goto("/");
  await page.getByLabel("שם משתמש").fill("qa-one");
  await page.getByLabel("סיסמה").fill("Local-test-password-One!");
  await page.getByRole("button", { name: "התחברות", exact: true }).click();
  await expect(page.locator(".dashboard-value").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "יציאה", exact: true })).toBeVisible();
  const cookie = (await context.cookies()).find((item) => item.name === "familyfin_session");
  expect(cookie).toMatchObject({ httpOnly: true, sameSite: "Strict", secure: false, path: "/api/v1" });
  await page.reload();
  await expect(page.locator(".dashboard-value").first()).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  await expect(page.locator(".dashboard-value").first()).toBeVisible();

  // Reporting cards and the trend range have independent scopes.
  const trendEnd = await page.locator('input[name="end_month"]').inputValue();
  await page.getByRole("button", { name: "חודש לסקירה", exact: true }).click();
  await page.getByRole("button", { name: "אוקטובר 2026", exact: true }).click();
  await expect(page.getByText(/אין נתונים לחודש זה במטבע שנבחר/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "סה״כ הכנסות", exact: true })).toHaveCount(0);
  await expect(page.locator('input[name="end_month"]')).toHaveValue(trendEnd);
  await page.getByRole("button", { name: "חודש לסקירה", exact: true }).click();
  await page.getByRole("button", { name: "ספטמבר 2026", exact: true }).click();
  await expect(page.getByRole("heading", { name: "סה״כ הכנסות", exact: true })).toBeVisible();

  await page.getByText("סטטיסטיקה והשוואות", { exact: true }).click();
  const statistics = page.locator(".dashboard-period-statistics");
  await expect(statistics.getByRole("heading", { name: "ממוצע לחודש בתקופה" })).toBeVisible();
  await expect(statistics.getByText(/כולל 1 חודש עם נתונים חלקיים/)).toBeVisible();
  await statistics.getByRole("radio", { name: /חודשים מלאים בלבד/ }).check();
  await expect(statistics.getByText(/1 חודש עם נתונים חלקיים לא נכלל/)).toBeVisible();
  await statistics.getByRole("radio", { name: /כל החודשים עם נתונים/ }).check();

  const desktopViewport = page.viewportSize()!;
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  const filters = page.getByRole("button", { name: /תקופת הדוח/ });
  await expect(filters).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByLabel("חודש התחלה", { exact: true })).toBeHidden();
  await filters.click();
  await expect(page.getByLabel("חודש התחלה", { exact: true })).toBeVisible();
  await page.getByText("הצגת נתונים בטבלה", { exact: true }).click();
  const matrixScroll = page.getByRole("region", { name: "גלילת נתוני התרשים" });
  await expect(matrixScroll).toBeVisible();
  await expect(matrixScroll.getByRole("rowheader")).toHaveCount(3);
  await expect.poll(() => matrixScroll.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
  await matrixScroll.focus();
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.setViewportSize({ width: 320, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  await filters.click();
  await expect(page.getByLabel("חודש התחלה", { exact: true })).toBeHidden();
  await page.setViewportSize(desktopViewport);
  await expect(filters).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByLabel("חודש התחלה", { exact: true })).toBeHidden();
  await filters.click();
  await expect(page.getByLabel("חודש התחלה", { exact: true })).toBeVisible();

  // Resolve a source-sign conflict through the real proxy/API, then verify report values.
  await page.goto("/classification");
  const conflictCard = page.getByRole("article").filter({has:page.getByRole("heading",{name:"Cloud conflict fixture",exact:true})});
  await conflictCard.getByRole("button",{name:"עריכת סיווג"}).click();
  await expect(conflictCard.getByLabel("קטגוריית ניתוח",{exact:true})).toHaveValue("אחסון ענן");
  await expect(conflictCard.getByRole("button",{name:"שמירת תיקון"})).toBeDisabled();
  await conflictCard.getByLabel("כיוון מאומת").selectOption("debit");
  const correctedResponse = page.waitForResponse((response)=>response.url().endsWith("/override") && response.request().method()==="POST");
  await conflictCard.getByRole("button",{name:"שמירת תיקון"}).click();
  const corrected = await correctedResponse;
  expect(corrected.status()).toBe(200);
  const correction = (await corrected.json()).data;
  expect(correction.result).toMatchObject({amount:"-72.4",imported_amount:"72.4",original_amount:"-72.4",economic_class:"consumption",analysis_category:"אחסון ענן"});
  await expect(conflictCard).toHaveCount(0);
  await page.goto("/dashboard");
  await expect(page.locator(".dashboard-card").filter({has:page.getByRole("heading",{name:"סה״כ הוצאות",exact:true})})).toContainText("89.8");
  await page.goto("/expenses");
  await expect(page.getByRole("list",{name:"התפלגות הוצאות לפי קטגוריה"}).getByRole("listitem").filter({hasText:"אחסון ענן"})).toContainText("72.4");
  await page.goto("/classification");
  await page.getByRole("checkbox",{name:"הצגת עסקאות שכבר סווגו"}).check();
  await conflictCard.getByRole("button",{name:"עריכת סיווג"}).click();
  const undoResponse = page.waitForResponse((response)=>response.url().endsWith("/override") && response.request().method()==="DELETE");
  await conflictCard.getByRole("button",{name:"ביטול תיקון וחזרה למקור"}).click();
  expect((await undoResponse).status()).toBe(200);

  // Explicitly review a zero fee without inventing a charge or losing provenance.
  const zeroCard = page.getByRole("article").filter({has:page.getByRole("heading",{name:"Waived card fee fixture",exact:true})});
  await zeroCard.getByRole("button",{name:"עריכת סיווג"}).click();
  await zeroCard.getByLabel("סיווג כלכלי",{exact:true}).selectOption("no_financial_effect");
  await expect(zeroCard.getByLabel("לתקן את הסכום לחישוב")).not.toBeChecked();
  const zeroResponse = page.waitForResponse(response=>response.url().endsWith("/override") && response.request().method()==="POST");
  await zeroCard.getByRole("button",{name:"שמירת תיקון"}).click();
  const zeroSaved = await zeroResponse;
  expect(zeroSaved.status()).toBe(200);
  expect((await zeroSaved.json()).data.result).toMatchObject({amount:"0",imported_amount:"0",original_amount:"-17.9",economic_class:"no_financial_effect",expense_behavior:"not_applicable"});
  await page.getByRole("checkbox",{name:"הצגת עסקאות שכבר סווגו"}).uncheck();
  await expect(zeroCard).toHaveCount(0);
  await page.getByRole("checkbox",{name:"הצגת עסקאות שכבר סווגו"}).check();
  await zeroCard.getByRole("button",{name:"עריכת סיווג"}).click();
  const zeroUndo = page.waitForResponse(response=>response.url().endsWith("/override") && response.request().method()==="DELETE");
  await zeroCard.getByRole("button",{name:"ביטול תיקון וחזרה למקור"}).click();
  expect((await zeroUndo).status()).toBe(200);

  await page.goto("/data-quality");
  await page.getByRole("heading", { name: "חודשים שדורשים השלמה", exact: true }).waitFor();
  await page.setViewportSize({ width: 320, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  await page.setViewportSize(desktopViewport);
  const fixture = readFileSync(".next-local/live-fixture-path", "utf8");
  await page.getByLabel("קובץ XLSX של FamilyBiz", { exact: true }).setInputFiles(fixture);
  const previewResponse = page.waitForResponse((response) => response.url().endsWith("/imports/familybiz/previews"));
  await page.getByRole("button", { name: "בדיקה ותצוגה מקדימה", exact: true }).click();
  expect((await previewResponse).status()).toBe(200);
  await expect(page.getByRole("button", { name: "אישור וייבוא", exact: true })).toBeEnabled();
  const commitResponse = page.waitForResponse((response) => response.url().endsWith("/imports/familybiz/commits"));
  await page.getByRole("button", { name: "אישור וייבוא", exact: true }).click();
  const committed = await commitResponse;
  expect(committed.status()).toBe(200);
  expect(committed.headers()["cache-control"]).toContain("no-store");

  await page.goto("/");
  await expect(page.locator(".dashboard-value").first()).toBeVisible();
  // Simulate API outage while the browser and local web server remain available.
  await context.route("**/api/**", (route) => route.abort());
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  await expect(page.getByRole("heading", { name: "נדרש חיבור מאומת מחדש" })).toBeVisible();
  await expect(page.locator(".dashboard-feature")).toHaveCount(0);
  await context.unroute("**/api/**");
  await page.getByRole("button", { name: "לנסות שוב" }).click();
  await expect(page.locator(".dashboard-value").first()).toBeVisible();
  await page.getByRole("button", { name: "יציאה", exact: true }).click();
  await expect(page.getByRole("button", { name: "התחברות", exact: true })).toBeVisible();
  expect((await context.cookies()).some((item) => item.name === "familyfin_session")).toBe(false);
  expect(external).toEqual([]);
});
