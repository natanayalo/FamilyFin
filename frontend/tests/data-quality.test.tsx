import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DataQualityFeature } from "@/features/data-quality/data-quality-feature";
import type { FamilyBizPreview } from "@/features/data-quality/types";

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

function mockInitialLoads() {
  apiRequest.mockImplementation(async (path: string) => {
    if (path === "/dashboard/quality") return { data: emptyQuality };
    if (path.startsWith("/imports/history")) return { data: { items: [] }, meta: { next_cursor: null } };
    if (path.startsWith("/reconciliation/cases")) return { data: { items: [] }, meta: { next_cursor: null } };
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
      if (path === "/dashboard/quality") return { data: emptyQuality };
      if (path.startsWith("/imports/history")) return { data: { items: [] }, meta: { next_cursor: null } };
      if (path.startsWith("/reconciliation/cases")) return { data: { items: [] }, meta: { next_cursor: null } };
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
});
