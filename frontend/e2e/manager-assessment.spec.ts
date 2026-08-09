import { test, expect } from "@playwright/test";
import { registerUser, loginViaUI } from "./helpers";

const API_BASE = "http://localhost:8100/api";

test.describe("Manager assessments (HRP-186)", () => {
  test("candidate card mounts Assessments section and creates a round", async ({
    page,
  }) => {
    const { email, password, accessToken } = await registerUser(page);

    const vacResp = await page.request.post(
      `${API_BASE}/recruitment/vacancies`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: { title: "HRP-186 e2e vacancy", language: "en" },
      },
    );
    expect(vacResp.ok()).toBeTruthy();
    const vacancy = await vacResp.json();

    const candResp = await page.request.post(
      `${API_BASE}/recruitment/vacancies/${vacancy.id}/candidates`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: {
          full_name: "Jane Assessment",
          email: `jane-${Date.now()}@example.com`,
        },
      },
    );
    expect(candResp.ok()).toBeTruthy();
    const candidate = await candResp.json();

    await loginViaUI(page, email, password);
    await page.goto(`/recruitment/candidates/${candidate.id}`);

    const section = page.getByTestId("candidate-section-assessments");
    await expect(section).toBeVisible({ timeout: 10000 });
    await expect(section).toContainText("Manager assessments");

    await page.getByTestId("assessment-round-new-btn").click();
    // HRP-186 REDO: a confirm dialog now guards the round creation.
    await page
      .getByTestId("assessment-round-new-confirm-modal-confirm")
      .click();
    const firstTab = page.locator('[data-testid^="assessment-round-tab-"]');
    await expect(firstTab).toHaveCount(1, { timeout: 10000 });
    await expect(firstTab.first()).toContainText("Interview");

    // HRP-352: no competences in the vacancy profile yet → the invite
    // button is disabled (tooltip explains why).
    const inviteBtn = page.getByTestId("invite-evaluator-modal-open");
    await expect(inviteBtn).toBeDisabled();

    // Seed a profile matrix, reload — the button unlocks.
    const profSeedResp = await page.request.put(
      `${API_BASE}/recruitment/vacancies/${vacancy.id}/profile`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: {
          profile_data: {
            competences: [{ name: "Communication", criticality: "critical" }],
          },
        },
      },
    );
    expect(profSeedResp.ok()).toBeTruthy();
    await page.reload();
    await expect(inviteBtn).toBeEnabled({ timeout: 10000 });
    await inviteBtn.click();
    const modal = page.getByTestId("invite-evaluator-modal");
    await expect(modal).toBeVisible();

    // HRP-350: Remove on the only row clears it back to placeholders.
    await page.getByTestId("invite-evaluator-modal-email-0").fill("a@b.com");
    await page.getByTestId("invite-evaluator-modal-name-0").fill("Some Name");
    await page.getByTestId("invite-evaluator-modal-remove-0").click();
    await expect(
      page.getByTestId("invite-evaluator-modal-email-0"),
    ).toHaveValue("");
    await expect(page.getByTestId("invite-evaluator-modal-name-0")).toHaveValue(
      "",
    );

    // HRP-350: a malformed email is rejected client-side; the modal stays
    // open and no invite row appears.
    await page.getByTestId("invite-evaluator-modal-email-0").fill("Aaa");
    await page.getByTestId("invite-evaluator-modal-name-0").fill("Bad Email");
    await page.getByTestId("invite-evaluator-modal-submit").click();
    await expect(modal).toBeVisible();
    await expect(
      page.locator('[data-testid^="assessment-round-invite-"]'),
    ).toHaveCount(0);
  });

  // HRP-348 REDO: the sheet renders indicators + criticality chips, and
  // `Mark as complete` stays locked until every critical competence has
  // an overall score.
  test("assessment sheet shows indicators, criticality chip and gates completion", async ({
    page,
  }) => {
    const { email, password, accessToken } = await registerUser(page);

    const vacResp = await page.request.post(
      `${API_BASE}/recruitment/vacancies`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: { title: "HRP-348 e2e vacancy", language: "en" },
      },
    );
    expect(vacResp.ok()).toBeTruthy();
    const vacancy = await vacResp.json();

    const profResp = await page.request.put(
      `${API_BASE}/recruitment/vacancies/${vacancy.id}/profile`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: {
          profile_data: {
            competences: [
              {
                name: "Python",
                group: "Hard",
                subgroup: "Core",
                criticality: "critical",
                indicators: ["Writes idiomatic code", "Knows asyncio"],
              },
              {
                name: "Teamwork",
                group: "Soft",
                subgroup: "Core",
                criticality: "desirable",
              },
            ],
          },
        },
      },
    );
    expect(profResp.ok()).toBeTruthy();

    const candResp = await page.request.post(
      `${API_BASE}/recruitment/vacancies/${vacancy.id}/candidates`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: {
          full_name: "John Sheet",
          email: `john-${Date.now()}@example.com`,
        },
      },
    );
    expect(candResp.ok()).toBeTruthy();
    const candidate = await candResp.json();

    await loginViaUI(page, email, password);
    await page.goto(`/recruitment/candidates/${candidate.id}`);

    const section = page.getByTestId("candidate-section-assessments");
    await expect(section).toBeVisible({ timeout: 10000 });

    await page.getByTestId("assessment-round-new-btn").click();
    await page
      .getByTestId("assessment-round-new-confirm-modal-confirm")
      .click();
    await expect(
      page.locator('[data-testid^="assessment-round-tab-"]'),
    ).toHaveCount(1, { timeout: 10000 });

    // Start scoring — creates the per-user sheet.
    await page
      .getByRole("button", { name: "Start scoring this round" })
      .click();

    const cards = page.locator('[data-testid^="assessment-competence-card-"]');
    await expect(cards).toHaveCount(2, { timeout: 10000 });
    await expect(section).toContainText("0 / 2 competences assessed");

    // Criticality chips are rendered for both competences.
    await expect(
      page.locator('[data-testid^="assessment-competence-criticality-"]'),
    ).toHaveCount(2);
    await expect(section).toContainText("Critical");
    await expect(section).toContainText("Desirable");

    // Completion is locked while the critical competence is unscored.
    const completeBtn = page.getByTestId("assessment-round-complete-btn");
    await expect(completeBtn).toBeDisabled();

    // Open the critical competence card — indicators are listed with
    // their own score rows.
    const criticalCard = cards.filter({ hasText: "Python" });
    // HRP-368: chevron marks the card as expandable before it is opened.
    await expect(
      criticalCard.locator('[data-testid^="assessment-competence-chevron-"]'),
    ).toBeVisible();
    await criticalCard.locator("summary").click();
    await expect(
      criticalCard.locator('[data-testid^="assessment-indicators-"]'),
    ).toBeVisible();
    await expect(criticalCard).toContainText("Writes idiomatic code");
    await expect(criticalCard).toContainText("Knows asyncio");

    // Scoring only the desirable competence keeps completion locked.
    const desirableCard = cards.filter({ hasText: "Teamwork" });
    await desirableCard.locator("summary").click();
    await desirableCard
      .locator(
        'label:has(input[data-testid^="assessment-competence-overall-radio-"][data-testid$="-3"])',
      )
      .click();
    await expect(section).toContainText("1 / 2 competences assessed");
    await expect(completeBtn).toBeDisabled();

    // Scoring the critical competence through its indicators computes the
    // overall server-side and unlocks Mark as complete.
    const indicatorRadios = criticalCard.locator(
      'label:has(input[data-testid^="assessment-indicator-radio-"][data-testid$="-3"])',
    );
    await expect(indicatorRadios).toHaveCount(2);
    await indicatorRadios.nth(0).click();
    await indicatorRadios.nth(1).click();
    await expect(section).toContainText("2 / 2 competences assessed", {
      timeout: 10000,
    });
    // HRP-378: the overall is still derived from the indicators — the card
    // now reports it as the round average instead of a "from indicators"
    // chip, and the completion gate opens.
    await expect(
      criticalCard.locator(
        '[data-testid^="assessment-competence-round-average-"]',
      ),
    ).toContainText("3.0", { timeout: 10000 });
    await expect(completeBtn).toBeEnabled();
  });

  // HRP-374: the round header carries an Average score next to the progress
  // bar — an em dash until something is scored, then the round mean.
  // HRP-378: indicators and a manual overall never contradict each other.
  test("round header shows Average score and overall/indicators override each other", async ({
    page,
  }) => {
    const { email, password, accessToken } = await registerUser(page);

    const vacResp = await page.request.post(
      `${API_BASE}/recruitment/vacancies`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: { title: "HRP-374 e2e vacancy", language: "en" },
      },
    );
    expect(vacResp.ok()).toBeTruthy();
    const vacancy = await vacResp.json();

    const profResp = await page.request.put(
      `${API_BASE}/recruitment/vacancies/${vacancy.id}/profile`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: {
          profile_data: {
            competences: [
              {
                name: "Python",
                criticality: "critical",
                indicators: ["Writes idiomatic code", "Knows asyncio"],
              },
            ],
          },
        },
      },
    );
    expect(profResp.ok()).toBeTruthy();

    const candResp = await page.request.post(
      `${API_BASE}/recruitment/vacancies/${vacancy.id}/candidates`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: {
          full_name: "Ada Average",
          email: `ada-${Date.now()}@example.com`,
        },
      },
    );
    expect(candResp.ok()).toBeTruthy();
    const candidate = await candResp.json();

    await loginViaUI(page, email, password);
    await page.goto(`/recruitment/candidates/${candidate.id}`);

    const section = page.getByTestId("candidate-section-assessments");
    await expect(section).toBeVisible({ timeout: 10000 });
    await page.getByTestId("assessment-round-new-btn").click();
    await page
      .getByTestId("assessment-round-new-confirm-modal-confirm")
      .click();
    await expect(
      page.locator('[data-testid^="assessment-round-tab-"]'),
    ).toHaveCount(1, { timeout: 10000 });
    await page
      .getByRole("button", { name: "Start scoring this round" })
      .click();

    // Nothing scored yet — the header shows an em dash, not a zero.
    const average = page.getByTestId("assessment-round-average-score");
    await expect(average).toBeVisible({ timeout: 10000 });
    await expect(average).toContainText("—");

    const card = page
      .locator('[data-testid^="assessment-competence-card-"]')
      .first();
    await card.locator("summary").click();

    // A manual overall of 4 lands in the header average.
    await card
      .locator(
        'label:has(input[data-testid^="assessment-competence-overall-radio-"][data-testid$="-4"])',
      )
      .click();
    await expect(average).toContainText("4.0", { timeout: 10000 });

    // HRP-378 §7.2: indicators now override that manual overall — two 2s
    // pull the competence (and the header average) down to 2.0.
    const twos = card.locator(
      'label:has(input[data-testid^="assessment-indicator-radio-"][data-testid$="-2"])',
    );
    await expect(twos).toHaveCount(2);
    await twos.nth(0).click();
    await twos.nth(1).click();
    await expect(average).toContainText("2.0", { timeout: 10000 });

    // HRP-378 §7.4: going back to a manual overall clears the indicator
    // answers — nothing stays selected.
    await card
      .locator(
        'label:has(input[data-testid^="assessment-competence-overall-radio-"][data-testid$="-3"])',
      )
      .click();
    await expect(average).toContainText("3.0", { timeout: 10000 });
    await expect(
      card.locator('input[data-testid^="assessment-indicator-radio-"]:checked'),
    ).toHaveCount(0);
  });

  // HRP-372: tabs read in hiring order regardless of creation order.
  // HRP-376: the round kebab closes / archives the round, and completing
  // it turns the sheet read-only and revokes the external links.
  // HRP-377: every invitation carries its own actions menu.
  test("round tabs are ordered, and the kebab completes and archives a round", async ({
    page,
  }) => {
    const { email, password, accessToken } = await registerUser(page);

    const vacResp = await page.request.post(
      `${API_BASE}/recruitment/vacancies`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: { title: "HRP-376 e2e vacancy", language: "en" },
      },
    );
    expect(vacResp.ok()).toBeTruthy();
    const vacancy = await vacResp.json();

    const profResp = await page.request.put(
      `${API_BASE}/recruitment/vacancies/${vacancy.id}/profile`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: {
          profile_data: {
            competences: [{ name: "Python", criticality: "critical" }],
          },
        },
      },
    );
    expect(profResp.ok()).toBeTruthy();

    const candResp = await page.request.post(
      `${API_BASE}/recruitment/vacancies/${vacancy.id}/candidates`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: {
          full_name: "Ordered Rounds",
          email: `ordered-${Date.now()}@example.com`,
        },
      },
    );
    expect(candResp.ok()).toBeTruthy();
    const candidate = await candResp.json();

    await loginViaUI(page, email, password);
    await page.goto(`/recruitment/candidates/${candidate.id}`);

    const section = page.getByTestId("candidate-section-assessments");
    await expect(section).toBeVisible({ timeout: 10000 });

    // Interview 1 first, then a Pre-interview — the strip must still read
    // Pre-interview, Interview 1.
    await page.getByTestId("assessment-round-new-btn").click();
    await page
      .getByTestId("assessment-round-new-confirm-modal-confirm")
      .click();
    const tabs = page.locator('[data-testid^="assessment-round-tab-"]');
    await expect(tabs).toHaveCount(1, { timeout: 10000 });
    await page.getByRole("button", { name: "+ Pre-interview" }).click();
    await expect(tabs).toHaveCount(2, { timeout: 10000 });
    await expect(tabs.first()).toContainText("Pre-interview");
    await expect(tabs.nth(1)).toContainText("Interview 1");

    // Work on Interview 1: start scoring, invite an external evaluator.
    await tabs.nth(1).click();
    await page
      .getByRole("button", { name: "Start scoring this round" })
      .click();
    await expect(
      page.locator('[data-testid^="assessment-competence-card-"]'),
    ).toHaveCount(1, { timeout: 10000 });

    await page.getByTestId("invite-evaluator-modal-open").click();
    await page
      .getByTestId("invite-evaluator-modal-email-0")
      .fill("ext@example.com");
    await page.getByTestId("invite-evaluator-modal-name-0").fill("Ext Eval");
    await page.getByTestId("invite-evaluator-modal-submit").click();
    const inviteRow = page
      .locator('[data-testid^="assessment-round-invite-"]')
      .first();
    await expect(inviteRow).toBeVisible({ timeout: 10000 });
    // HRP-377: the row has a kebab offering Resend / Revoke.
    await inviteRow.locator('[data-testid$="-kebab"]').click();
    await expect(page.locator('[data-testid$="-resend"]')).toBeVisible();
    await page.keyboard.press("Escape");

    // HRP-348: the kebab's Complete obeys the same gate as the button, so
    // the critical competence has to carry a score first.
    const scoreCard = page
      .locator('[data-testid^="assessment-competence-card-"]')
      .first();
    await scoreCard.locator("summary").click();
    await scoreCard
      .locator(
        'label:has(input[data-testid^="assessment-competence-overall-radio-"][data-testid$="-4"])',
      )
      .click();
    await expect(
      page.getByTestId("assessment-round-complete-btn"),
    ).toBeEnabled({ timeout: 10000 });
    // The header average only moves once the debounced PATCH has landed —
    // completing before that would freeze the round under a pending save.
    await expect(
      page.getByTestId("assessment-round-average-score"),
    ).toContainText("4.0", { timeout: 10000 });

    // HRP-376: the kebab completes the round, the button is replaced by a
    // Completed badge and the invitation is revoked.
    const activeTabId = await tabs.nth(1).getAttribute("data-testid");
    const roundId = activeTabId!.replace("assessment-round-tab-", "");
    await page.getByTestId(`assessment-round-kebab-${roundId}`).click();
    await page.getByTestId(`assessment-round-complete-${roundId}`).click();
    await expect(
      page.getByTestId("assessment-round-status-badge"),
    ).toContainText("Completed", { timeout: 10000 });
    await expect(page.getByTestId("assessment-round-complete-btn")).toHaveCount(
      0,
    );
    await expect(
      inviteRow.locator('[data-testid$="-status-badge"]'),
    ).toContainText("Revoked", { timeout: 10000 });

    // Archiving marks the round as excluded from the aggregate.
    await page.getByTestId(`assessment-round-kebab-${roundId}`).click();
    await page.getByTestId(`assessment-round-archive-${roundId}`).click();
    await expect(
      page.getByTestId("assessment-round-excluded-note"),
    ).toBeVisible({
      timeout: 10000,
    });

    // …and Restore brings it back to Completed, not to in-progress.
    await page.getByTestId(`assessment-round-kebab-${roundId}`).click();
    await page.getByTestId(`assessment-round-restore-${roundId}`).click();
    await expect(
      page.getByTestId("assessment-round-status-badge"),
    ).toContainText("Completed", { timeout: 10000 });
  });
});
