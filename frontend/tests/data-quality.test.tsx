import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DataQualityFeature } from "@/features/data-quality/data-quality-feature";
import type { DataQualitySummary, FamilyBizPreview, ReconciliationCase } from "@/features/data-quality/types";

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }));

vi.mock("@/components/app-provider", () => ({ useAppAuth: () => ({ online: true }) }));
vi.mock("@/lib/api", () => ({
  ApiRequestError: class ApiRequestError extends Error {
    status: number;
    apiError?: { request_id?: string; code?: string; message?: string };
    constructor(message: string, status: number, apiError?: { request_id?: string; code?: string; message?: string }) {
      super(message);
      this.status = status;
      this.apiError = apiError;
    }
  },
  apiRequest,
}));

const emptyQuality = {
  accepted_rows: 0,
  freshness_date: null,
  covered_start: null,
  covered_end: null,
  currencies: {},
  issue_counts: {},
  incomplete_months: [],
  open_reconciliation_cases: 0,
  unclassified_transaction_count: 0,
  unclassified_absolute_amount: "0",
  source_coverage: "unknown",
  latest_import: null,
};

const preview: FamilyBizPreview = {
  preview_token: "ephemeral-token",
  inspection: {
    parser_version: "familybiz-v2",
    file_sha256: "a".repeat(64),
    filename: "synthetic.xlsx",
    compressed_bytes: 512,
    uncompressed_bytes: 2048,
    sheet_names: ["Sheet1"],
    section_count: 1,
    transaction_count: 1,
    report_start: "2026-09-01",
    report_end: "2026-09-30",
    min_booking_date: "2026-09-19",
    max_booking_date: "2026-09-19",
    currencies: { ILS: 1 },
    account_kinds: { card: 1 },
    issue_counts: {},
    freshness_as_of: "2026-09-25T12:00:00Z",
    preview_rows: [{ amount: "-17.4", currency: "ILS" }],
  },
  parser_version: "familybiz-v2",
  file_sha256: "a".repeat(64),
  baseline_batch_id: null,
  baseline_fingerprint: "baseline-fingerprint",
  matching_baseline_json: "{}",
  matcher_version: "familybiz-matcher-v3",
  decision_plan_version: "familybiz-decision-plan-v1",
  decision_plan_fingerprint: "plan-fingerprint",
  decision_plan_json: "{\"decisions\":[]}",
  candidate_count: 1,
  warning_count: 0,
  rejected_count: 0,
  issue_counts: {},
  preview_rows: [{ amount: "-17.4", currency: "ILS" }],
  predicted_statistics: {
    total_records: 1,
    inserted: 1,
    unchanged: 0,
    updated: 0,
    rejected: 0,
    ambiguous: 0,
    unresolved: 0,
    duplicate_file: false,
    non_ils_records: 0,
  },
};

let qualityData: DataQualitySummary = emptyQuality;
let caseRows: ReconciliationCase[] = [];

function mockInitialLoads() {
  apiRequest.mockImplementation(async (path: string) => {
    if (path === "/dashboard/quality") return { data: qualityData };
    if (path.startsWith("/imports/history")) return { data: { items: [] }, meta: { next_cursor: null } };
    if (path.startsWith("/reconciliation/cases")) return { data: { items: caseRows }, meta: { next_cursor: null } };
    if (path === "/imports/familybiz/previews") return { data: preview };
    throw new Error(`Unexpected API call: ${path}`);
  });
}

async function chooseFileAndPreview() {
  const input = screen.getByLabelText("קובץ XLSX של FamilyBiz");
  const file = new File(["synthetic workbook bytes"], "synthetic.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
  fireEvent.change(input, { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: "בדיקה ותצוגה מקדימה" }));
  await screen.findByText("plan-fingerprint");
}

