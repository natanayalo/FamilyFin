import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DashboardFilterForm, type FilterDraft } from "@/features/dashboard/shared";
import type { DashboardFilters } from "@/features/dashboard/types";

function FilterHarness({ onApply, initial = { start_month: "2025-10", end_month: "2026-09", currency: "USD" } }: {
  onApply: (value: DashboardFilters) => void;
  initial?: FilterDraft;
}) {
  const [draft, setDraft] = useState(initial);
  return <DashboardFilterForm value={draft} onChange={setDraft} onApply={onApply} loading={false} />;
}

describe("Hebrew report period controls", () => {
  it("uses the shared month calendar, preserves the saved currency, and submits only on apply", async () => {
    const apply = vi.fn();
    render(<FilterHarness onApply={apply} />);
    expect(screen.getByRole("button", { name: "חודש התחלה" })).toHaveTextContent("אוקטובר 2025");
    expect(screen.getByRole("button", { name: "חודש סיום" })).toHaveTextContent("ספטמבר 2026");
    expect(screen.queryByLabelText("מטבע")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "חודש התחלה" }));
    fireEvent.click(await screen.findByRole("button", { name: "השנה הקודמת" }));
    fireEvent.click(screen.getByRole("button", { name: "דצמבר 2024" }));
    expect(apply).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "עדכון תצוגה" }));
    expect(apply).toHaveBeenCalledWith({ start_month: "2024-12-01", end_month: "2026-09-01", currency: "USD" });
  });

  it("rejects reversed ranges without applying", async () => {
    const apply = vi.fn();
    render(<FilterHarness onApply={apply} />);
    fireEvent.click(screen.getByRole("button", { name: "חודש התחלה" }));
    fireEvent.click(await screen.findByRole("button", { name: "השנה הבאה" }));
    fireEvent.click(screen.getByRole("button", { name: "השנה הבאה" }));
    fireEvent.click(screen.getByRole("button", { name: "ינואר 2027" }));
    fireEvent.click(screen.getByRole("button", { name: "עדכון תצוגה" }));
    expect(screen.getByRole("alert")).toHaveTextContent("חודש ההתחלה צריך להיות לפני חודש הסיום.");
    expect(apply).not.toHaveBeenCalled();
  });

  it("focuses an unset boundary when applying an incomplete range", () => {
    const apply = vi.fn();
    render(<FilterHarness onApply={apply} initial={{ start_month: "", end_month: "2026-09", currency: "USD" }} />);
    fireEvent.click(screen.getByRole("button", { name: "עדכון תצוגה" }));
    expect(screen.getByRole("alert")).toBeVisible();
    expect(screen.getByRole("button", { name: "חודש התחלה" })).toHaveFocus();
    expect(apply).not.toHaveBeenCalled();
  });
});
