import { test, expect } from "./fixtures";

import {
  API_BASE,
  registerUser,
  SAAS_E2E,
  setAuthTokens,
  uniqueEmail,
} from "./helpers";

/**
 * HRP-806 — an imported employee gets a set-password link instead of a
 * shared default password, and an admin can resend it from the card until
 * the person sets a password. A demo emails only the first few of them.
 *
 * The import goes through the real Celery worker with a CSV shaped like the
 * page's own template: before this ticket that file did not import at all.
 */
test.describe("HRP-806 — import sends set-password links", () => {
  test("imported employee's card offers to resend the link", async ({
    page,
  }) => {
    const reg = await registerUser(page);
    const headers = { Authorization: `Bearer ${reg.accessToken}` };
    const email = uniqueEmail();

    const upload = await page.request.post(`${API_BASE}/import/employees`, {
      headers,
      multipart: {
        file: {
          name: "employees.csv",
          mimeType: "text/csv",
          buffer: Buffer.from(
            "email,first_name,last_name,position,hire_date\n" +
              `${email},Ida,Imported,Analyst,2024-01-15\n`,
          ),
        },
      },
    });
    expect(upload.ok(), await upload.text()).toBeTruthy();
    const job = await upload.json();

    await expect
      .poll(
        async () => {
          const res = await page.request.get(
            `${API_BASE}/import/jobs/${job.id}`,
            { headers },
          );
          const body = await res.json();
          return [body.status, body.processed_rows];
        },
        { timeout: 60000 },
      )
      .toEqual(["completed", 1]);

    const list = await page.request.get(
      `${API_BASE}/employees?q=${encodeURIComponent(email)}`,
      { headers },
    );
    const [employee] = (await list.json()).items;
    expect(employee.set_password_link_available).toBe(true);

    await setAuthTokens(page, reg.accessToken, reg.refreshToken);
    await page.goto(`/employees/${employee.id}`);
    await expect(page.getByTestId("employee-name")).toBeVisible({
      timeout: 15000,
    });

    await page.getByTestId("employee-btn-actions").click();
    const resend = page.getByTestId("employee-action-resend-set-password-link");
    await expect(resend).toBeVisible({ timeout: 10000 });

    const sent = page.waitForResponse(
      (res) =>
        res.url().includes(`/employees/${employee.id}/set-password-link`) &&
        res.request().method() === "POST",
    );
    await resend.click();
    const res = await sent;
    if (res.status() !== 204) {
      // A stack without an email provider says so instead of claiming the
      // link went out (CI runs without one).
      expect(res.status()).toBe(409);
      expect((await res.json()).code).toBe("set_password_link_email_not_configured");
    }
  });

  test("demo visitor is told how many imported employees get the email", async ({
    page,
  }) => {
    test.skip(!SAAS_E2E, "demo sandbox endpoints only exist in saas mode");
    const start = await page.request.post(`${API_BASE}/demo/start`, {
      data: {},
    });
    test.skip(start.status() === 503, "demo sandbox disabled on this stack");
    expect(start.ok(), `demo/start failed: ${start.status()}`).toBeTruthy();
    const { access_token } = await start.json();

    // Same storage dance as demo-persona.spec.ts.
    await page.goto("/login");
    await page.evaluate((token: string) => {
      localStorage.setItem("access_token", token);
      localStorage.removeItem("refresh_token");
      document.cookie = "has_token=1; path=/; SameSite=Lax";
      document.cookie = "demo_session=1; path=/; SameSite=Lax";
    }, access_token);

    await page.goto("/settings/import");
    await expect(page.getByTestId("import-demo-email-limit-note")).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId("import-demo-credits-note")).toBeVisible();
  });
});
