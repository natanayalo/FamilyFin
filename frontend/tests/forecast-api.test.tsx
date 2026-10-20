import { expect, it, vi } from "vitest";
import { createForecast, previewForecast, saveForecastRevision } from "@/features/forecasts/api";
import type { ForecastInputPayload, ForecastRole } from "@/features/forecasts/types";

it.each(["preview", "create", "save"] as const)("%s strips read-only pool metadata while preserving exact balances and quality acknowledgements", async (operation) => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ data: {} }), { status: 200 }));
  const pool = { pool_id: "read-only-pool-id", name: "חיסכון", pool_type: "investment" as const,
    opening_balance: "9007199254740993.01", as_of_date: "2026-09-01",
    net_worth_account_key: "account", net_worth_snapshot_revision_id: "snapshot-revision",
    source_valuation_date: "2026-08-31", source_stale: true, source_quality_acknowledged: true };
  const body: ForecastInputPayload = { scenario_id: "s", source_revision_number: 2, starting_pools: [pool],
    cases: ["conservative", "baseline", "optimistic"].map((role) => ({ role: role as ForecastRole, annual_return_rate: "0.04", routes: [{ source_item_id: "saving", pool_name: "חיסכון" }], sweep_enabled: false, sweep_pool_name: null, adjustments: [], events: [], confirmed: true })),
    notes: "נשמר במפורש", provisional_acknowledged: true };
  if (operation === "preview") await previewForecast(body);
  else if (operation === "create") await createForecast({ ...body, name: "תחזית" });
  else await saveForecastRevision("forecast", { starting_pools: body.starting_pools, cases: body.cases, notes: body.notes, provisional_acknowledged: body.provisional_acknowledged, expected_revision_number: 3 });
  const sent = JSON.parse(fetchMock.mock.calls.at(-1)![1]!.body as string);
  expect(sent.starting_pools[0]).not.toHaveProperty("pool_id");
  const { pool_id: readOnlyId, ...editable } = pool;
  expect(readOnlyId).toBe("read-only-pool-id");
  expect(sent.starting_pools).toEqual([editable]);
  expect(sent.cases).toEqual(body.cases);
  expect(sent.provisional_acknowledged).toBe(true);
  if (operation === "save") expect(sent.expected_revision_number).toBe(3);
});
