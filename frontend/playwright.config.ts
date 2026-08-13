import { defineConfig, devices } from "@playwright/test";

// A worktree runs its own stack on offset ports (E2E_BASE_URL / E2E_API_BASE
// in e2e/helpers.ts). Setting the override also means a stack is already up,
// so the webServer block below must not spawn a second one on 3100.
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3100";
// Either override means a stack is already up. Reacting to E2E_API_BASE too
// matters: with only that one set, spawning the default frontend would point
// the main worktree's UI at this branch's backend.
const EXTERNAL_STACK =
  !!process.env.CI || !!process.env.E2E_BASE_URL || !!process.env.E2E_API_BASE;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: "html",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: EXTERNAL_STACK
    ? undefined
    : [
        {
          command: "cd .. && make run-back",
          url: "http://localhost:8100/health",
          reuseExistingServer: true,
          timeout: 30000,
        },
        {
          command: "npm run dev -- --port 3100",
          url: "http://localhost:3100",
          reuseExistingServer: true,
          timeout: 30000,
        },
      ],
});
