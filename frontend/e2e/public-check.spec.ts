import { test, expect } from "./fixtures";
import { API_BASE, registerUser } from "./helpers";
import {
  APP_ORIGIN,
  CHECK_HOST_HEADER,
  CHECK_ORIGIN,
  PUBLIC_CHECK_E2E,
  actAsOwner,
  browseFrom,
  seedLetterToken,
  seedReadyCheck,
  spendIpBudget,
  uniqueIp,
  uniqueProcess,
} from "./public-check-helpers";

/**
 * HRP-932 — the public process check "AI or Human?" (epic HRP-918) on its
 * own host: input → result → share, the link preview, the gallery, keeping
 * a result by email, "my checks" and deleting them, the guards of the
 * intake. Without a model: a check sent from the form ends in the queue or
 * in an error (CI has no key); the result pages start from the seeded check
 * (public-check-helpers.ts). The live breakdown is public-check-live.spec.ts
 * (E2E_LLM=1); signup, approval and the move into Coverage are
 * ee/public-check-move.spec.ts.
 */
test.skip(
  !PUBLIC_CHECK_E2E,
  "the public check is off: run with PUBLIC_CHECK_ENABLED=true and PUBLIC_CHECK_HOST on backend, frontend and Playwright",
);

const CHECKS = `${API_BASE}/public-check/checks`;

test.describe("Public check — input page", () => {
  test("the check host's root is the form; a check opens its short result link", async ({
    page,
  }) => {
    await browseFrom(page, uniqueIp());
    const landed = await page.goto(`${CHECK_ORIGIN}/?utm_source=e2e&utm_campaign=hrp932`);
    expect(landed?.status()).toBe(200);
    // A rewrite, not a redirect: the short address stays in the bar.
    expect(page.url()).toBe(`${CHECK_ORIGIN}/?utm_source=e2e&utm_campaign=hrp932`);
    await expect(page.getByTestId("check-form")).toBeVisible();

    const submit = page.getByTestId("check-btn-submit");
    await expect(submit).toBeDisabled();
    await page.getByTestId("check-input-description").fill("Too short");
    await expect(submit).toBeDisabled();
    await expect(page.getByTestId("check-description-hint")).toBeVisible();

    await page.getByTestId("check-example-month-end-close").click();
    const description = await page.getByTestId("check-input-description").inputValue();
    expect(description.length).toBeGreaterThanOrEqual(20);
    await page.getByTestId("check-input-industry").fill("Retail");
    await page.getByTestId("check-input-team-size").fill("6");
    await page.getByTestId("check-select-frequency").selectOption("monthly");
    await page.getByTestId("check-input-hourly-rate").fill("55");

    const created = page.waitForResponse(
      (r) => r.url() === CHECKS && r.request().method() === "POST",
    );
    await submit.click();
    const response = await created;
    expect(response.status()).toBe(202);
    expect(response.request().postDataJSON()).toMatchObject({
      description,
      answers: {
        industry: "Retail",
        team_size: 6,
        frequency: "monthly",
        hourly_rate: 55,
        currency: "EUR",
      },
      locale: "en",
      utm: { source: "e2e", campaign: "hrp932" },
    });
    const { token } = (await response.json()) as { token: string };

    await page.waitForURL(`${CHECK_ORIGIN}/r/${token}`);
    // Queued or failed without a model key - either way the page polls the
    // check it was given, and this browser holds the check's owner key.
    await expect(
      page.getByTestId("check-progress").or(page.getByTestId("check-run-error")),
    ).toBeVisible({ timeout: 15000 });
    expect(
      await page.evaluate((t) => localStorage.getItem(`public-check:owner:${t}`), token),
    ).toBeTruthy();
  });

  test("a description outside 20–4000 characters is a 422, no check is made", async ({
    request,
  }) => {
    for (const description of ["x".repeat(19), "x".repeat(4001)]) {
      const resp = await request.post(CHECKS, {
        data: { description },
        headers: { "x-forwarded-for": uniqueIp() },
      });
      expect(resp.status()).toBe(422);
    }
  });

  test("past the per-IP budget the visitor reads why; results still open", async ({
    page,
    request,
  }) => {
    const ip = uniqueIp();
    const ready = await seedReadyCheck(request);
    expect(await spendIpBudget(request, ip)).toBeGreaterThan(0);

    const refused = await request.post(CHECKS, {
      data: { description: uniqueProcess() },
      headers: { "x-forwarded-for": ip },
    });
    expect(refused.status()).toBe(429);
    expect((await refused.json()).code).toBe("public_check_rate_limited");
    expect(Number(refused.headers()["retry-after"])).toBeGreaterThan(0);
    // Polling is never limited.
    const poll = await request.get(`${CHECKS}/${ready.token}`, {
      headers: { "x-forwarded-for": ip },
    });
    expect(poll.status()).toBe(200);

    await browseFrom(page, ip);
    await page.goto(`${CHECK_ORIGIN}/`);
    await page.getByTestId("check-input-description").fill(uniqueProcess());
    await page.getByTestId("check-btn-submit").click();
    await expect(page.getByTestId("check-error")).toContainText(/too many checks/i);
    await expect(page).toHaveURL(`${CHECK_ORIGIN}/`);
  });
});

