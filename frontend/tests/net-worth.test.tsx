import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "@/lib/api";
import { getAccountHistory, getAccounts, getRevisions, getSummary, getSnapshots, getTrend } from "@/features/net-worth/api";
import { NetWorthPage } from "@/features/net-worth/net-worth-page";

vi.mock("@/lib/api", () => ({
  apiRequest: vi.fn(),
  ApiRequestError: class ApiRequestError extends Error {
    status: number;
    apiError?: { code?: string; request_id?: string; message?: string };
    constructor(message: string, status: number, apiError?: { code?: string; request_id?: string; message?: string }) {
      super(message);
      this.status = status;
      this.apiError = apiError;
    }
  },
}));

vi.mock("@/features/net-worth/api", () => ({
  getAccountHistory: vi.fn(),
  getAccounts: vi.fn(),
  getRevisions: vi.fn(),
  getSummary: vi.fn(),
  getSnapshots: vi.fn(),
  getTrend: vi.fn(),
  postCsvPreview: vi.fn(),
}));

const account = {
  id: "account-id", account_key: "cash", display_name: "מזומן", side: "asset" as const,
  category: "cash", liquidity: "liquid" as const, owner_label: null, active_from: "2020-01-01",
  active_to: null, stale_after_days: 45, created_at: null, updated_at: "2026-09-25T10:00:00Z",
};
const snapshot = {
  snapshot_id: "snapshot-id", snapshot_date: "2026-08-31", current_revision_number: 1,
  archived: false, created_at: null, updated_at: null,
};
const revision = {
  snapshot_id: "snapshot-id", revision_id: "revision-id", revision_number: 1, snapshot_date: "2026-08-31",
  origin: "manual" as const, notes: "", quality_issues: [], quality_acknowledged: false, content_hash: "hash-1",
  active_account_keys: ["cash"], source_file_id: null,
  balances: [{
    account_key: "cash", amount_ils: "9007199254740993.12345", valuation_date: "2026-08-31",
    notes: "", account_name: "מזומן", side: "asset" as const, category: "cash", liquidity: "liquid" as const,
    owner_label: null, stale_after_days: 45, snapshot_date: "2026-08-31", stale: false,
  }],
  created_at: null, stale_account_keys: [], complete: true,
};

describe("Net Worth feature", () => {
  beforeEach(() => {
    vi.mocked(getAccounts).mockResolvedValue([account]);
    vi.mocked(getSnapshots).mockResolvedValue([snapshot]);
    vi.mocked(getRevisions).mockResolvedValue([revision]);
    vi.mocked(getSummary).mockResolvedValue({
      revision_id: "revision-id", snapshot_id: "snapshot-id", snapshot_date: "2026-08-31", revision_number: 1,
      total_assets: "9007199254740993.12345", total_liabilities: "0", net_worth: "9007199254740993.12345",
      liquid_assets: "9007199254740993.12345", restricted_assets: "0", illiquid_assets: "0",
      stale_account_keys: [], snapshot_freshness_days: 25, by_category: { cash: "9007199254740993.12345" },
      by_liquidity: { liquid: "9007199254740993.12345" }, by_owner: { Shared: "9007199254740993.12345" },
      by_account: { cash: "9007199254740993.12345" },
    });
    vi.mocked(getTrend).mockResolvedValue([{
      snapshot_date: "2026-08-31", revision_id: "revision-id", total_assets: "9007199254740993.12345",
      total_liabilities: "0", net_worth: "9007199254740993.12345", liquid_assets: "9007199254740993.12345",
      restricted_assets: "0", illiquid_assets: "0",
    }]);
    vi.mocked(getAccountHistory).mockResolvedValue([]);
    vi.mocked(apiRequest).mockResolvedValue({ data: {} });
  });

  it("shows service totals, observed trend, and defers the forecast chooser", async () => {
    render(<NetWorthPage />);
    await screen.findByRole("heading", { name: "רשימת חשבונות" });
    expect(document.body.textContent).toContain("9,007,199,254,740,993.12345 ₪");
    expect(screen.getByRole("heading", { name: "רשימת חשבונות" })).toBeVisible();
    expect(screen.getByText("מגמת הון שנמדד")).toBeVisible();
    expect(screen.getByText(/נקודת הקצה בצד השרת זמינה/)).toBeVisible();
    expect(screen.getByText("ממתין למודול התחזית")).toBeVisible();
  });

  it("sends snapshot amounts as exact decimal strings with the current expected revision", async () => {
    render(<NetWorthPage />);
    await screen.findByRole("heading", { name: "רשימת חשבונות" });
    fireEvent.click(screen.getAllByRole("button", { name: "שמירת גרסה חדשה" }).at(-1)!);
    const amount = await screen.findByLabelText("יתרה: מזומן");
    fireEvent.change(amount, { target: { value: "12345678901234567890.123456" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /מאשר\/ת את אזהרות איכות/ }));
    fireEvent.click(screen.getAllByRole("button", { name: "שמירת גרסה חדשה" }).at(-1)!);

    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(
      "/net-worth/snapshots/snapshot-id/revisions",
      expect.objectContaining({ method: "POST" }),
    ));
    const body = JSON.parse(vi.mocked(apiRequest).mock.calls[0][1]?.body as string);
    expect(body.expected_revision_number).toBe(1);
    expect(body.balances[0].amount_ils).toBe("12345678901234567890.123456");
    expect(typeof body.balances[0].amount_ils).toBe("string");
  });

  it("sends the account version from the loaded row when editing account metadata", async () => {
    render(<NetWorthPage />);
    await screen.findByRole("heading", { name: "רשימת חשבונות" });
    fireEvent.click(screen.getByRole("button", { name: "עריכה" }));
    fireEvent.change(screen.getByLabelText("שם החשבון"), { target: { value: "יתרת מזומן" } });
    fireEvent.click(screen.getByRole("button", { name: "שמירת חשבון" }));

    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(
      "/net-worth/accounts/cash",
      expect.objectContaining({ method: "PUT" }),
    ));
    const body = JSON.parse(vi.mocked(apiRequest).mock.calls[0][1]?.body as string);
    expect(body.expected_updated_at).toBe(account.updated_at);
  });

  it.each([
    { active_to: null, button: "סגירה", field: "closed_on" },
    { active_to: "2026-09-01", button: "הפעלה מחדש", field: "active_from" },
  ])("sends the account version when account lifecycle changes", async ({ active_to, button, field }) => {
    vi.mocked(getAccounts).mockResolvedValue([{ ...account, active_to }]);
    render(<NetWorthPage />);
    await screen.findByRole("heading", { name: "רשימת חשבונות" });
    fireEvent.click(screen.getByRole("button", { name: button }));

    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(
      `/net-worth/accounts/cash/${field === "closed_on" ? "close" : "reactivate"}`,
      expect.objectContaining({ method: "POST" }),
    ));
    const body = JSON.parse(vi.mocked(apiRequest).mock.calls[0][1]?.body as string);
    expect(body[field]).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(body.expected_updated_at).toBe(account.updated_at);
  });
});
