/**
 * HRP-186 — Public assessment page (invited evaluator flow).
 *
 * Covers the three things the unit suite cannot reach:
 *   1. Proxy whitelist — `/public/assessments/<token>` is served without auth
 *      (the page lived behind the login gate before the fix).
 *   2. Final-notes autosave — the textarea actually PATCHes the backend
 *      (was a UI-only `Promise.resolve()` noop before the fix).
 *   3. End-to-end consent → autosave → submit / decline against a real
 *      invite issued through the recruiter API.
 *
 * Requires E2E_MODE=true on the backend so the dev token-fetch endpoint
 * is available; `registerUser` already depends on the same flag.
 */
import { test, expect, type Page } from "./fixtures";
import { registerUser } from "./helpers";

const API_BASE = "http://localhost:8100/api";

interface InviteSetup {
  cvId: string;
  roundId: string;
  inviteId: string;
  rawToken: string;
}

// HRP-352: invites are refused until the vacancy profile has competences,
// so every setup seeds a minimal profile matrix first.
export const E2E_PROFILE_COMPETENCES = [
  {
    id: "communication",
    name: "Communication",
    criticality: "critical",
    indicators: ["Clear writing", "Active listening"],
  },
  {
    id: "ownership",
    name: "Ownership",
    criticality: "important",
    indicators: [],
  },
];

async function createInviteSetup(
  page: Page,
  accessToken: string,
): Promise<InviteSetup> {
  const headers = { Authorization: `Bearer ${accessToken}` };

  const vacancyResp = await page.request.post(
    `${API_BASE}/recruitment/vacancies`,
    { headers, data: { title: `Public Eval Vacancy ${Date.now()}` } },
  );
  if (!vacancyResp.ok()) {
    throw new Error(
      `createVacancy failed (${vacancyResp.status()}): ${await vacancyResp.text()}`,
    );
  }
  const vacancy = await vacancyResp.json();

  const profileResp = await page.request.put(
    `${API_BASE}/recruitment/vacancies/${vacancy.id}/profile`,
    {
      headers,
      data: { profile_data: { competences: E2E_PROFILE_COMPETENCES } },
    },
  );
  if (!profileResp.ok()) {
    throw new Error(
      `saveProfile failed (${profileResp.status()}): ${await profileResp.text()}`,
    );
  }

  const candResp = await page.request.post(
    `${API_BASE}/recruitment/candidates`,
    {
      headers,
      data: {
        first_name: "Public",
        last_name: `Eval ${Date.now()}`,
        email: `cand-${Date.now()}-${Math.random().toString(36).slice(2, 6)}@test.com`,
      },
    },
  );
  if (!candResp.ok()) {
    throw new Error(
      `createCandidate failed (${candResp.status()}): ${await candResp.text()}`,
    );
  }
  const candidate = await candResp.json();

  const cvResp = await page.request.post(
    `${API_BASE}/recruitment/candidate-vacancies`,
    {
      headers,
      data: { candidate_id: candidate.id, vacancy_id: vacancy.id },
    },
  );
  if (!cvResp.ok()) {
    throw new Error(
      `attachCandidate failed (${cvResp.status()}): ${await cvResp.text()}`,
    );
  }
  const cv = await cvResp.json();

  const roundResp = await page.request.post(
    `${API_BASE}/v1/candidate-vacancies/${cv.id}/assessment-rounds`,
    { headers, data: { type: "interview" } },
  );
  if (!roundResp.ok()) {
    throw new Error(
      `createRound failed (${roundResp.status()}): ${await roundResp.text()}`,
    );
  }
  const round = await roundResp.json();

  const inviteResp = await page.request.post(
    `${API_BASE}/v1/candidate-vacancies/${cv.id}/manager-assessment-invites`,
    {
      headers,
      data: {
        invitees: [
          {
            email: `evaluator-${Date.now()}@example.com`,
            name: "External Evaluator",
          },
        ],
        round_id: round.id,
        expires_in_days: 7,
        allow_reediting: true,
      },
    },
  );
  if (!inviteResp.ok()) {
    throw new Error(
      `createInvites failed (${inviteResp.status()}): ${await inviteResp.text()}`,
    );
  }
  const invites = await inviteResp.json();
  const inviteId = invites[0].id as string;

  const tokenResp = await page.request.get(
    `${API_BASE}/v1/dev/manager-assessment-invites/${inviteId}/token`,
  );
  if (!tokenResp.ok()) {
    throw new Error(
      `dev token-fetch failed (${tokenResp.status()}): ${await tokenResp.text()}`,
    );
  }
  const { token } = await tokenResp.json();
  return { cvId: cv.id, roundId: round.id, inviteId, rawToken: token };
}

