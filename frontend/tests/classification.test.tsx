import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ClassificationFeature } from "@/features/classification/ClassificationFeature";

const result = {
  transaction_id: 1,
  booking_date: "2026-09-09",
  amount: "-75",
  currency: "ILS",
  account_kind: "bank",
  source_category: "food",
  source_movement_type: "purchase",
  economic_class: "consumption",
  expense_behavior: "unknown",
  analysis_category: "food",
  source: "builtin_rule",
  policy_version: "classification-v1",
  explanation: "Ordinary negative bank or card purchase.",
  issues: [],
  override_ids: [],
};
const queueItem = {
  transaction_id: 1,
  booking_date: "2026-09-09",
  amount: "-75",
  currency: "ILS",
  description: "Synthetic market",
  account_kind: "bank",
  source_category: "food",
  source_movement_type: "purchase",
  effective_classification: result,
  source_fields: { normalized: { source: "fixture" } },
  issues: [],
  expected_override_version: 12,
  expected_classification_state: "a".repeat(64),
};
const coverage = {
  month: "2026-09",
  currency: "ILS",
  total_accepted: 3,
  classified_count: 2,
  unclassified_count: 1,
  review_required_count: 1,
  classification_coverage_percent: "66.7",
  by_economic_class: { income: 0, consumption: 2, refund: 0, internal_transfer: 0, savings_transfer: 0, credit_card_settlement: 0, debt_principal: 0, unclassified: 1 },
  by_source: { override: 0, reusable_rule: 0, builtin_rule: 2, unclassified: 1 },
  issue_counts: { UNCLASSIFIED_TRANSACTION: 1 },
};

