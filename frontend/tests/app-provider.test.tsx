import { useState } from "react";
import { getDashboardFilters, rememberDashboardFilters, resetDashboardFilters } from "@/features/dashboard/filter-state";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppProvider, useAppAuth } from "@/components/app-provider";

vi.mock("@/lib/service-worker", () => ({ configureServiceWorker: vi.fn().mockResolvedValue(undefined) }));

function Status() {
  const { auth, online, refreshSession, signIn, signOut } = useAppAuth();
  return <><span>{auth.status}:{String(online)}</span><button onClick={() => void refreshSession()}>retry</button><button onClick={() => void signOut()}>logout</button><button onClick={() => void signIn("b", "password")}>login</button></>;
}

function sessionResponse(id = "local") {
  return new Response(JSON.stringify({ data: { user: { id, display_name: "Local" }, csrf_token: "csrf" } }), { status: 200 });
}

describe("local API connectivity", () => {
  it("works when navigator reports no internet and revalidates offline events", async () => {
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => sessionResponse());
    render(<AppProvider><Status /></AppProvider>);
    await screen.findByText("signed-in:true");
    fireEvent(window, new Event("offline"));
    await screen.findByText("signed-in:true");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("hides content on an API error and restores authentication after retry", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => sessionResponse());
    render(<AppProvider><Status /></AppProvider>);
    await screen.findByText("signed-in:true");
    fetchMock.mockImplementation(async () => new Response("{}", { status: 500 }));
    fireEvent(window, new Event("offline"));
    await screen.findByText("offline:false");
    fetchMock.mockImplementation(async () => sessionResponse());
    fireEvent.click(screen.getByText("retry"));
    await screen.findByText("signed-in:true");
  });
});

const usdFilters = { start_month: "2026-01-01", end_month: "2026-09-01", currency: "USD" };

// Capture filters only on mount, just as report hooks initialize their draft.
function ReportProbe() {
  const { auth } = useAppAuth();
  const [currency] = useState(() => getDashboardFilters()?.currency ?? "account-default");
  return auth.status === "signed-in" ? <span>{auth.session.user.id}:{currency}</span> : null;
}

describe("account filter isolation", () => {
  afterEach(resetDashboardFilters);

  it("clears applied filters on sign-out before another account signs in", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => sessionResponse("a"));
    render(<AppProvider><Status /><ReportProbe /></AppProvider>);
    await screen.findByText("a:account-default");
    rememberDashboardFilters(usdFilters);
    fetchMock.mockImplementation(async () => new Response(null, { status: 204 }));
    fireEvent.click(screen.getByText("logout"));
    await screen.findByText("signed-out:true");
    expect(getDashboardFilters()).toBeUndefined();
    fetchMock.mockImplementation(async () => sessionResponse("b"));
    fireEvent.click(screen.getByText("login"));
    await screen.findByText("b:account-default");
  });

  it("keeps filters for the same session and clears them before mounting a changed account", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => sessionResponse("a"));
    render(<AppProvider><Status /><ReportProbe /></AppProvider>);
    await screen.findByText("a:account-default");
    rememberDashboardFilters(usdFilters);
    fireEvent.click(screen.getByText("retry"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(getDashboardFilters()).toEqual(usdFilters);
    fetchMock.mockImplementation(async () => sessionResponse("b"));
    fireEvent.click(screen.getByText("retry"));
    await screen.findByText("b:account-default");
    expect(getDashboardFilters()).toBeUndefined();
  });

  it("clears filters when the API reports an expired session", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => sessionResponse());
    render(<AppProvider><Status /></AppProvider>);
    await screen.findByText("signed-in:true");
    rememberDashboardFilters(usdFilters);
    fetchMock.mockImplementation(async () => new Response("{}", { status: 401 }));
    fireEvent.click(screen.getByText("retry"));
    await screen.findByText("signed-out:true");
    expect(getDashboardFilters()).toBeUndefined();
  });

  it("preserves filters across a temporary API outage for the same account", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => sessionResponse());
    render(<AppProvider><Status /></AppProvider>);
    await screen.findByText("signed-in:true");
    rememberDashboardFilters(usdFilters);
    fetchMock.mockRejectedValue(new TypeError("offline"));
    fireEvent.click(screen.getByText("retry"));
    await screen.findByText("offline:false");
    expect(getDashboardFilters()).toEqual(usdFilters);
    fetchMock.mockImplementation(async () => sessionResponse());
    fireEvent.click(screen.getByText("retry"));
    await screen.findByText("signed-in:true");
    expect(getDashboardFilters()).toEqual(usdFilters);
  });
});
