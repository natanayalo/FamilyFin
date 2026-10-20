import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ForecastsFeature } from "@/features/forecasts/ForecastsFeature";

it("provides a route to planning when a forecast needs its first budget", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify({ data: [] }), { status: 200 }));
  render(<ForecastsFeature />);
  expect(await screen.findByRole("link", { name: "יצירת תקציב" })).toHaveAttribute("href", "/planning");
  expect(screen.getByRole("button", { name: "תחזית חדשה" })).toBeDisabled();
});
