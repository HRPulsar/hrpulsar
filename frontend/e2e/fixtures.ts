// Crash guard for every spec (v1.19.1 fallout): the demo's seeded
// interview page crashed in prod while every spec that crossed it stayed
// green — the URL matched and the demo banner (outside the error
// boundary) was visible, so nothing asserted the page body actually
// rendered. Importing `test` from this file instead of @playwright/test
// arms two automatic nets:
//  * uncaught page errors fail the test (throws that escape React);
//  * a test may not end on the error-boundary screen (system-screen-500)
//    — React 19 reports boundary-caught render errors via console, not
//    window, so `pageerror` alone never sees them.
import { test as base, expect } from "@playwright/test";

// Benign browser noise that must not fail specs.
const IGNORED_PAGE_ERRORS = /ResizeObserver loop/;

export const test = base.extend<{ pageCrashGuard: void }>({
  pageCrashGuard: [
    async ({ page }, use, testInfo) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => {
        if (!IGNORED_PAGE_ERRORS.test(error.message)) {
          errors.push(error.message);
        }
      });
      await use();
      // Only pile on when the test itself passed — a real assertion
      // failure stays the headline.
      if (testInfo.status !== testInfo.expectedStatus) return;
      expect(errors, "uncaught page errors during the test").toEqual([]);
      if (!page.isClosed()) {
        try {
          expect(
            await page.getByTestId("system-screen-500").count(),
            "test ended on the error-boundary screen",
          ).toBe(0);
        } catch (err) {
          // Page torn down mid-check (navigation race) — not a crash.
          if (err instanceof Error && /Target.*closed|context/i.test(err.message)) return;
          throw err;
        }
      }
    },
    { auto: true },
  ],
});

export { expect, request, devices } from "@playwright/test";
export type { APIRequestContext, Page } from "@playwright/test";