async function inviteStatus(
  page: Page,
  accessToken: string,
  cvId: string,
  inviteId: string,
): Promise<string> {
  const resp = await page.request.get(
    `${API_BASE}/v1/candidate-vacancies/${cvId}/manager-assessment-invites`,
    { headers: { Authorization: `Bearer ${accessToken}` } },
  );
  const invites = (await resp.json()) as Array<{ id: string; status: string }>;
  return invites.find((i) => i.id === inviteId)?.status ?? "missing";
}

test.describe("Public assessment page (HRP-186)", () => {
  test("unknown token reaches the invalid-page without /login redirect", async ({
    page,
  }) => {
    // Regression guard for the proxy whitelist: without `/public/assessments/`
    // in TOKEN_PUBLIC_PREFIXES the middleware bounces to /login and the
    // invited evaluator never sees the form.
    const response = await page.goto(
      "/public/assessments/this-token-does-not-exist-12345",
    );

    await expect(
      page.getByTestId("public-error-invalid-token-page"),
    ).toBeVisible({ timeout: 15000 });
    expect(page.url()).toContain("/public/assessments/");
    expect(page.url()).not.toContain("/login");

    // HRP-359 hardening headers from the proxy: strict nonce'd CSP,
    // noindex and no-referrer must all be present on the document.
    const headers = response!.headers();
    expect(headers["content-security-policy"]).toContain("'nonce-");
    expect(headers["content-security-policy"]).toContain(
      "frame-ancestors 'none'",
    );
    expect(headers["x-robots-tag"]).toContain("noindex");
    expect(headers["referrer-policy"]).toBe("no-referrer");
  });

  test("consent → autosave-persists → submit", async ({ page }) => {
    const admin = await registerUser(page);
    const setup = await createInviteSetup(page, admin.accessToken);

    // Visit without setting any auth tokens — this simulates a real
    // invited evaluator opening the email link in a clean browser.
    await page.goto(`/public/assessments/${setup.rawToken}`);

    await expect(
      page.getByTestId("public-assessment-consent-modal"),
    ).toBeVisible({ timeout: 15000 });
    await page.getByTestId("public-assessment-consent-accept-btn").click();
    await expect(page.getByTestId("public-assessment-page")).toBeVisible({
      timeout: 10000,
    });

    // Assert the autosave actually fires a PATCH (the prior implementation
    // was a no-op so the network was silent).
    const notesPatch = page.waitForRequest(
      (req) =>
        req
          .url()
          .includes(`/v1/public/assessments/${setup.rawToken}/notes`) &&
        req.method() === "PATCH",
      { timeout: 5000 },
    );
    await page
      .getByTestId("public-assessment-final-notes")
      .fill("My evaluator draft notes");
    await notesPatch;
    await expect(
      page.getByTestId("assessment-autosave-status"),
    ).toHaveText(/Saved/i, { timeout: 5000 });

    // Cross-check via the recruiter API that the draft really landed in
    // the DB — this is what was silently lost on refresh before the fix.
    const persisted = await page.request.get(
      `${API_BASE}/v1/assessment-rounds/${setup.roundId}/assessments`,
      { headers: { Authorization: `Bearer ${admin.accessToken}` } },
    );
    expect(persisted.ok()).toBeTruthy();
    const assessments = (await persisted.json()) as Array<{
      evaluator_invite_id: string | null;
      final_notes: string | null;
    }>;
    const ours = assessments.find(
      (a) => a.evaluator_invite_id === setup.inviteId,
    );
    expect(ours, "an assessment row was created for our invite").toBeDefined();
    expect(ours?.final_notes).toBe("My evaluator draft notes");

    // HRP-359: the page renders the real competence sheet — score the
    // critical competence so submit passes without the warning modal.
    const criticalCard = page
      .locator('details[data-testid^="assessment-competence-card-"]')
      .first();
    // HRP-368: the disclosure chevron is what tells an external evaluator
    // the card opens — it ships on the shared sheet, so it must render here.
    await expect(
      criticalCard.locator('[data-testid^="assessment-competence-chevron-"]'),
    ).toBeVisible();
    await criticalCard.locator("summary").click();
    const scorePatch = page.waitForRequest(
      (req) =>
        req.url().includes("/competence-scores/") && req.method() === "PATCH",
      { timeout: 5000 },
    );
    await criticalCard
      .locator(
        'label:has(input[data-testid^="assessment-competence-overall-radio-"][data-testid$="-3"])',
      )
      .click();
    await scorePatch;

    // Submit closes the flow.
    await page.getByTestId("public-assessment-submit-btn").click();
    await expect(
      page.getByTestId("public-assessment-submitted-banner"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("invite status walks opened → in progress → submitted (HRP-358)", async ({
    page,
    browser,
  }) => {
    const admin = await registerUser(page);
    const setup = await createInviteSetup(page, admin.accessToken);
    expect(
      await inviteStatus(page, admin.accessToken, setup.cvId, setup.inviteId),
    ).toBe("pending");

    const anonContext = await browser.newContext();
    const anonPage = await anonContext.newPage();
    try {
      // Following the email link is enough to flip pending → opened.
      await anonPage.goto(`/public/assessments/${setup.rawToken}`);
      await expect(
        anonPage.getByTestId("public-assessment-consent-modal"),
      ).toBeVisible({ timeout: 15000 });
      expect(
        await inviteStatus(page, admin.accessToken, setup.cvId, setup.inviteId),
      ).toBe("opened");

      await anonPage
        .getByTestId("public-assessment-consent-accept-btn")
        .click();
      await expect(
        anonPage.getByTestId("public-assessment-page"),
      ).toBeVisible({ timeout: 10000 });

      // First saved score flips opened → in progress.
      const card = anonPage
        .locator('details[data-testid^="assessment-competence-card-"]')
        .first();
      await card.locator("summary").click();
      const scorePatch = anonPage.waitForRequest(
        (req) =>
          req.url().includes("/competence-scores/") &&
          req.method() === "PATCH",
        { timeout: 5000 },
      );
      await card
        .locator(
          'label:has(input[data-testid^="assessment-competence-overall-radio-"][data-testid$="-3"])',
        )
        .click();
      await scorePatch;
      await expect
        .poll(
          () =>
            inviteStatus(page, admin.accessToken, setup.cvId, setup.inviteId),
          { timeout: 10000 },
        )
        .toBe("in_progress");

      // Submit flips to the terminal submitted status.
      await anonPage.getByTestId("public-assessment-submit-btn").click();
      await expect(
        anonPage.getByTestId("public-assessment-submitted-banner"),
      ).toBeVisible({ timeout: 10000 });
      expect(
        await inviteStatus(page, admin.accessToken, setup.cvId, setup.inviteId),
      ).toBe("submitted");
    } finally {
      await anonContext.close();
    }
  });

  test("submit warns when critical competences are unscored (HRP-359)", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const setup = await createInviteSetup(page, admin.accessToken);

    await page.goto(`/public/assessments/${setup.rawToken}`);
    await page.getByTestId("public-assessment-consent-accept-btn").click();
    await expect(page.getByTestId("public-assessment-page")).toBeVisible({
      timeout: 10000,
    });

    // No scores at all → the critical-competence warning modal appears.
    await page.getByTestId("public-assessment-submit-btn").click();
    await expect(
      page.getByTestId("public-assessment-submit-warning-modal"),
    ).toBeVisible({ timeout: 5000 });
    await page
      .getByTestId("public-assessment-submit-warning-modal-confirm")
      .click();
    await expect(
      page.getByTestId("public-assessment-submitted-banner"),
    ).toBeVisible({ timeout: 10000 });
    // Re-editing is allowed by default — the sheet stays interactive.
    await expect(page.getByTestId("public-assessment-reedit-note")).toBeVisible();
  });

  test("decline lands on the invalid-token page", async ({ page }) => {
    const admin = await registerUser(page);
    const setup = await createInviteSetup(page, admin.accessToken);

    await page.goto(`/public/assessments/${setup.rawToken}`);
    await expect(
      page.getByTestId("public-assessment-consent-modal"),
    ).toBeVisible({ timeout: 15000 });
    await page.getByTestId("public-assessment-consent-decline-btn").click();

    await expect(
      page.getByTestId("public-error-invalid-token-page"),
    ).toBeVisible({ timeout: 10000 });
  });
});
