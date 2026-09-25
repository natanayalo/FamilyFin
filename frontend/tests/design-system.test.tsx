import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/async-state";
import { FormErrorSummary, TextField } from "@/components/ui/form-patterns";
import { ResponsiveDataTable } from "@/components/ui/responsive-data-table";

describe("shared design-system states", () => {
  it("exposes loading and empty states accessibly without sample values", () => {
    render(<><LoadingState label="טוענים נתונים" /><EmptyState title="אין פריטים" description="לא נמצאו פריטים להצגה." /></>);
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("heading", { name: "אין פריטים" })).toBeVisible();
    expect(screen.queryByText(/₪|ש״ח|balance/i)).not.toBeInTheDocument();
  });

  it("associates field validation and summary links with the input", () => {
    render(<><FormErrorSummary errors={[{ fieldId: "scenario-name", fieldLabel: "שם", message: "יש להזין שם." }]} /><TextField id="scenario-name" label="שם" error="יש להזין שם." /></>);
    expect(document.querySelector(".form-error-summary")).toHaveTextContent("יש להזין שם.");
    expect(screen.getByRole("link", { name: "שם" })).toHaveAttribute("href", "#scenario-name");
    expect(screen.getByLabelText("שם")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("שם")).toHaveAttribute("aria-describedby", "scenario-name-error");
  });

  it("provides a safe, actionable error state", () => {
    render(<ErrorState description="השירות אינו זמין." requestId="req-test" onRetry={() => undefined} />);
    expect(document.querySelector(".error-state")).toHaveTextContent("req-test");
    expect(screen.getByRole("button", { name: "לנסות שוב" })).toBeEnabled();
  });
});

describe("responsive data table pattern", () => {
  it("keeps semantic headers and per-cell labels for narrow card layouts", () => {
    const rows = [{ name: "Synthetic item", state: "Ready" }];
    render(<ResponsiveDataTable caption="רשימת פריטים" rows={rows} getRowKey={(row) => row.name} columns={[
      { key: "name", label: "שם פריט", render: (row) => row.name },
      { key: "state", label: "מצב", render: (row) => row.state },
    ]} />);
    expect(screen.getByRole("table", { name: "רשימת פריטים" })).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "שם פריט" })).toBeVisible();
    expect(screen.getByText("Synthetic item").closest("td")).toHaveAttribute("data-label", "שם פריט");
  });

  it("shows a labeled empty state instead of an empty table", () => {
    render(<ResponsiveDataTable caption="רשימת פריטים" rows={[]} getRowKey={() => "unused"} columns={[]} emptyTitle="אין רשומות" />);
    expect(screen.getByRole("heading", { name: "אין רשומות" })).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