function response(data: unknown, meta: Record<string, unknown> = {}) {
  return new Response(JSON.stringify({ data, meta }), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("classification feature", () => {
  it("prefills a stored conflicting decision, blocks invalid saves and sends an explicit correction", async () => {
    let saved = false;
    const item = { ...queueItem, amount: "72.4", effective_classification: { ...result, amount: "72.4", imported_amount: "72.4", original_amount: "-72.4", original_currency: "ILS", economic_class: "unclassified", source: "override", issues: [{ code: "INVALID_CLASS_SIGN", message: "Wrong sign", severity: "error" }] }, saved_override: { economic_class: "consumption", analysis_category: "אחסון ענן", expense_behavior: "fixed" } };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/planning/categories")) return response(["אחסון ענן"]);
      if (url.includes("/classification/coverage")) return response(coverage);
      if (url.includes("/classification/review-queue")) return response(saved ? [] : [item]);
      if (url.includes("/classification/rules")) return response([]);
      if (url.includes("/transactions/1/override") && init?.method === "POST") {
        expect(JSON.parse(String(init.body))).toMatchObject({ economic_class: "consumption", effective_amount: "-72.4", analysis_category: "אחסון ענן", expense_behavior: "fixed", reason: "תיקון סכום וכיוון לאחר בדיקת פרטי המקור" });
        saved = true;
        return response({ result: { ...result, amount: "-72.4", economic_class: "consumption" }, override_version: 15, expected_classification_state: "b".repeat(64) });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ClassificationFeature />);
    await screen.findByText("Synthetic market");
    fireEvent.click(screen.getByRole("button", { name: "עריכת סיווג" }));
    expect(screen.getByLabelText("קטגוריית ניתוח", { selector: "#category-1" })).toHaveValue("אחסון ענן");
    expect(screen.getByLabelText("סיווג כלכלי", { selector: "#class-1" })).toHaveValue("consumption");
    expect(screen.getByRole("button", { name: "שמירת תיקון" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("כיוון מאומת"), { target: { value: "debit" } });
    expect(screen.getByLabelText("סכום לחישוב")).toHaveValue("-72.4");
    expect(screen.getByRole("button", { name: "שמירת תיקון" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "שמירת תיקון" }));
    await waitFor(() => expect(saved).toBe(true));
    await waitFor(() => expect(screen.getByText(/התיקון לעסקה 1 נשמר/)).toBeVisible());
    await waitFor(() => expect(screen.queryByText("Synthetic market")).not.toBeInTheDocument());
  });

  it("resolves a positive reporting amount by classification without copying the negative original sign", async () => {
    let saved = false;
    const item = { ...queueItem, amount: "72.4", effective_classification: { ...result, amount: "72.4", imported_amount: "72.4", original_amount: "-72.4", original_currency: "ILS", economic_class: "unclassified", source: "override", issues: [{ code: "INVALID_CLASS_SIGN", message: "Wrong sign", severity: "error" }] }, saved_override: { economic_class: "consumption", analysis_category: "אחסון ענן", expense_behavior: "not_applicable" } };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/planning/categories")) return response([]);
      if (url.includes("/classification/coverage")) return response(coverage);
      if (url.includes("/classification/review-queue")) return response(saved ? [] : [item]);
      if (url.includes("/classification/rules")) return response([]);
      if (url.includes("/transactions/1/override") && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        expect(body.economic_class).toBe("income");
        expect(body).not.toHaveProperty("effective_amount");
        saved = true;
        return response({ result: { ...result, amount: "72.4", economic_class: "income" }, override_version: 15, expected_classification_state: "b".repeat(64) });
      }
      throw new Error(`Unexpected request: ${url}`);
    }));
    render(<ClassificationFeature />);
    await screen.findByText("Synthetic market");
    fireEvent.click(screen.getByRole("button", { name: "עריכת סיווג" }));
    expect(screen.getByText("סכום · הבסיס לדוחות")).toBeVisible();
    expect(screen.getByText(/הסימן שלה אינו קובע אם זו הכנסה או הוצאה/)).toBeVisible();
    expect(screen.getByLabelText("לתקן את הסכום לחישוב")).not.toBeChecked();
    fireEvent.change(screen.getByLabelText("סיווג כלכלי", { selector: "#class-1" }), { target: { value: "income" } });
    expect(screen.getByRole("button", { name: "שמירת תיקון" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "שמירת תיקון" }));
    await waitFor(() => expect(saved).toBe(true));
    await waitFor(() => expect(screen.queryByText("Synthetic market")).not.toBeInTheDocument());
  });

  it("lets a zero-value fee be reviewed without adding an expense or changing its amount", async () => {
    let saved = false;
    const item = { ...queueItem, amount: "0", effective_classification: { ...result, amount: "0", imported_amount: "0", original_amount: "-17.9", economic_class: "unclassified", source: "override", issues: [{ code: "INVALID_CLASS_SIGN", message: "Wrong sign", severity: "error" }] }, saved_override: { economic_class: "consumption", expense_behavior: "fixed" } };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/planning/categories")) return response([]);
      if (url.includes("/classification/coverage")) return response(coverage);
      if (url.includes("/classification/review-queue")) return response(saved ? [] : [item]);
      if (url.includes("/classification/rules")) return response([]);
      if (url.includes("/transactions/1/override") && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        expect(body.economic_class).toBe("no_financial_effect");
        expect(body.expense_behavior).toBe("not_applicable");
        expect(body).not.toHaveProperty("effective_amount");
        saved = true;
        return response({ result: { ...result, amount: "0", economic_class: "no_financial_effect" }, override_version: 15, expected_classification_state: "b".repeat(64) });
      }
      throw new Error(`Unexpected request: ${url}`);
    }));
    render(<ClassificationFeature />);
    await screen.findByText("Synthetic market");
    fireEvent.click(screen.getByRole("button", { name: "עריכת סיווג" }));
    expect(screen.getByRole("button", { name: "שמירת תיקון" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("סיווג כלכלי", { selector: "#class-1" }), { target: { value: "no_financial_effect" } });
    expect(screen.getByText(/השורה תסומן כנבדקה/)).toBeVisible();
    expect(screen.getByLabelText("לתקן את הסכום לחישוב")).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "שמירת תיקון" }));
    await waitFor(() => expect(saved).toBe(true));
    await waitFor(() => expect(screen.queryByText("Synthetic market")).not.toBeInTheDocument());
  });

  it("suggests historical categories in both editors and refreshes after saving a new name", async () => {
    let categories = ["food", "transport"];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/planning/categories")) {
        expect(url).toContain("currency=ILS");
        return response(categories);
      }
      if (url.includes("/classification/coverage")) return response(coverage);
      if (url.includes("/classification/review-queue")) return response([queueItem]);
      if (url.includes("/classification/rules")) return response([]);
      if (url.includes("/transactions/1/override") && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        expect(body.analysis_category).toBe("קטגוריה חדשה");
        categories = [...categories, body.analysis_category];
        return response({ result: { ...result, analysis_category: body.analysis_category, source: "override" }, override_version: 15, expected_classification_state: "b".repeat(64) });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ClassificationFeature />);
    await screen.findByText("Synthetic market");
    fireEvent.click(screen.getByText("כללי סיווג חוזרים", { exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "עריכת סיווג" }));
    const overrideInput = screen.getByLabelText("קטגוריית ניתוח", { selector: "#category-1" });
    const ruleInput = screen.getByLabelText("קטגוריית ניתוח", { selector: "#rule-analysis-category" });
    await waitFor(() => {
      const list = document.getElementById(overrideInput.getAttribute("list")!);
      expect(Array.from(list!.querySelectorAll("option"), (option) => option.value)).toEqual(categories);
    });
    expect(ruleInput).toHaveAttribute("list", overrideInput.getAttribute("list"));
    expect(overrideInput).toHaveAccessibleDescription("אפשר לבחור קטגוריה קיימת או להקליד שם חדש.");
    fireEvent.click(overrideInput.parentElement!.querySelector("button")!);
    fireEvent.click(screen.getByRole("button", { name: "transport" }));
    expect(overrideInput).toHaveValue("transport");
    expect(overrideInput).toHaveFocus();
    fireEvent.change(overrideInput, { target: { value: "קטגוריה חדשה" } });
    fireEvent.click(screen.getByRole("button", { name: "שמירת תיקון" }));
    await waitFor(() => expect(document.getElementById(ruleInput.getAttribute("list")!)!.querySelector('option[value="קטגוריה חדשה"]')).not.toBeNull());
  });

  it("scopes rule suggestions by currency and keeps free text usable when suggestions fail", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/planning/categories")) {
        if (url.includes("currency=USD")) return new Response("", { status: 400 });
        return response(["food"]);
      }
      if (url.includes("/classification/coverage")) return response(coverage);
      if (url.includes("/classification/review-queue")) return response([queueItem]);
      if (url.includes("/classification/rules")) return response([]);
      throw new Error(`Unexpected request: ${url}`);
    }));
    render(<ClassificationFeature />);
    await screen.findByText("Synthetic market");
    fireEvent.click(screen.getByText("כללי סיווג חוזרים", { exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "עריכת סיווג" }));
    fireEvent.change(screen.getByLabelText(/מטבע/, { selector: "#rule-currency" }), { target: { value: "USD" } });
    await screen.findByText("לא ניתן לטעון הצעות כרגע. אפשר להקליד שם קטגוריה.");
    const ruleInput = screen.getByLabelText("קטגוריית ניתוח", { selector: "#rule-analysis-category" });
    fireEvent.change(ruleInput, { target: { value: "Custom category" } });
    expect(ruleInput).toHaveValue("Custom category");
    const overrideInput = screen.getByLabelText("קטגוריית ניתוח", { selector: "#category-1" });
    expect(ruleInput.getAttribute("list")).not.toEqual(overrideInput.getAttribute("list"));
    expect(document.getElementById(overrideInput.getAttribute("list")!)!.querySelector('option[value="food"]')).not.toBeNull();
    expect(screen.getByText("Synthetic market")).toBeVisible();
  });

  it("shows service coverage and submits an override against the loaded version", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/planning/categories")) return response(["food", "transport"]);
      if (url.includes("/classification/coverage")) return response(coverage);
      if (url.includes("/classification/review-queue")) return response([queueItem]);
      if (url.includes("/classification/rules")) return response([]);
      if (url.includes("/transactions/1/override") && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        expect(body.expected_override_version).toBe(12);
        expect(body.expected_classification_state).toBe("a".repeat(64));
        expect(body.reason).toBe("Saved from classification review");
        return response({ result: { ...result, source: "override" }, override_version: 15, expected_classification_state: "b".repeat(64) });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ClassificationFeature />);
    expect(await screen.findByText("66.7%")).toBeInTheDocument();
    expect(screen.getByText("כיסוי סיווג")).toBeInTheDocument();
    expect(screen.getByText("Synthetic market")).toBeInTheDocument();
    expect(screen.queryByText("רכישה בחשבון בנק או בכרטיס אשראי שסווגה כהוצאה.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "עריכת סיווג" }));
    expect(screen.getByText("רכישה בחשבון בנק או בכרטיס אשראי שסווגה כהוצאה.")).toBeVisible();
    expect(screen.getByText("Ordinary negative bank or card purchase.")).not.toBeVisible();
    const save = screen.getByRole("button", { name: "שמירת תיקון" });
    const form = save.closest("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form!);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/classification/transactions/1/override"),
      expect.objectContaining({ method: "POST" }),
    ));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url, init]) =>
      String(url).includes("/transactions/1/override") && init?.method === "POST",
    )).toHaveLength(1));
    expect(await screen.findByRole("status")).toHaveTextContent("הסיווג הפעיל: צריכה");
    expect(screen.queryByRole("button", { name: "שמירת תיקון" })).not.toBeInTheDocument();
  });

  it("explains a saved unclassified decision after refresh", async () => {
    const invalidSign = false;
    let saved = false;
    const issues = invalidSign ? [{ code: "INVALID_CLASS_SIGN", message: "consumption requires a negative debit amount", severity: "error" }] : [];
    const unclassified = { ...result, amount: "630", economic_class: "unclassified", source: "override", issues };
    const item = { ...queueItem, amount: "630", effective_classification: unclassified, issues };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/planning/categories")) return response(["food", "transport"]);
      if (url.includes("/classification/coverage")) return response(coverage);
      if (url.includes("/classification/review-queue")) return response([{ ...item, expected_override_version: saved ? 15 : 12 }]);
      if (url.includes("/classification/rules")) return response([]);
      if (url.includes("/transactions/1/override") && init?.method === "POST") {
        saved = true;
        return response({ result: unclassified, override_version: 15, expected_classification_state: "b".repeat(64) });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ClassificationFeature />);
    await screen.findByText("Synthetic market");
    if (invalidSign) expect(screen.getByText(/סכום חיובי מציין זיכוי/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "עריכת סיווג" }));
    fireEvent.change(screen.getByLabelText("סיווג כלכלי", { selector: "#class-1" }), { target: { value: invalidSign ? "consumption" : "unclassified" } });
    fireEvent.click(screen.getByRole("button", { name: "שמירת תיקון" }));
    const feedback = await screen.findByRole("alert");
    expect(feedback).toHaveTextContent(invalidSign ? "הסיווג ״צריכה״ לא הוחל" : "העסקה עדיין לא מסווגת");
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/classification/review-queue")).length).toBeGreaterThan(1));
    expect(screen.getByRole("alert")).toBeVisible();
    expect(screen.getByRole("button", { name: "שמירת תיקון" })).toBeVisible();
  });

  it("keeps the rule create disabled until a matching preview and sends its revision precondition", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/planning/categories")) return response(["food", "transport"]);
      if (url.includes("/classification/coverage")) return response(coverage);
      if (url.includes("/classification/review-queue")) return response([]);
      if (url.includes("/classification/rules/previews")) {
        return response({ count: 2, rule: {}, expected_current_rule_id: 8 });
      }
      if (url.endsWith("/classification/rules") && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        expect(body.expected_current_rule_id).toBe(8);
        return response({ id: 9, revision: 2 });
      }
      if (url.includes("/classification/rules")) return response([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ClassificationFeature />);
    await screen.findByText("כיסוי סיווג");
    fireEvent.click(screen.getByText("כללי סיווג חוזרים", { exact: true }));
    const create = screen.getByRole("button", { name: "יצירת כלל" });
    expect(create).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/קטגוריית מקור/), { target: { value: "food" } });
    fireEvent.click(screen.getByRole("button", { name: "תצוגה מקדימה" }));
    expect(await screen.findByText("הכלל יתאים ל־2 עסקאות שהתקבלו.")).toBeInTheDocument();
    expect(create).toBeEnabled();
    fireEvent.click(create);
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) =>
      String(url).endsWith("/classification/rules") && init?.method === "POST",
    )).toBe(true));
  });
});