test.describe("Public check — result, share, preview", () => {
  test("three lists with reasons, the headline, preliminary, the bridge and the share buttons", async ({
    page,
    request,
    context,
  }) => {
    const check = await seedReadyCheck(request, { answers: { hourly_rate: 50 } });
    const canonical = `${CHECK_ORIGIN}/r/${check.token}`;
    await actAsOwner(page, check);
    await context.grantPermissions(["clipboard-read", "clipboard-write"], {
      origin: CHECK_ORIGIN,
    });
    await page.goto(canonical);

    await expect(page.getByTestId("check-result")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("check-result-preliminary")).toBeVisible();
    await expect(page.getByTestId("check-result-headline")).toHaveAttribute("data-share", "25");
    await expect(page.getByTestId("check-share-to-review")).toHaveAttribute("data-share", "50");
    await expect(page.getByTestId("check-figure-total")).toBeVisible();
    for (const [list, steps] of [
      ["moves", [1]],
      ["to-review", [2, 3]],
      ["stays", [4]],
    ] as const) {
      const block = page.getByTestId(`check-list-${list}`);
      for (const position of steps) {
        await expect(block.getByTestId(`check-step-${position}-reason`)).not.toBeEmpty();
      }
    }
    // The physical step is out of every figure but not lost.
    const outOfScope = page.getByTestId("check-out-of-scope");
    await outOfScope.locator("summary").click();
    await expect(outOfScope.getByTestId("check-step-5")).toContainText("Carry the box");
    await expect(page.getByTestId("check-result-expires")).toBeVisible();
    await expect(page.getByTestId("check-save")).toBeVisible();

    const register = page.getByTestId("check-cta-register");
    await expect(register).toHaveAttribute(
      "href",
      new RegExp(`^${APP_ORIGIN}/register\\?utm_source=public_check&`),
    );

    await expect(page.getByTestId("check-social-url")).toHaveValue(canonical);
    await expect(page.getByTestId("check-social-linkedin")).toHaveAttribute(
      "href",
      `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(canonical)}`,
    );
    const xHref = new URL(
      (await page.getByTestId("check-social-x").getAttribute("href")) ?? "",
    );
    expect(xHref.origin + xHref.pathname).toBe("https://x.com/intent/tweet");
    expect(xHref.searchParams.get("url")).toBe(canonical);
    expect(xHref.searchParams.get("text")).toMatch(/^AI takes 1 of my 4 steps in “.+”$/);

    await page.getByTestId("check-social-copy").click();
    await expect(page.getByTestId("check-social-copy")).toHaveText(/copied/i);
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(canonical);
  });

  test("a crawler reads the result's own preview, and its card is an image", async ({
    request,
  }) => {
    const check = await seedReadyCheck(request, {
      description: uniqueProcess("Supplier invoices"),
    });
    const canonical = `${CHECK_ORIGIN}/r/${check.token}`;
    // LinkedIn's crawler, on the check host: metadata in the document head.
    const page = await request.get(`${APP_ORIGIN}/r/${check.token}`, {
      headers: { ...CHECK_HOST_HEADER, "user-agent": "LinkedInBot/1.0" },
    });
    expect(page.status()).toBe(200);
    const head = (await page.text()).split("</head>")[0];
    const meta = (attr: string, name: string) =>
      head.match(new RegExp(`<meta ${attr}="${name}" content="([^"]*)"`))?.[1] ?? null;
    expect(meta("property", "og:title")).toMatch(
      /^AI takes 1 of my 4 steps in (“|&quot;|&#x201C;)?Supplier invoices/,
    );
    expect(meta("property", "og:url")).toBe(canonical);
    expect(meta("name", "twitter:card")).toBe("summary_large_image");
    expect(meta("name", "robots")).toMatch(/noindex/);
    expect(head).toContain(`<link rel="canonical" href="${canonical}"`);

    const image = meta("property", "og:image") ?? "";
    expect(image.startsWith(`${CHECK_ORIGIN}/check/r/${check.token}/opengraph-image`)).toBe(
      true,
    );
    const card = await request.get(`${APP_ORIGIN}${new URL(image).pathname}`, {
      headers: CHECK_HOST_HEADER,
    });
    expect(card.status()).toBe(200);
    expect(card.headers()["content-type"]).toBe("image/png");
  });

  test("a shared link shows the result without the save block", async ({ page, request }) => {
    const check = await seedReadyCheck(request);
    await page.goto(`${CHECK_ORIGIN}/r/${check.token}`);
    await expect(page.getByTestId("check-result")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("check-social")).toBeVisible();
    await expect(page.getByTestId("check-save")).toHaveCount(0);

    // Nor can the API be talked into it without the owner key.
    const save = await request.post(`${CHECKS}/${check.token}/save`, {
      data: { email: "stranger@example.com", consent: true },
      headers: { "x-forwarded-for": uniqueIp() },
    });
    expect(save.status()).toBe(403);
  });

  test("an unknown link reads as unavailable and leads back to the form", async ({ page }) => {
    await page.goto(`${CHECK_ORIGIN}/r/not-a-real-token`);
    await expect(page.getByTestId("check-not-found")).toBeVisible({ timeout: 15000 });
    await page.getByTestId("check-link-new").click();
    await expect(page.getByTestId("check-form")).toBeVisible();
    expect(page.url()).toBe(`${CHECK_ORIGIN}/`);
  });
});

test.describe("Public check — gallery", () => {
  test("from the form to the gallery, a process and back to the form", async ({ page }) => {
    await page.goto(`${CHECK_ORIGIN}/`);
    await page.getByTestId("check-link-gallery").click();
    await expect(page.getByTestId("check-gallery")).toBeVisible();
    expect(page.url()).toBe(`${CHECK_ORIGIN}/gallery`);

    await page.getByTestId("check-gallery-search").fill("onboard");
    await expect(page.getByTestId("check-gallery-item-employee-onboarding")).toBeVisible();
    await expect(page.getByTestId("check-gallery-item-month-end-close")).toHaveCount(0);
    await page.getByTestId("check-gallery-search").fill("zzzz");
    await expect(page.getByTestId("check-gallery-empty")).toBeVisible();
    await page.getByTestId("check-gallery-search").fill("");

    await page.getByTestId("check-gallery-item-month-end-close").click();
    await expect(page.getByTestId("check-gallery-process")).toBeVisible();
    expect(page.url()).toBe(`${CHECK_ORIGIN}/gallery/month-end-close`);
    await expect(page.getByTestId("check-gallery-steps")).toContainText(/of \d+ steps/);
    await expect(page.getByTestId("check-list-moves")).toBeVisible();
    await expect(page.getByTestId("check-gallery-sources")).toBeVisible();

    await page.getByTestId("check-gallery-cta").click();
    await expect(page.getByTestId("check-form")).toBeVisible();
    expect(page.url()).toBe(`${CHECK_ORIGIN}/`);
  });
});

test.describe("Public check — its host", () => {
  test("a product path on the check host is a 307 to the app host, uncached", async ({
    page,
  }) => {
    const landed = await page.goto(`${CHECK_ORIGIN}/dashboard?from=check`);
    // The first hop of the chain (the app host bounces a guest to /login).
    let hop = landed?.request();
    while (hop?.redirectedFrom()) hop = hop.redirectedFrom()!;
    const redirect = await hop?.response();
    expect(hop?.url()).toBe(`${CHECK_ORIGIN}/dashboard?from=check`);
    expect(redirect?.status()).toBe(307);
    expect(redirect?.headers()["location"]).toBe(`${APP_ORIGIN}/dashboard?from=check`);
    expect(redirect?.headers()["cache-control"]).toBe("no-store");
    // Signed out on the app host: its own guard takes over from there.
    expect(new URL(page.url()).origin).toBe(APP_ORIGIN);
  });

  test("robots and sitemap answer for the check host only", async ({ request }) => {
    const robots = await request.get(`${APP_ORIGIN}/robots.txt`, { headers: CHECK_HOST_HEADER });
    expect(await robots.text()).toMatch(/Allow: \//);
    const sitemap = await request.get(`${APP_ORIGIN}/sitemap.xml`, { headers: CHECK_HOST_HEADER });
    expect(sitemap.status()).toBe(200);
    expect(await sitemap.text()).toContain(`${CHECK_ORIGIN}/gallery/month-end-close`);
    expect((await request.get(`${APP_ORIGIN}/sitemap.xml`)).status()).toBe(404);
  });
});

test.describe("Public check — kept by email", () => {
  test("save → confirm → my checks → open a result → delete my data", async ({
    page,
    request,
  }) => {
    const email = `e2e-check-${Date.now()}-${Math.random().toString(36).slice(2, 6)}@test.com`;
    const check = await seedReadyCheck(request);
    await actAsOwner(page, check);
    await browseFrom(page, uniqueIp());
    await page.goto(`${CHECK_ORIGIN}/r/${check.token}`);

    // Missing pieces are said on click, not hidden behind a dead button.
    const save = page.getByTestId("check-save");
    await save.getByTestId("check-save-btn-submit").click();
    await expect(save.getByTestId("check-save-error")).toBeVisible();
    await save.getByTestId("check-save-input-email").fill(email);
    await save.getByTestId("check-save-btn-submit").click();
    await expect(save.getByTestId("check-save-error")).toContainText(/agree/i);
    await save.getByTestId("check-save-consent").check();
    await save.getByTestId("check-save-btn-submit").click();
    await expect(save.getByTestId("check-save-sent")).toContainText(email);
    await expect(page.getByTestId("check-result-expires")).toBeVisible();

    // The letter's link: a button, never an action on open.
    const confirm = await seedLetterToken(request, email);
    expect(confirm.kind).toBe("confirm");
    await page.goto(`${CHECK_ORIGIN}/confirm/${confirm.token}`);
    await expect(page.getByTestId("check-confirm")).toBeVisible();
    await page.getByTestId("check-confirm-btn").click();
    await expect(page.getByTestId("check-confirm-done")).toBeVisible();

    await page.goto(`${CHECK_ORIGIN}/r/${check.token}`);
    await expect(page.getByTestId("check-result")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("check-save")).toHaveCount(0);
    await expect(page.getByTestId("check-result-expires")).toHaveCount(0);

    // "My checks": the same answer for any address, the link by letter.
    await page.goto(`${CHECK_ORIGIN}/my`);
    await page.getByTestId("check-link-input-email").fill(email);
    await page.getByTestId("check-link-btn-submit").click();
    await expect(page.getByTestId("check-link-sent")).toBeVisible();
    const magic = await seedLetterToken(request, email);
    expect(magic.kind).toBe("magic");

    await page.goto(`${CHECK_ORIGIN}/my/${magic.token}`);
    await expect(page.getByTestId("check-my")).toBeVisible();
    const item = page.locator(`[data-testid="check-my-item"][data-check-id="${check.id}"]`);
    await expect(item).toBeVisible();
    // No account with this address yet: "move" registers on the app host.
    const move = page.getByTestId("check-my-move-link");
    await expect(move).toHaveAttribute(
      "href",
      `${APP_ORIGIN}/register?utm_source=public_check&utm_medium=my_checks&utm_campaign=ai_or_human&email=${encodeURIComponent(email)}`,
    );

    await item.getByRole("link").first().click();
    await expect(page.getByTestId("check-saved-result")).toBeVisible();
    await expect(page.getByTestId("check-result")).toBeVisible();
    await expect(page.getByTestId("check-save")).toHaveCount(0);
    await page.getByTestId("check-saved-back").click();
    await expect(page.getByTestId("check-my")).toBeVisible();

    // Reverse: the address and its checks go, the links die.
    await page.getByTestId("check-my-btn-delete").click();
    await expect(page.getByTestId("check-my-delete-dialog")).toBeVisible();
    await page.getByTestId("check-my-delete-dialog-confirm").click();
    await expect(page.getByTestId("check-my-deleted")).toBeVisible();
    await page.goto(`${CHECK_ORIGIN}/r/${check.token}`);
    await expect(page.getByTestId("check-not-found")).toBeVisible({ timeout: 15000 });
    await page.goto(`${CHECK_ORIGIN}/my/${magic.token}`);
    await expect(page.getByTestId("check-link-invalid")).toBeVisible();
  });
});

test.describe("Public check — the move link stays out of URLs a server sees", () => {
  test("the import page's link rides in the fragment through sign-in and leaves the address", async ({
    page,
  }) => {
    const link = `e2e-link-${Date.now()}`;
    const user = await registerUser(page);
    // A guest: the proxy sends them to /login; the token is not in next=.
    await page.goto(`${APP_ORIGIN}/coverage/saved-checks#link=${link}`);
    await page.waitForURL("**/login?**");
    const login = new URL(page.url());
    expect(login.searchParams.get("next")).toBe("/coverage/saved-checks");
    expect(login.search).not.toContain(link);
    expect(login.hash).toBe(`#link=${link}`);

    await page.getByTestId("login-input-email").fill(user.email);
    await page.getByTestId("login-input-password").fill(user.password);
    await page.getByTestId("login-btn-submit").click();
    await page.waitForURL(`${APP_ORIGIN}/coverage/saved-checks`);
    await expect(page.getByTestId("coverage-import")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("coverage-import-btn")).toBeEnabled();
    expect(page.url()).not.toContain(link);

    // A reload keeps the link (the session has it) and sends no Referer.
    const reloaded = await page.reload();
    expect(reloaded?.headers()["referrer-policy"]).toBe("no-referrer");
    await expect(page.getByTestId("coverage-import-btn")).toBeEnabled({ timeout: 15000 });
  });
});
