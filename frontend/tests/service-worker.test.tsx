import { afterEach, expect, it, vi } from "vitest";
import { configureServiceWorker } from "@/lib/service-worker";

afterEach(() => vi.unstubAllGlobals());

it("development removes only FamilyFin workers and static caches", async () => {
  const unregister = vi.fn().mockResolvedValue(true);
  const otherUnregister = vi.fn();
  const serviceWorker = {
    getRegistrations: vi.fn().mockResolvedValue([
      { active: { scriptURL: `${location.origin}/sw.js` }, unregister },
      { active: { scriptURL: `${location.origin}/another-worker.js` }, unregister: otherUnregister },
    ]),
    register: vi.fn(), controller: null,
  };
  Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: serviceWorker });
  const cacheStorage = { keys: vi.fn().mockResolvedValue(["familyfin-static-old", "unrelated"]), delete: vi.fn() };
  vi.stubGlobal("caches", cacheStorage);
  await configureServiceWorker(true);
  expect(unregister).toHaveBeenCalledOnce();
  expect(otherUnregister).not.toHaveBeenCalled();
  expect(cacheStorage.delete).toHaveBeenCalledExactlyOnceWith("familyfin-static-old");
  expect(serviceWorker.register).not.toHaveBeenCalled();
});

it("QA and production register the real service worker", async () => {
  const register = vi.fn().mockResolvedValue({});
  Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: { register } });
  await configureServiceWorker(false);
  expect(register).toHaveBeenCalledExactlyOnceWith("/sw.js", { scope: "/" });
});
