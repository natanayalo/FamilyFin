import assert from "node:assert/strict";
import test from "node:test";
import { ApiRequestError, apiRequest, setCsrfToken, subscribeApiHealth } from "../src/lib/api.ts";

const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { "Content-Type": "application/json" },
});

function observeHealth(context) {
  const events = [];
  const originalFetch = globalThis.fetch;
  const unsubscribe = subscribeApiHealth((value) => events.push(value));
  context.after(() => {
    unsubscribe();
    globalThis.fetch = originalFetch;
  });
  return events;
}

test("an API 401 expires shared auth and clears the in-memory CSRF token", async (context) => {
  const health = observeHealth(context);
  setCsrfToken("memory-only-token");
  let nextHeaders;
  globalThis.fetch = async (_url, init) => {
    if (init?.method === "POST") {
      nextHeaders = new Headers(init.headers);
      return json({ data: { ok: true } });
    }
    return json({ error: { code: "SESSION_EXPIRED", message: "Session expired" } }, 401);
  };

  await assert.rejects(apiRequest("/dashboard/overview"), (error) => error instanceof ApiRequestError && error.status === 401);
  await apiRequest("/classification/transactions/1/override", { method: "POST", body: "{}" });

  assert.deepEqual(health, ["unauthorized", "reachable"]);
  assert.equal(nextHeaders.get("X-CSRF-Token"), null);
});

test("a network failure hides protected content and the next successful API response restores reachability", async (context) => {
  const health = observeHealth(context);
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };

  await assert.rejects(apiRequest("/dashboard/overview"), (error) => error instanceof ApiRequestError && error.status === 0);
  globalThis.fetch = async () => json({ data: { ok: true } });
  await apiRequest("/auth/session");

  assert.deepEqual(health, ["unreachable", "reachable"]);
});

test("503 marks the API unreachable even while the browser may remain online", async (context) => {
  const health = observeHealth(context);
  globalThis.fetch = async () => json({ error: { code: "SERVICE_UNAVAILABLE", message: "Unavailable" } }, 503);

  await assert.rejects(apiRequest("/dashboard/overview"), (error) => error instanceof ApiRequestError && error.status === 503);
  assert.deepEqual(health, ["unreachable"]);
});