it("opens dashboard review links with the reporting month and unclassified filter", async () => {
  window.history.replaceState({}, "", "/classification?month=2026-09&currency=ILS&economic_class=unclassified");
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/classification/coverage")) return response(coverage);
    return response([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<ClassificationFeature />);
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("month=2026-09") && String(url).includes("economic_class=unclassified"))).toBe(true));
  window.history.replaceState({}, "", "/");
});

it("opens all monthly transactions from the overview, including already classified rows", async () => {
  window.history.replaceState({}, "", "/classification?month=2026-09&currency=USD&include_resolved=true");
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => String(input).includes("/classification/coverage") ? response(coverage) : response([]));
  vi.stubGlobal("fetch", fetchMock);
  render(<ClassificationFeature />);
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/review-queue?") && String(url).includes("month=2026-09") && String(url).includes("currency=USD") && String(url).includes("include_resolved=true"))).toBe(true));
  expect(screen.getByLabelText("הצגת עסקאות שכבר סווגו")).toBeChecked();
  window.history.replaceState({}, "", "/");
});

it("keeps secondary tools collapsed and opens only the selected transaction editor", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/classification/coverage")) return response(coverage);
    if (url.includes("/classification/review-queue")) return response([queueItem, { ...queueItem, transaction_id: 2, description: "Second purchase" }]);
    return response([]);
  }));
  render(<ClassificationFeature />);
  await screen.findByText("Second purchase");
  for (const label of ["פירוט כיסוי הסיווג", "מסננים נוספים", "כללי סיווג חוזרים"]) {
    expect(screen.getByText(label, { exact: true }).closest("details")).not.toHaveAttribute("open");
  }
  const edit = screen.getAllByRole("button", { name: "עריכת סיווג" });
  fireEvent.click(edit[0]);
  expect(screen.getByRole("region", { name: "עריכת העסקה: Synthetic market" })).toBeVisible();
  fireEvent.click(edit[1]);
  expect(screen.queryByRole("region", { name: "עריכת העסקה: Synthetic market" })).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "עריכת העסקה: Second purchase" })).toBeVisible();
  expect(edit[0]).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(screen.getByText("מסננים נוספים", { exact: true }));
  expect(screen.getByLabelText("קוד בדיקה")).toBeVisible();
});


