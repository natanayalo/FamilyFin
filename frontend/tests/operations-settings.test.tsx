import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OperationsFeature } from "@/features/operations/operations-feature";
import { SettingsFeature } from "@/features/settings/settings-feature";
import type { OperationsSnapshot } from "@/features/operations/api";
import type { SettingsOverview } from "@/features/settings/api";
import * as operationsApi from "@/features/operations/api";
import * as settingsApi from "@/features/settings/api";
import { rememberDashboardFilters, resetDashboardFilters } from "@/features/dashboard/filter-state";
import { useDashboardReport } from "@/features/dashboard/shared";
import type { DashboardFilters } from "@/features/dashboard/types";
import { ApiRequestError } from "@/lib/api";

vi.mock("@/features/insight-preferences/insight-preferences-feature", () => ({
  InsightPreferencesFeature: () => <section aria-label="תובנות" />,
}));
vi.mock("@/features/operations/api", () => ({
  getAutomationStatus: vi.fn(), getAutomationRuns: vi.fn(), startAutomation: vi.fn(),
  getAttentionFiles: vi.fn(), preflightAttentionFile: vi.fn(), commitAttentionFile: vi.fn(),
}));
vi.mock("@/features/settings/api", () => ({
  getSettings: vi.fn(), getSessions: vi.fn(), saveAppPreferences: vi.fn(), revokeSession: vi.fn(),
}));

const blockedOperations: OperationsSnapshot = {
  audit: { passed: true, checks: [{ name: "sqlite_integrity", passed: true, issue_codes: [] }] },
  backup: { configured: false, status: "not_configured", last_verified_at: null },
  run_now_allowed: false,
  run_now_block_reason: "AUTOMATION_BACKUP_NOT_CONFIGURED",
  warnings: ["AUTOMATION_BACKUP_NOT_CONFIGURED"],
};
const settingsValue: SettingsOverview = {
  preferences: { default_currency: "ILS", default_months: 12, updated_at: null },
  freshness: {
    familybiz: { last_import_at: "2026-09-20T12:00:00Z", latest_transaction_date: "2026-09-19", age_days: 8 },
    planning: { last_import_at: null, age_days: null },
    net_worth: { last_import_at: null, age_days: null },
  },
  operations: {
    audit: { passed: true, checks: [] },
    backup: { configured: true, status: "verified", last_verified_at: "20260920T120000Z" },
    run_now_allowed: true, run_now_block_reason: null, warnings: [],
  },
  operational_warnings: [],
  household: { member_count: 2, members: ["Sam", "Lee"], permissions: "equal" },
};

