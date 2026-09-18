import { defineConfig } from "@playwright/test";

/** Smoke tests against a RUNNING stack (web on :3000 talking to the engine). `pnpm e2e`. */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000", trace: "retain-on-failure" },
  reporter: [["list"]],
});
