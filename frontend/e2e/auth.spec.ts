import { test, expect } from "./fixtures";
import {
  uniqueEmail,
  registerUser,
  loginViaUI,
  skipUnlessMultiLocaleStand,
  SAAS_E2E,
} from "./helpers";

test.describe("Login", () => {
  test("login page renders correctly", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByTestId("login-form")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("login-input-email")).toBeVisible();
    await expect(page.getByTestId("login-input-password")).toBeVisible();
    await expect(page.getByTestId("login-btn-submit")).toBeVisible();
    await expect(page.getByTestId("login-link-forgot")).toBeVisible();
    await expect(page.getByTestId("login-link-register")).toBeVisible();
  });

  test("login with valid credentials redirects to dashboard", async ({
    page,
  }) => {
    const { email, password } = await registerUser(page);
    await loginViaUI(page, email, password);
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10000 });
  });

  test("wrong password shows error", async ({ page }) => {
    const { email } = await registerUser(page);
    await page.goto("/login");
    await page.evaluate(() => {
      localStorage.clear();
      document.cookie =
        "has_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    });
    await page.goto("/login");
    await page.getByTestId("login-input-email").fill(email);
    await page.getByTestId("login-input-password").fill("wrongpassword");
    await page.getByTestId("login-btn-submit").click();
    await expect(page.getByTestId("login-error")).toBeVisible({
      timeout: 10000,
    });
    await expect(page).toHaveURL(/\/login/);
  });

  test("non-existent email shows error", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("login-input-email").fill(uniqueEmail());
    await page.getByTestId("login-input-password").fill("somepassword123");
    await page.getByTestId("login-btn-submit").click();
    await expect(page.getByTestId("login-error")).toBeVisible({
      timeout: 10000,
    });
  });

  test("forgot password link navigates", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("login-link-forgot").click();
    await expect(page).toHaveURL(/\/forgot-password/, { timeout: 10000 });
  });

  test("register link navigates", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("login-link-register").click();
    await expect(page).toHaveURL(/\/register/, { timeout: 10000 });
  });

  test("unauthenticated redirect to login", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => {
      localStorage.clear();
      document.cookie =
        "has_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    });
    await page.goto("/employees");
    await expect(page).toHaveURL(/\/login/, { timeout: 10000 });
  });
});

test.describe("Register", () => {
  // HRP-390: these cover the moderated saas funnel; the onprem self-serve
  // form is covered by register-onprem.spec.ts.
  test.skip(!SAAS_E2E, "moderated signup funnel only renders in saas mode");

  test("register page renders correctly", async ({ page }) => {
    await page.goto("/register");
    await expect(page.getByTestId("register-form")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("register-input-firstname")).toBeVisible();
    await expect(page.getByTestId("register-input-lastname")).toBeVisible();
    await expect(page.getByTestId("register-input-email")).toBeVisible();
    await expect(page.getByTestId("register-input-company")).toBeVisible();
    await expect(page.getByTestId("register-select-role")).toBeVisible();
    await expect(page.getByTestId("register-btn-submit")).toBeVisible();
  });

  test("register with valid data redirects to verify-email", async ({
    page,
  }) => {
    await page.goto("/register");
    await page.getByTestId("register-input-firstname").fill("E2E");
    await page.getByTestId("register-input-lastname").fill("User");
    await page.getByTestId("register-input-email").fill(uniqueEmail());
    await page.getByTestId("register-input-company").fill("E2E Corp");
    await page.getByTestId("register-select-role").selectOption("hr");
    await page.getByTestId("register-btn-submit").click();
    await expect(page).toHaveURL(/\/verify-email/, { timeout: 10000 });
  });

  test("register link to login", async ({ page }) => {
    await page.goto("/register");
    await expect(page.getByTestId("register-link-login")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("register-link-login").click();
    await expect(page).toHaveURL(/\/login/, { timeout: 10000 });
  });
});

test.describe("Forgot password", () => {
  test("forgot password page renders", async ({ page }) => {
    await page.goto("/forgot-password");
    await expect(page.getByTestId("forgot-form")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("forgot-input-email")).toBeVisible();
    await expect(page.getByTestId("forgot-btn-submit")).toBeVisible();
  });

  test("forgot password submit shows success", async ({ page }) => {
    await page.goto("/forgot-password");
    await page.getByTestId("forgot-input-email").fill("any@example.com");
    await page.getByTestId("forgot-btn-submit").click();
    await expect(page.getByText("reset link", { exact: false })).toBeVisible({
      timeout: 10000,
    });
  });

  test("back to login link", async ({ page }) => {
    await page.goto("/forgot-password");
    await expect(page.getByTestId("forgot-link-login")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("forgot-link-login").click();
    await expect(page).toHaveURL(/\/login/, { timeout: 10000 });
  });
});

// HRP-516: signed-out surfaces get their own locale control. Without it
// /login, /register and /accept-invite were stuck on whatever
// Accept-Language said, with nothing to change it.
test.describe("Auth page language switcher", () => {
  test("switches the signed-out interface and keeps the choice", async ({
    page,
  }) => {
    await page.goto("/login");
    await skipUnlessMultiLocaleStand(page);
    const trigger = page.getByTestId("auth-btn-language");
    await expect(trigger).toBeVisible({ timeout: 10000 });
    // aria-label is t(common.changeLanguage): it re-renders in the chosen
    // locale, so it proves the catalog actually took over.
    await trigger.click();
    await page.getByTestId("auth-menu-language-de").click();
    await expect(trigger).toHaveAttribute("aria-label", "Sprache ändern", {
      timeout: 10000,
    });
    // The choice is a cookie, so it survives navigation while signed out.
    await page.goto("/register");
    await expect(page.getByTestId("auth-btn-language")).toHaveAttribute(
      "aria-label",
      "Sprache ändern",
      { timeout: 10000 },
    );
    await page.goto("/login");
    await trigger.click();
    await page.getByTestId("auth-menu-language-en").click();
    await expect(trigger).toHaveAttribute("aria-label", "Change language", {
      timeout: 10000,
    });
  });

  test("an invitation link's ?lang= opens the page in that language", async ({
    page,
  }) => {
    // The link the backend puts in invitation emails carries the
    // recipient's locale; the proxy turns it into the NEXT_LOCALE cookie
    // and strips the parameter.
    await page.goto("/login?lang=de");
    await skipUnlessMultiLocaleStand(page);
    const trigger = page.getByTestId("auth-btn-language");
    await expect(trigger).toHaveAttribute("aria-label", "Sprache ändern", {
      timeout: 10000,
    });
    // Consumed, not sticky: the address bar must be clean afterwards.
    await expect(page).toHaveURL(/\/login$/, { timeout: 10000 });
  });

  test("a language switch survives reloading the link that set it", async ({
    page,
  }) => {
    // Regression: ?lang= used to re-apply on every navigation, so a user
    // who arrived on a German link, switched to English and pressed F5
    // was thrown back to German.
    await page.goto("/login?lang=de");
    await skipUnlessMultiLocaleStand(page);
    const trigger = page.getByTestId("auth-btn-language");
    await expect(trigger).toHaveAttribute("aria-label", "Sprache ändern", {
      timeout: 10000,
    });
    await trigger.click();
    await page.getByTestId("auth-menu-language-en").click();
    await expect(trigger).toHaveAttribute("aria-label", "Change language", {
      timeout: 10000,
    });
    await page.reload();
    await expect(page.getByTestId("auth-btn-language")).toHaveAttribute(
      "aria-label",
      "Change language",
      { timeout: 10000 },
    );
  });
});