describe("Data Quality import flow", () => {
  beforeEach(() => {
    qualityData = emptyQuality;
    caseRows = [];
    apiRequest.mockReset();
    mockInitialLoads();
  });

  it("previews the selected workbook and exposes the complete decision-plan download", async () => {
    render(<DataQualityFeature />);
    await screen.findByRole("heading", { name: "העלאת קובץ FamilyBiz" });
    await chooseFileAndPreview();

    expect(screen.getByText("רשומות מועמדות")).toBeVisible();
    expect(screen.getByRole("button", { name: "הורדת תכנית החלטות מלאה" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "אישור וייבוא" })).toBeEnabled();
    expect(apiRequest).toHaveBeenCalledWith("/imports/familybiz/previews", expect.objectContaining({ method: "POST", body: expect.any(FormData) }));
    expect(apiRequest).not.toHaveBeenCalledWith("/imports/familybiz/commits", expect.anything());
  });

  it("marks an import timeout outcome unknown and requires a fresh preview", async () => {
    const { ApiRequestError } = await import("@/lib/api");
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/dashboard/quality") return { data: qualityData };
      if (path.startsWith("/imports/history")) return { data: { items: [] }, meta: { next_cursor: null } };
      if (path.startsWith("/reconciliation/cases")) return { data: { items: caseRows }, meta: { next_cursor: null } };
      if (path === "/imports/familybiz/previews") return { data: preview };
      if (path === "/imports/familybiz/commits") throw new ApiRequestError("offline", 0);
      throw new Error(`Unexpected API call: ${path}`);
    });

    render(<DataQualityFeature />);
    await screen.findByRole("heading", { name: "העלאת קובץ FamilyBiz" });
    await chooseFileAndPreview();
    fireEvent.click(screen.getByRole("button", { name: "אישור וייבוא" }));

    expect(await screen.findByText(/מצב הייבוא אינו ידוע/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "אישור וייבוא" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "בדיקה ותצוגה חדשה" })).toBeEnabled();
    await waitFor(() => expect(apiRequest.mock.calls.filter(([path]) => path === "/imports/familybiz/commits")).toHaveLength(1));
  });
  it("does not present an empty household as complete or infer account coverage", async () => {
    qualityData = { ...emptyQuality, monthly_checks: [{ month: "2026-10-01", source_period_complete: false, classification_complete: true, unclassified_transaction_count: 0, open_reconciliation_count: 0, complete: false }] };
    render(<DataQualityFeature />);
    await screen.findByText("מתחילים מהנתונים שלכם");
    expect(screen.getByText("הדוח הראשון הוא נקודת ההתחלה")).toBeVisible();
    expect(screen.queryByText("חודשים שדורשים השלמה")).not.toBeInTheDocument();
    expect(screen.queryByText("כל החודשים בטווח עברו את שלוש הבדיקות.")).not.toBeInTheDocument();
    expect(screen.getByText(/כיסוי כל חשבונות המשפחה אינו מאומת/)).toBeVisible();
  });

  it("separates source gaps, classification and reconciliation using the service assessments", async () => {
    qualityData = { ...emptyQuality, accepted_rows: 8, unclassified_transaction_count: 2,
      unclassified_absolute_amount: "9007199254740993.01", open_reconciliation_cases: 1,
      incomplete_months: ["2026-01-01", "2026-02-01", "2026-03-01"],
      monthly_checks: [
        { month: "2026-01-01", source_period_complete: false, classification_complete: true, unclassified_transaction_count: 0, open_reconciliation_count: 0, complete: false },
        { month: "2026-02-01", source_period_complete: true, classification_complete: false, unclassified_transaction_count: 2, open_reconciliation_count: 0, complete: false },
        { month: "2026-03-01", source_period_complete: true, classification_complete: true, unclassified_transaction_count: 0, open_reconciliation_count: 1, complete: false },
        { month: "2026-04-01", source_period_complete: true, classification_complete: true, unclassified_transaction_count: 0, open_reconciliation_count: 0, complete: true },
      ] };
    render(<DataQualityFeature />);
    await screen.findByText("חודש אחד ללא כיסוי תקופה מלא");
    const months = screen.getByRole("heading", { name: "חודשים שדורשים השלמה" }).closest("div")!;
    const firstList = within(months).getAllByRole("list")[0];
    const rows = within(firstList).getAllByRole("listitem");
    expect(within(rows[0]).getByText("ינואר 2026")).toBeVisible();
    expect(within(rows[0]).getByRole("link", { name: "ייבוא דוח שמכסה את כל החודש" })).toHaveAttribute("href", "#familybiz-import");
    expect(within(rows[1]).queryByText(/תקופת המקור חלקית/)).not.toBeInTheDocument();
    expect(within(rows[1]).getByRole("link", { name: "מעבר לתור הסיווג" })).toHaveAttribute("href", "/classification?month=2026-02&currency=ILS");
    expect(within(rows[2]).getByRole("link", { name: "בדיקת ההתאמות" })).toHaveAttribute("href", "#reconciliation-cases");
    expect(screen.getByText(/9,007,199,254,740,993.01/)).toBeVisible();
    expect(screen.getByText(/כיסוי חשבונות המשפחה: לא ידוע/)).toBeVisible();
  });

  it("requires an explicit reconciliation decision and preserves it on an uncertain retry", async () => {
    const { ApiRequestError } = await import("@/lib/api");
    const source = { booking_date: "2026-09-19", allocation_date: "2026-09-19", amount: "-17.40", currency: "ILS", original_currency: null, original_amount: null, description: "עסקת בדיקה", movement_type: null, category: "קניות" };
    caseRows = [{ id: "qa-case", import_batch_id: "qa-batch", source_record_id: 1, reason: "Plausible non-exact candidate transactions", created_at: "2026-09-19", source, candidates: [{ ...source, id: 7, account: "חשבון בדיקה" }] }];
    const initial = apiRequest.getMockImplementation()!;
    apiRequest.mockImplementation(async (path: string, options: unknown) => {
      if (path.includes("/resolution")) throw new ApiRequestError("timeout", 0);
      return initial(path, options);
    });
    render(<DataQualityFeature />);
    await screen.findByText("עסקת בדיקה", { selector: "h3" });
    const save = screen.getByRole("button", { name: "שמירת החלטה" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "החלטה" }), { target: { value: "link_existing" } });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "עסקה מועמדת" }), { target: { value: "7" } });
    fireEvent.click(save);
    const retry = await screen.findByRole("button", { name: "שליחה חוזרת של אותה החלטה" });
    expect(screen.queryByRole("combobox", { name: "החלטה" })).not.toBeInTheDocument();
    const error = screen.getByText(/לא התקבלה תשובה. אפשר לשלוח שוב/);
    expect(error.closest("div.quality-detail")).toContainElement(screen.getByRole("heading", { name: "התאמות פתוחות" }));
    fireEvent.click(retry);
    await waitFor(() => expect(apiRequest.mock.calls.filter(([path]) => path.includes("/resolution"))).toHaveLength(2));
    const calls = apiRequest.mock.calls.filter(([path]) => path.includes("/resolution"));
    expect(calls[0][1]).toEqual(calls[1][1]);
    expect(JSON.parse(calls[0][1].body)).toEqual({ resolution: "link_existing", transaction_id: 7 });
  });

  it("explains duplicate imports before an explicit commit", async () => {
    const initial = apiRequest.getMockImplementation()!;
    apiRequest.mockImplementation(async (path: string, options: unknown) => path === "/imports/familybiz/previews"
      ? { data: { ...preview, predicted_statistics: { ...preview.predicted_statistics, duplicate_file: true, inserted: 0 } } }
      : initial(path, options));
    render(<DataQualityFeature />);
    await screen.findByRole("heading", { name: "העלאת קובץ FamilyBiz" });
    await chooseFileAndPreview();
    expect(screen.getByText(/הקובץ הזה כבר יובא/)).toBeVisible();
    expect(apiRequest.mock.calls.filter(([path]) => path.includes("/commits"))).toHaveLength(0);
  });

  it("does not report an empty reconciliation list after a failed load", async () => {
    apiRequest.mockRejectedValue(new Error("service unavailable"));
    render(<DataQualityFeature />);
    expect(await screen.findByText("ההתאמות אינן זמינות כרגע. נסו לעדכן את הנתונים.")).toBeVisible();
    expect(screen.queryByText("אין תיקי התאמה פתוחים.")).not.toBeInTheDocument();
  });

  it("ignores an older load that completes after a newer refresh", async () => {
    let resolveOld!: (value: unknown) => void;
    const oldLoad = new Promise((resolve) => { resolveOld = resolve; });
    let calls = 0;
    const initial = apiRequest.getMockImplementation()!;
    apiRequest.mockImplementation(async (path: string, options: unknown) => {
      if (path === "/dashboard/quality") {
        calls += 1;
        if (calls === 1) return oldLoad;
        return { data: { ...emptyQuality, accepted_rows: 5 } };
      }
      return initial(path, options);
    });
    render(<DataQualityFeature />);
    fireEvent.click(screen.getByRole("button", { name: "עדכון היסטוריה" }));
    await screen.findByText("מה עוד צריך להשלים?");
    await act(async () => { resolveOld({ data: emptyQuality }); });
    expect(screen.getByText("מה עוד צריך להשלים?")).toBeVisible();
    expect(screen.queryByText("מתחילים מהנתונים שלכם")).not.toBeInTheDocument();
  });

  it("shows pending history without claiming empty, then shows a successful empty response", async () => {
    let resolveHistory!: (value: unknown) => void;
    const pendingHistory = new Promise((resolve) => { resolveHistory = resolve; });
    const initial = apiRequest.getMockImplementation()!;
    apiRequest.mockImplementation(async (path: string, options: unknown) => path.startsWith("/imports/history") ? pendingHistory : initial(path, options));
    render(<DataQualityFeature />);
    fireEvent.click(screen.getByText("היסטוריית ייבוא", { selector: "strong" }).closest("summary")!);
    expect(screen.getByText("טוענים את היסטוריית הייבוא…")).toBeVisible();
    expect(screen.queryByText("אין ייבואים להצגה")).not.toBeInTheDocument();
    expect(screen.queryByText("היסטוריה תופיע לאחר השלמת ייבוא.")).not.toBeInTheDocument();
    await act(async () => { resolveHistory({ data: { items: [] }, meta: { next_cursor: null } }); });
    expect(await screen.findByText("טרם בוצע ייבוא")).toBeVisible();
    expect(screen.getByText("אין ייבואים להצגה")).toBeVisible();
    expect(screen.getByText("היסטוריה תופיע לאחר השלמת ייבוא.")).toBeVisible();
  });

  it("shows unavailable history after an initial failure without the empty-history claim", async () => {
    const initial = apiRequest.getMockImplementation()!;
    apiRequest.mockImplementation(async (path: string, options: unknown) => {
      if (path.startsWith("/imports/history")) throw new Error("history unavailable");
      return initial(path, options);
    });
    render(<DataQualityFeature />);
    await screen.findByText("ההיסטוריה אינה זמינה");
    fireEvent.click(screen.getByText("היסטוריית ייבוא", { selector: "strong" }).closest("summary")!);
    expect(screen.getByText(/לא ניתן לקבוע אם קיימים ייבואים/)).toBeVisible();
    expect(screen.queryByText("אין ייבואים להצגה")).not.toBeInTheDocument();
    expect(screen.queryByText("היסטוריה תופיע לאחר השלמת ייבוא.")).not.toBeInTheDocument();
    expect(screen.queryByText("טרם בוצע ייבוא")).not.toBeInTheDocument();
  });

  it("keeps previously loaded history with a stale-result explanation on refresh failure", async () => {
    const initial = apiRequest.getMockImplementation()!;
    let fail = false;
    const stats = { total_records: 1, inserted: 1, unchanged: 0, updated: 0, rejected: 0, ambiguous: 0, unresolved: 0, duplicate_file: false, non_ils_records: 0 };
    apiRequest.mockImplementation(async (path: string, options: unknown) => {
      if (path.startsWith("/imports/history")) {
        if (fail) throw new Error("refresh failed");
        return { data: { items: [{ id: "saved-batch", source_file_id: 1, parser_version: "v2", baseline_batch_id: null, report_start: "2026-09-01", report_end: "2026-09-30", max_transaction_date: "2026-09-19", freshness_days: 0, status: "committed", statistics: stats, issue_codes: [], error_code: null, created_at: "2026-09-20" }] }, meta: { next_cursor: null } };
      }
      return initial(path, options);
    });
    render(<DataQualityFeature />);
    await screen.findByText("ייבוא אחרון: 20/09/2026 · הושלם");
    fireEvent.click(screen.getByText("היסטוריית ייבוא", { selector: "strong" }).closest("summary")!);
    expect(screen.getByRole("cell", { name: "20/09/2026" })).toBeVisible();
    fail = true;
    fireEvent.click(screen.getByRole("button", { name: "עדכון היסטוריה" }));
    expect(await screen.findByText(/עדכון ההיסטוריה נכשל. מוצגות תוצאות מהטעינה הקודמת/)).toBeVisible();
    expect(screen.getByRole("cell", { name: "20/09/2026" })).toBeVisible();
    expect(screen.queryByText("אין ייבואים להצגה")).not.toBeInTheDocument();
  });

  it("does not present a previously empty snapshot as a fresh empty result after refresh failure", async () => {
    const initial = apiRequest.getMockImplementation()!;
    let fail = false;
    apiRequest.mockImplementation(async (path: string, options: unknown) => {
      if (path.startsWith("/imports/history") && fail) throw new Error("refresh failed");
      return initial(path, options);
    });
    render(<DataQualityFeature />);
    await screen.findByText("טרם בוצע ייבוא");
    fireEvent.click(screen.getByText("היסטוריית ייבוא", { selector: "strong" }).closest("summary")!);
    fail = true;
    fireEvent.click(screen.getByRole("button", { name: "עדכון היסטוריה" }));
    expect(await screen.findByText("לא נמצאו ייבואים בטעינה הקודמת")).toBeVisible();
    expect(screen.getByText("לא ניתן לקבוע אם נוספו ייבואים מאז הטעינה הקודמת.")).toBeVisible();
    expect(screen.queryByText("אין ייבואים להצגה")).not.toBeInTheDocument();
    expect(screen.queryByText("טרם בוצע ייבוא")).not.toBeInTheDocument();
  });

});
