import { defineConfig, devices } from "@playwright/test";

// Standalone Playwright config for the marketing landing tests.
// The landing tests do not hit the backend, so we skip the backend
// webServer (whose /health endpoint can be 503 in dev when celery is
// not running) and only spin up the Next.js frontend.
export default defineConfig({
  testDir: "./e2e",
  testMatch: /landing\.spec\.ts$/,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: "list",
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
  webServer: [
    {
      command: "npm run dev -- --port 3100",
      url: "http://localhost:3100",
      reuseExistingServer: true,
      timeout: 60000,
    },
  ],
});
