import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: "html",
  use: {
    baseURL: "http://localhost:3100",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: process.env.CI
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
