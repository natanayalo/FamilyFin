import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { expect, it, vi } from "vitest";
import { AppProvider } from "@/components/app-provider";
import { Workspace } from "@/components/workspace";

vi.mock("next/navigation", () => ({ usePathname: () => "/planning" }));
vi.mock("@/components/theme-toggle", () => ({ ThemeToggle: () => null }));
vi.mock("@/lib/service-worker", () => ({ configureServiceWorker: vi.fn().mockResolvedValue(undefined) }));

function Draft() {
  const [value, setValue] = useState("");
  return <input aria-label="Budget draft" value={value} onChange={(event) => setValue(event.target.value)} />;
}

function sessionResponse() {
  return new Response(JSON.stringify({ data: { user: { id: "local", display_name: "Local" }, csrf_token: "csrf" } }), { status: 200 });
}

it("preserves a draft throughout a pending and successful background session check", async () => {
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => sessionResponse());
  render(<AppProvider><Workspace sectionId="planning"><Draft /></Workspace></AppProvider>);
  fireEvent.change(await screen.findByLabelText("Budget draft"), { target: { value: "Unsaved budget" } });
  let resolveCheck!: (response: Response) => void;
  fetchMock.mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveCheck = resolve; }));
  fireEvent(document, new Event("visibilitychange"));
  expect(screen.getByLabelText("Budget draft")).toHaveValue("Unsaved budget");
  await act(async () => resolveCheck(sessionResponse()));
  expect(screen.getByLabelText("Budget draft")).toHaveValue("Unsaved budget");
});

it.each([401, 500])("hides the workspace after revalidation fails with %s", async (status) => {
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => sessionResponse());
  render(<AppProvider><Workspace sectionId="planning"><Draft /></Workspace></AppProvider>);
  await screen.findByLabelText("Budget draft");
  fetchMock.mockImplementationOnce(async () => new Response("{}", { status }));
  fireEvent(document, new Event("visibilitychange"));
  await waitFor(() => expect(screen.queryByLabelText("Budget draft")).not.toBeInTheDocument());
});
