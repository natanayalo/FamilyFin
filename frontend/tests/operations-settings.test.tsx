import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OperationsFeature } from "@/features/operations/operations-feature";
import { SettingsFeature } from "@/features/settings/settings-feature";
import type { OperationsSnapshot } from "@/features/operations/api";
import type { SettingsOverview } from "@/features/settings/api";
import * as operationsApi from "@/features/operations/api";
import * as settingsApi from "@/features/settings/api";

vi.mock("@/features/insight-preferences/insight-preferences-feature", () => ({
  InsightPreferencesFeature: () => <section aria-label="תובנות" />,
}));
vi.mock("@/features/operations/api", () => ({
  getAutomationStatus: vi.fn(), getAutomationRuns: vi.fn(), startAutomation: vi.fn(),
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
    vi.mocked(operationsApi.getAutomationStatus).mockResolvedValue({ data: {
      inbox: { inbox_file_count: 2, review_file_count: 1 },
      operations: blockedOperations,
      latest_run: null,
    } });
    vi.mocked(operationsApi.getAutomationRuns).mockResolvedValue({ data: { items: [] } });
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

  it("saves per-account display preferences and revokes only another session", async () => {
    render(<SettingsFeature />);
    await screen.findByRole("heading", { name: "העדפות תצוגה" });
    expect(screen.getByText("החיבורים הפעילים שלך")).toBeVisible();
    expect(screen.queryByText("private-session-id")).not.toBeInTheDocument();
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
});
