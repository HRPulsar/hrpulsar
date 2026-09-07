import { expect, test } from "./fixtures";
import { registerUser, setAuthTokens } from "./helpers";

// HRP-728: an API failure on the employees list used to render as the empty
// state ("no employees yet"). It must render an error with a retry instead.
test.describe("Employees list — load error", () => {
  test("shows an error with retry instead of the empty state when the API fails", async ({ page }) => {
    const admin = await registerUser(page);
    await setAuthTokens(page, admin.accessToken, admin.refreshToken);

    let fail = true;
    await page.route(
      (url) => url.pathname.endsWith("/api/employees"),
      async (route) => {
        if (fail && route.request().method() === "GET") {
          await route.fulfill({
            status: 503,
            contentType: "application/json",
            body: JSON.stringify({ detail: "no upstreams available" }),
          });
          return;
        }
        await route.continue();
      },
    );

    await page.goto("/employees");
    await expect(page.getByTestId("employees-load-failed")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("employees-empty")).toHaveCount(0);

    fail = false;
    await page.getByTestId("employees-load-retry").click();
    await expect(page.getByTestId("employees-load-failed")).toBeHidden({ timeout: 15000 });
  });
});
