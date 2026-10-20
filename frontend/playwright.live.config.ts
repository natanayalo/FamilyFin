import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "live.spec.ts",
  outputDir: "test-results/live",
  workers: 1,
  fullyParallel: false,
  reporter: "list",
  timeout: 60_000,
  use: {
    baseURL: "http://127.0.0.1:3101",
    serviceWorkers: "allow",
    // Household responses and passwords must not enter saved browser traces.
    trace: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: ".venv/bin/python -m tests.live_stack",
    cwd: resolve(__dirname, ".."),
    url: "http://127.0.0.1:3101/api/v1/health",
    reuseExistingServer: false,
    timeout: 120_000,
    gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 },
  },
});
