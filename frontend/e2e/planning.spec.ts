import { expect, test } from "@playwright/test";

const session = {
  data: { user: { id: "fixture-user", display_name: "משתמשת בדיקה" }, csrf_token: "fixture-csrf" },
  meta: { request_id: "planning-fixture" },
};

function makeItem(amount: string, overrides: Record<string, unknown> = {}) {
  return {
    id: "item-1", kind: "savings_contribution", label: "חיסכון חודשי", category: null, amount,
    frequency: "one_time", start_month: null, end_month: null, occurrence_month: "2026-10-01",
    origin: "manual", source_range: null, source_row: null, policy_version: "planning-v1",
    completeness_codes: [], contributor_transaction_ids: [], provenance: {}, notes: [], ...overrides,
  };
}

function makeRevision(number: number, items: Array<Record<string, unknown>>, notes = "") {
  return {
    revision_id: `revision-${number}`, scenario_id: "scenario-1", revision_number: number,
    items, notes, created_at: `2026-09-${String(number).padStart(2, "0")}T09:00:00Z`,
    provisional: false, issue_codes: [], completeness_snapshot: [], expense_notes: [],
  };
}

function makeProjection(revisionNumber: number) {
  return {
    scenario_id: "scenario-1", revision_number: revisionNumber, currency: "ILS", provisional: false, issue_codes: [],
    months: Array.from({ length: 12 }, (_, index) => ({
      month: `2026-${String(10 + index > 12 ? 10 + index - 12 : 10 + index).padStart(2, "0")}-01`,
      currency: "ILS", income: "10000", expenses: "4000", savings_contributions: "0", savings_withdrawals: "0",
      operating_surplus: "6000", net_planned_savings: "0", cash_remaining_after_savings: "6000",
      expenses_by_category: {}, income_by_category: {}, contributor_item_ids: {}, unmapped_expense_categories: [],
    })),
  };
}

test("mobile RTL planning wizard saves assumptions and reports a current-revision conflict", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/v1/auth/session", async (route) => {
    if (route.request().method() === "GET") await route.fulfill({ status: 200, json: session });
    else await route.fulfill({ status: 204 });
  });

  let scenarioExists = false;
  let currentRevision = 1;
  let originalItems: Array<Record<string, unknown>> = [];
  const scenario = () => ({
    scenario_id: "scenario-1", name: "טיול 2026", currency: "ILS", start_month: "2026-10-01", end_month: "2027-09-01",
    current_revision_number: currentRevision, archived: false, clone_of_scenario_id: null,
    created_at: "2026-09-28T09:00:00Z", updated_at: "2026-09-28T09:00:00Z",
  });

  await page.route("**/api/v1/planning/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    const envelope = (data: unknown) => ({ data, meta: { request_id: "planning-fixture" } });
    if (path.endsWith("/suggested-start-month")) return route.fulfill({ status: 200, json: envelope("2026-10-01") });
    if (path.endsWith("/scenarios") && method === "GET") return route.fulfill({ status: 200, json: envelope(scenarioExists ? [scenario()] : []) });
    if (path.endsWith("/scenarios") && method === "POST") {
      const body = route.request().postDataJSON() as { name: string; currency: string; start_month: string; items: Array<Record<string, unknown>> };
      expect(body.name).toBe("טיול 2026");
      expect(body.currency).toBe("ILS");
      expect(body.items[0].amount).toBe("1250.25");
      expect(body.items[0].frequency).toBe("one_time");
      expect(body.items[0].occurrence_month).toBe("2026-10-01");
      scenarioExists = true;
      originalItems = body.items.map((item) => ({ ...item, id: "item-1" }));
      return route.fulfill({ status: 201, json: envelope(scenario()) });
    }
    if (path === "/api/v1/planning/scenarios/scenario-1" && method === "GET") return route.fulfill({ status: 200, json: envelope(scenario()) });
    if (path.endsWith("/scenarios/scenario-1/revisions") && method === "GET") {
      const history = [makeRevision(1, originalItems)];
      if (currentRevision === 2) history.push(makeRevision(2, [makeItem("1300.50", { id: "item-2" })], "שינוי מקביל"));
      return route.fulfill({ status: 200, json: envelope(history) });
    }
    if (path.endsWith("/scenarios/scenario-1/projection") && method === "GET") return route.fulfill({ status: 200, json: envelope(makeProjection(currentRevision)) });
    if (path.endsWith("/scenarios/scenario-1/projections") && method === "POST") return route.fulfill({ status: 200, json: envelope(makeProjection(1)) });
    if (path.endsWith("/scenarios/scenario-1/revisions") && method === "POST") {
      currentRevision = 2;
      return route.fulfill({
        status: 409,
        json: { error: { code: "STALE_REVISION", message: "Current revision is newer", fields: { current_revision_number: ["2"] }, request_id: "conflict-2" } },
      });
    }
    return route.fulfill({ status: 200, json: envelope([]) });
  });

  await page.goto("/planning");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await page.getByRole("button", { name: "תרחיש חדש" }).click();
  const editor = page.locator("section[aria-labelledby='planning-editor-title']");
  await editor.getByLabel("שם התרחיש").fill("טיול 2026");
  await editor.getByLabel("סוג").selectOption("savings_contribution");
  await editor.getByLabel("שם ההנחה").fill("חיסכון חופשה");
  await editor.getByLabel("סכום במטבע התרחיש").fill("1250.25");
  await editor.getByRole("button", { name: "המשך" }).click();
  await editor.getByLabel("תדירות").selectOption("one_time");
  await expect(editor.getByLabel("חודש ההתרחשות")).toHaveValue("2026-10");
  await editor.getByRole("button", { name: "המשך" }).click();
  await expect(editor.getByText("סקירת הנחות לפני שמירה")).toBeVisible();
  await editor.getByRole("button", { name: "יצירת תרחיש" }).click();
  await expect(page.getByRole("heading", { name: "טיול 2026", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "עריכת תרחיש" }).click();
  const edit = page.locator("section[aria-labelledby='planning-editor-title']");
  await edit.getByLabel("סכום במטבע התרחיש").fill("1400.75");
  await edit.getByRole("button", { name: "המשך" }).click();
  await edit.getByRole("button", { name: "המשך" }).click();
  await expect(edit.getByText(/חישוב הטיוטה/)).toBeVisible();
  await edit.getByRole("button", { name: "שמירת גרסה" }).click();
  await expect(page.getByRole("alert").getByText(/נשמרה גרסה 2/)).toBeVisible();
  await expect(edit.getByText("הטיוטה מבוססת על גרסה 2")).toBeVisible();
  await expect(edit.getByRole("button", { name: "שמירת גרסה" })).toBeDisabled();
});