it("offers zero-value review only in the transaction editor, not reusable rules", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/classification/coverage")) return response(coverage);
    if (url.includes("/classification/review-queue")) return response([queueItem]);
    return response([]);
  }));
  render(<ClassificationFeature />);
  fireEvent.click(await screen.findByRole("button", { name: "עריכת סיווג" }));
  const transactionClass = screen.getByLabelText("סיווג כלכלי", { selector: "#class-1" });
  expect(within(transactionClass).getByRole("option", { name: "נבדק - ללא השפעה כספית" })).toBeInTheDocument();
  fireEvent.click(screen.getByText("כללי סיווג חוזרים", { exact: true }));
  const ruleClass = screen.getByLabelText("סיווג כלכלי", { selector: "#rule-class" });
  expect(within(ruleClass).queryByRole("option", { name: "נבדק - ללא השפעה כספית" })).not.toBeInTheDocument();
});

it("submits an explicit null when clearing a saved category", async () => {
  const item = { ...queueItem, saved_override: { economic_class: "consumption", analysis_category: "Groceries", expense_behavior: "unknown" }, effective_classification: { ...queueItem.effective_classification, analysis_category: "Groceries", source: "override" } };
  let submitted: Record<string, unknown> | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/classification/coverage")) return response(coverage);
    if (url.includes("/classification/review-queue")) return response([item]);
    if (url.includes("/transactions/1/override") && init?.method === "POST") {
      submitted = JSON.parse(String(init.body));
      return response({ result: { ...item.effective_classification, analysis_category: "food" }, override_version: 15, expected_classification_state: "b".repeat(64) });
    }
    return response([]);
  }));
  render(<ClassificationFeature />);
  fireEvent.click(await screen.findByRole("button", { name: "עריכת סיווג" }));
  const category = screen.getByLabelText("קטגוריית ניתוח", { selector: "#category-1" });
  expect(category).toHaveValue("Groceries");
  fireEvent.change(category, { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "שמירת תיקון" }));
  await waitFor(() => expect(submitted).toMatchObject({ analysis_category: null, economic_class: "consumption" }));
});