describe("Operations and settings workflows", () => {
  beforeEach(() => {
    resetDashboardFilters();
    vi.mocked(operationsApi.getAutomationStatus).mockResolvedValue({ data: {
      inbox: { inbox_file_count: 2, review_file_count: 1 },
      operations: blockedOperations,
      latest_run: null,
    } });
    vi.mocked(operationsApi.getAutomationRuns).mockResolvedValue({ data: { items: [] } });
    vi.mocked(operationsApi.getAttentionFiles).mockResolvedValue({ data: { items: [] } });
    vi.mocked(operationsApi.preflightAttentionFile).mockResolvedValue({ data: {
      file_id: "f".repeat(64), file_sha256: "a".repeat(64), action: "needs_review",
      duplicate_file: false, ambiguous_count: 1, reconciliation_count: 1,
      candidate_count: 2, warning_count: 1, rejected_count: 0,
      issue_counts: {}, predicted_statistics: { inserted: 0, updated: 0, unchanged: 0 },
    } });
    vi.mocked(operationsApi.commitAttentionFile).mockResolvedValue({ data: {
      batch_id: "batch-1", status: "needs_review",
      statistics: { inserted: 0, updated: 0, unchanged: 0 },
    } });
    vi.mocked(operationsApi.startAutomation).mockResolvedValue({ data: {
      id: "run-1", status: "dry_run", started_at: "2026-09-28T12:00:00Z", finished_at: "2026-09-28T12:00:01Z",
      dry_run: true, audit_passed: true, backup_created: false, counts: { ready: 2 }, issue_codes: [], items: [],
    } });
    vi.mocked(settingsApi.getSettings).mockResolvedValue({ data: settingsValue });
    vi.mocked(settingsApi.getSessions).mockResolvedValue({ data: { items: [
      { id: "private-session-id", created_at: "2026-09-28T12:00:00Z", expires_at: "2026-09-28T20:00:00Z", current: true },
      { id: "private-other-session-id", created_at: "2026-09-27T12:00:00Z", expires_at: "2026-09-28T20:00:00Z", current: false },
    ] } });
    vi.mocked(settingsApi.saveAppPreferences).mockResolvedValue({ data: {
      default_currency: "USD", default_months: 24, updated_at: "2026-09-28T12:00:00Z",
    } });
    vi.mocked(settingsApi.revokeSession).mockResolvedValue({ data: undefined });
  });

  it("replaces failed Settings loading with a retry that can recover", async () => {
    vi.mocked(settingsApi.getSettings).mockRejectedValueOnce(new Error("Unavailable"));
    render(<SettingsFeature />);
    expect(screen.getByText("טוענים הגדרות מהשרת…")).toBeVisible();
    await screen.findByText("לא ניתן לטעון את ההגדרות.");
    expect(screen.queryByText("טוענים הגדרות מהשרת…")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "לנסות שוב" }));
    expect(await screen.findByLabelText("מטבע ברירת מחדל")).toHaveValue("ILS");
    expect(screen.queryByText("לא ניתן לטעון את ההגדרות.")).not.toBeInTheDocument();
  });

  it("keeps Run Now visibly blocked without a backup destination while allowing dry-run", async () => {
    render(<OperationsFeature />);
    await screen.findByText("ההפעלה חסומה עד להגדרת יעד גיבוי. הריצה תיעצר גם אם יצירת הגיבוי תיכשל.");
    expect(screen.getByRole("button", { name: "הפעלה עכשיו" })).toBeDisabled();
    const dryRun = screen.getByRole("button", { name: "בדיקת תיבה ללא שינויים" });
    expect(dryRun).toBeEnabled();
    fireEvent.click(dryRun);
    await screen.findByText(/לא נשמרו נתונים ולא הועברו קבצים/);
    expect(operationsApi.startAutomation).toHaveBeenCalledWith(true);
  });

  it("keeps a rejected run visible through automatic/manual refresh and clears it only for a new explicit run", async () => {
    vi.mocked(operationsApi.startAutomation).mockRejectedValueOnce(new Error("Lost response"));
    render(<OperationsFeature />);
    const dryRun = await screen.findByRole("button", { name: "בדיקת תיבה ללא שינויים" });
    fireEvent.click(dryRun);
    await waitFor(() => expect(operationsApi.getAutomationStatus).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(dryRun).toBeEnabled());
    expect(screen.getByRole("alert")).toHaveTextContent("לא ניתן לאשר את תוצאת הבדיקה");
    expect(operationsApi.startAutomation).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /^רענון$/ }));
    await waitFor(() => expect(operationsApi.getAutomationStatus).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(dryRun).toBeEnabled());
    expect(screen.getByRole("alert")).toHaveTextContent("בדקו את היסטוריית הריצות");
    expect(screen.queryByText(/היסטוריית הריצות עשויה להיות לא מעודכנת/)).not.toBeInTheDocument();
    expect(operationsApi.startAutomation).toHaveBeenCalledTimes(1);
    fireEvent.click(dryRun);
    await screen.findByText(/הבדיקה הסתיימה/);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(operationsApi.startAutomation).toHaveBeenCalledTimes(2);
  });

  it.each([
    [400, "ההפעלה לא אושרה", false],
    [500, "לא ניתן לאשר את תוצאת ההפעלה", true],
  ] as const)("retains action feedback for HTTP %s while fresh status independently controls readiness", async (httpStatus, guidance, uncertain) => {
    vi.mocked(operationsApi.getAutomationStatus).mockResolvedValue({ data: {
      inbox: { inbox_file_count: 1, review_file_count: 0 }, operations: settingsValue.operations, latest_run: null,
    } });
    vi.mocked(operationsApi.startAutomation).mockRejectedValueOnce(new ApiRequestError("Synthetic run error", httpStatus));
    render(<OperationsFeature />);
    const runNow = await screen.findByRole("button", { name: "הפעלה עכשיו" });
    fireEvent.click(runNow);
    await waitFor(() => expect(operationsApi.getAutomationStatus).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(runNow).toBeEnabled());
    expect(screen.getByRole("alert")).toHaveTextContent(guidance);
    expect(screen.getByRole("alert").textContent?.includes("ייתכן שהפעולה הושלמה")).toBe(uncertain);
    expect(operationsApi.startAutomation).toHaveBeenCalledExactlyOnceWith(false);
    vi.mocked(operationsApi.getAutomationStatus).mockRejectedValueOnce(new Error("Read failed"));
    fireEvent.click(screen.getByRole("button", { name: /^רענון$/ }));
    await screen.findByText("לא ניתן לטעון את מצב התהליכים.");
    expect(screen.getByText(new RegExp(guidance))).toBeVisible();
    expect(runNow).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /^רענון$/ }));
    await waitFor(() => expect(runNow).toBeEnabled());
    expect(screen.getByRole("alert")).toHaveTextContent(guidance);
    expect(operationsApi.startAutomation).toHaveBeenCalledTimes(1);
  });

  it("does not claim empty files or history before their initial requests finish", async () => {
    let resolveFiles!: (value: Awaited<ReturnType<typeof operationsApi.getAttentionFiles>>) => void;
    let resolveRuns!: (value: Awaited<ReturnType<typeof operationsApi.getAutomationRuns>>) => void;
    vi.mocked(operationsApi.getAttentionFiles).mockReturnValueOnce(new Promise((resolve) => { resolveFiles = resolve; }));
    vi.mocked(operationsApi.getAutomationRuns).mockReturnValueOnce(new Promise((resolve) => { resolveRuns = resolve; }));
    render(<OperationsFeature />);
    expect(screen.queryByText("אין קבצים שממתינים לבדיקה.")).not.toBeInTheDocument();
    expect(screen.queryByText("אין ריצות שמורות.")).not.toBeInTheDocument();
    resolveFiles({ data: { items: [] } });
    resolveRuns({ data: { items: [] } });
    expect(await screen.findByText("אין קבצים שממתינים לבדיקה.")).toBeVisible();
    expect(await screen.findByText("אין ריצות שמורות.")).toBeVisible();
  });

  it("distinguishes initial failures from loading or empty results", async () => {
    vi.mocked(operationsApi.getAutomationStatus).mockRejectedValueOnce(new Error("Unavailable"));
    vi.mocked(operationsApi.getAttentionFiles).mockRejectedValueOnce(new Error("Unavailable"));
    render(<OperationsFeature />);
    await screen.findByText("לא ניתן לטעון את מצב התהליכים.");
    expect(screen.queryByText("טוענים נתונים מהשרת…")).not.toBeInTheDocument();
    expect(screen.queryByText("אין קבצים שממתינים לבדיקה.")).not.toBeInTheDocument();
    expect(screen.queryByText("אין ריצות שמורות.")).not.toBeInTheDocument();
    expect(screen.getByText("היסטוריית הריצות אינה זמינה. נסו לרענן את מצב התהליכים.")).toBeVisible();
  });

  it("labels prior empty snapshots as stale after refresh failure", async () => {
    render(<OperationsFeature />);
    await screen.findByText("אין ריצות שמורות.");
    await screen.findByText("אין קבצים שממתינים לבדיקה.");
    vi.mocked(operationsApi.getAutomationStatus).mockRejectedValueOnce(new Error("Unavailable"));
    vi.mocked(operationsApi.getAttentionFiles).mockRejectedValueOnce(new Error("Unavailable"));
    fireEvent.click(screen.getByRole("button", { name: /^רענון$/ }));
    fireEvent.click(screen.getByRole("button", { name: "רענון קבצים" }));
    await screen.findByText(/מוצגות תוצאות קודמות; היסטוריית הריצות/);
    await screen.findByText(/מוצגות תוצאות קודמות; הרשימה/);
    expect(screen.queryByText("אין ריצות שמורות.")).not.toBeInTheDocument();
    expect(screen.queryByText("אין קבצים שממתינים לבדיקה.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "בדיקת תיבה ללא שינויים" })).toBeDisabled();
  });

  it("allows manual run only when status reports audit and backup readiness", async () => {
    vi.mocked(operationsApi.getAutomationStatus).mockResolvedValue({ data: {
      inbox: { inbox_file_count: 1, review_file_count: 0 },
      operations: { ...blockedOperations, backup: { configured: true, status: "verified", last_verified_at: null }, run_now_allowed: true, run_now_block_reason: null, warnings: [] },
      latest_run: null,
    } });
    vi.mocked(operationsApi.startAutomation).mockResolvedValue({ data: {
      id: "run-2", status: "completed", started_at: "2026-09-28T12:00:00Z", finished_at: "2026-09-28T12:00:01Z",
      dry_run: false, audit_passed: true, backup_created: true, counts: { committed: 1 }, issue_codes: [], items: [],
    } });
    render(<OperationsFeature />);
    const runNow = await screen.findByRole("button", { name: "הפעלה עכשיו" });
    expect(runNow).toBeEnabled();
    fireEvent.click(runNow);
    await screen.findByText(/לאחר יצירת גיבוי מאומת/);
    expect(operationsApi.startAutomation).toHaveBeenCalledWith(false);
  });

  it("requires a preflight and explicit confirmation before attention commit", async () => {
    vi.mocked(operationsApi.getAttentionFiles).mockResolvedValue({ data: { items: [
      { id: "f".repeat(64), size_bytes: 2048, modified_at: "2026-09-28T12:00:00Z" },
    ] } });
    vi.mocked(operationsApi.getAutomationStatus).mockResolvedValue({ data: {
      inbox: { inbox_file_count: 0, review_file_count: 1 },
      operations: { ...blockedOperations, backup: { configured: true, status: "verified", last_verified_at: null }, run_now_allowed: true, run_now_block_reason: null, warnings: [] },
      latest_run: null,
    } });
    render(<OperationsFeature />);
    fireEvent.click(await screen.findByRole("button", { name: "בדיקה מוקדמת" }));
    const commit = await screen.findByRole("button", { name: "אישור קובץ לבדיקה" });
    expect(commit).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /אני מאשר\/ת/ }));
    expect(commit).toBeEnabled();
    fireEvent.click(commit);
    await waitFor(() => expect(operationsApi.commitAttentionFile).toHaveBeenCalledWith("f".repeat(64), "a".repeat(64)));
    expect(screen.getByText(/הטיפול בקובץ הושלם/)).toBeVisible();
  });

  it("saves per-account display preferences and revokes only another session", async () => {
    render(<SettingsFeature />);
    await screen.findByRole("heading", { name: "העדפות תצוגה" });
    expect(screen.getByText("החיבורים הפעילים שלך")).toBeVisible();
    expect(screen.queryByText("private-session-id")).not.toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.textContent === "תאריך עסקה אחרון: 19 בספטמבר 2026")).toBeVisible();
    expect(screen.getAllByText((_, element) => element?.tagName === "SPAN" && Boolean(element.textContent?.startsWith("ייבוא: ")))[0].textContent).toMatch(/\d{1,2}:\d{2}/);
    fireEvent.change(screen.getByLabelText("מטבע ברירת מחדל"), { target: { value: "USD" } });
    fireEvent.change(screen.getByLabelText("תקופת ברירת מחדל"), { target: { value: "24" } });
    fireEvent.click(screen.getByRole("button", { name: "שמירת העדפות" }));
    await screen.findByText("העדפות התצוגה נשמרו לחשבון שלך.");
    expect(settingsApi.saveAppPreferences).toHaveBeenCalledWith({ default_currency: "USD", default_months: 24 });

    fireEvent.click(screen.getByRole("button", { name: "ביטול חיבור" }));
    await waitFor(() => expect(settingsApi.revokeSession).toHaveBeenCalledWith("private-other-session-id"));
    expect(screen.getByText("המכשיר הנוכחי")).toBeVisible();
    expect(screen.getByText("חיבור פעיל")).toBeVisible();
  });

  it("uses the newly saved report currency after navigating away from settings", async () => {
    rememberDashboardFilters({ start_month: "2026-08-01", end_month: "2026-09-01", currency: "ILS" });
    vi.mocked(settingsApi.getSettings).mockResolvedValueOnce({ data: settingsValue }).mockResolvedValue({ data: { ...settingsValue, preferences: { ...settingsValue.preferences, default_currency: "USD" } } });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "https://testserver");
      return new Response(JSON.stringify({ data: { filters: { start_month: "2026-01-01", end_month: "2026-09-01", currency: url.searchParams.get("currency") ?? "USD" } } }), { headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<SettingsFeature />);
    fireEvent.change(await screen.findByLabelText("מטבע ברירת מחדל"), { target: { value: "USD" } });
    fireEvent.click(screen.getByRole("button", { name: "שמירת העדפות" }));
    await screen.findByText("העדפות התצוגה נשמרו לחשבון שלך.");
    view.unmount();
    function Report() {
      const report = useDashboardReport<{ filters: DashboardFilters }>("/dashboard/expenses");
      return <><p>{report.data?.filters.currency}</p><button disabled={report.loading || !report.draft.start_month} onClick={() => report.apply({ ...report.draft, start_month: "2026-01-01", end_month: "2026-09-01" })}>עדכון תקופה</button></>;
    }
    render(<Report />);
    expect(await screen.findByText("USD")).toBeVisible();
    expect(String(fetchMock.mock.calls[0][0])).not.toContain("currency=ILS");
    await waitFor(() => expect(screen.getByRole("button", { name: "עדכון תקופה" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "עדכון תקופה" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("currency=USD"))).toBe(true));
  });
});
