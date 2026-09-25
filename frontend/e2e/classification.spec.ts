import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const session = {
  data: { user: { id: "fixture-user", display_name: "משתמשת בדיקה" }, csrf_token: "fixture-csrf" },
  meta: { request_id: "fixture-request" },
};

function envelope(data: unknown) {
  return { data, meta: { request_id: "classification-fixture" } };
}

async function mockClassificationApi(page: Page) {
  let overrideVersion = 4;
  let classificationState = "a".repeat(64);
  let result: Record<string, unknown> = {
    transaction_id: 21,
    booking_date: "2026-09-09",
    amount: "-75",
    currency: "ILS",
    account_kind: "bank",
    source_category: "food",
    source_movement_type: "purchase",
    economic_class: "unclassified",
    expense_behavior: "not_applicable",
    analysis_category: null,
    source: "unclassified",
    policy_version: "classification-v1",
    explanation: "Requires review.",
    issues: [{ code: "UNCLASSIFIED_TRANSACTION", message: "Review this transaction.", severity: "warning" }],
    rule_id: null,
    override_ids: [],
  };
  let rules: Array<Record<string, unknown>> = [];

  await page.route("**/api/v1/auth/session", async (route) => {
    if (route.request().method() === "GET") await route.fulfill({ status: 200, json: session });
    else await route.fulfill({ status: 204 });
  });
  await page.route("**/api/v1/classification/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path.endsWith("/coverage")) {
      await route.fulfill({ status: 200, json: envelope({
        month: null,
        currency: "ILS",
        total_accepted: 1,
        classified_count: result.economic_class === "unclassified" ? 0 : 1,
        unclassified_count: result.economic_class === "unclassified" ? 1 : 0,
        review_required_count: result.economic_class === "unclassified" ? 1 : 0,
        classification_coverage_percent: result.economic_class === "unclassified" ? "0.0" : "100.0",
        by_economic_class: { income: 0, consumption: 0, refund: 0, internal_transfer: 0, savings_transfer: 0, credit_card_settlement: 0, debt_principal: 0, unclassified: result.economic_class === "unclassified" ? 1 : 0 },
        by_source: { override: result.source === "override" ? 1 : 0, reusable_rule: result.source === "reusable_rule" ? 1 : 0, builtin_rule: result.source === "builtin_rule" ? 1 : 0, unclassified: result.source === "unclassified" ? 1 : 0 },
        issue_counts: result.economic_class === "unclassified" ? { UNCLASSIFIED_TRANSACTION: 1 } : {},
      }) });
      return;
    }
    if (path.endsWith("/review-queue")) {
      const items = url.searchParams.get("include_resolved") === "true" || result.economic_class === "unclassified"
        ? [{
            transaction_id: 21,
            booking_date: "2026-09-09",
            amount: "-75",
            currency: "ILS",
            description: "Synthetic market",
            account_kind: "bank",
            source_category: "food",
            source_movement_type: "purchase",
            effective_classification: result,
            source_fields: { normalized: { sample: "fixture" } },
            issues: result.issues,
            expected_override_version: overrideVersion,
            expected_classification_state: classificationState,
          }]
        : [];
      await route.fulfill({ status: 200, json: envelope(items) });
      return;
    }
    if (path.endsWith("/rules/previews") && request.method() === "POST") {
      await route.fulfill({ status: 200, json: envelope({ count: 1, rule: {}, expected_current_rule_id: null }) });
      return;
    }
    if (path.endsWith("/rules") && request.method() === "POST") {
      const input = request.postDataJSON();
      expect(input.expected_current_rule_id).toBeNull();
      const saved = { ...input, id: 31, revision: 1, source_movement_type: input.source_movement_type ?? "", is_active: true, is_tombstone: false, is_current: true, effective_active: true };
      rules = [saved];
      await route.fulfill({ status: 200, json: envelope(saved) });
      return;
    }
    if (path.endsWith("/rules/31/disable") && request.method() === "POST") {
      const saved = { ...rules[0], id: 32, revision: 2, active: false, tombstone: true, is_active: false, is_tombstone: true, is_current: true, effective_active: false };
      rules = [{ ...rules[0], is_current: false, effective_active: false }, saved];
      await route.fulfill({ status: 200, json: envelope(saved) });
      return;
    }
    if (path.endsWith("/rules")) {
      await route.fulfill({ status: 200, json: envelope(rules), headers: { "Cache-Control": "private, no-store" } });
      return;
    }
    if (path.endsWith("/transactions/21/override") && request.method() === "POST") {
      const input = request.postDataJSON();
      expect(input.expected_override_version).toBe(overrideVersion);
      expect(input.expected_classification_state).toBe(classificationState);
      overrideVersion += 1;
      classificationState = "b".repeat(64);
      result = { ...result, economic_class: input.economic_class, expense_behavior: input.expense_behavior, analysis_category: input.analysis_category, source: "override", issues: [], override_ids: [51] };
      await route.fulfill({ status: 200, json: envelope({ result, override_version: overrideVersion, expected_classification_state: classificationState }) });
      return;
    }
    throw new Error(`Unhandled classification request: ${request.method()} ${path}`);
  });
}

test("classification review, conditional override, reusable-rule lifecycle, and coverage", async ({ page }) => {
  await mockClassificationApi(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/classification");

  await expect(page.getByRole("heading", { name: "סיווג עסקאות" })).toBeVisible();
  await expect(page.getByText("0.0%", { exact: true })).toBeVisible();
  await expect(page.getByText("Synthetic market")).toBeVisible();
  await page.getByRole("button", { name: "עריכת סיווג" }).click();
  await page.locator("#class-21").selectOption("consumption");
  await page.getByRole("button", { name: "שמירת תיקון" }).click();
  await expect(page.getByText("100.0%", { exact: true })).toBeVisible();

  await page.getByLabel(/קטגוריית מקור/).fill("food");
  await page.getByLabel("סוג תנועה במקור").fill("purchase");
  await page.getByRole("button", { name: "תצוגה מקדימה" }).click();
  await expect(page.getByText("הכלל יתאים ל־1 עסקאות שהתקבלו.")).toBeVisible();
  await page.getByRole("button", { name: "יצירת כלל" }).click();
  await expect(page.getByText(/גרסה 1 · מזהה 31 · פעילה/)).toBeVisible();
  await page.getByRole("button", { name: "השבתת כלל" }).click();
  await expect(page.getByText(/גרסה 2 · מזהה 32 · נוכחית ומושבתת/)).toBeVisible();

  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(results.violations.map((violation) => `${violation.id}: ${violation.help}`)).toEqual([]);
});
