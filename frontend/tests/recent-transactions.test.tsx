import { render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { RecentTransactions } from "@/features/dashboard/recent-transactions";

const filters = { start_month: "2026-09-01", end_month: "2026-09-01", currency: "USD" };
it("shows scoped recent transactions with effective amounts and a route to all transactions", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ data: [
    { transaction_id: 12, booking_date: "2026-09-20", description: "Synthetic purchase", amount: "-12.50", currency: "USD", analysis_category: "food", source_category: "source food", effective_classification: "consumption" },
    { transaction_id: 11, booking_date: "2026-09-19", description: "Synthetic unknown", amount: "50", currency: "USD", analysis_category: null, source_category: "", effective_classification: "unclassified" },
  ] }), { status: 200 }));
  render(<RecentTransactions filters={filters} />);
  expect(await screen.findByText("Synthetic purchase")).toBeVisible();
  expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("start_month=2026-09&end_month=2026-09&currency=USD"), expect.anything());
  expect(screen.getByText("\u2067\u2066-12.50\u2069 $\u2069")).toBeVisible();
  expect(screen.getByText("ממתינה לסיווג")).toBeVisible();
  expect(screen.getByRole("link", { name: "כל עסקאות החודש" })).toHaveAttribute("href", "/classification?month=2026-09&currency=USD&include_resolved=true");
  const rows = within(screen.getByRole("table")).getAllByRole("row");
  expect(rows).toHaveLength(3);
  expect(rows[1]).toHaveTextContent("Synthetic purchase");
});

it("shows a useful empty state without fabricated transactions", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ data: [] }), { status: 200 }));
  render(<RecentTransactions filters={filters} />);
  expect(await screen.findByText("אין עסקאות להצגה בחודש זה.")).toBeVisible();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
