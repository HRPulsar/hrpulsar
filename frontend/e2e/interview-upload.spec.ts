/**
 * HRP-202 — Interview upload + lifecycle happy path.
 *
 * Acceptance: a recruiter can attach a candidate to a vacancy, schedule
 * an interview from the candidate card, paste a text transcript when
 * no media is available, and archive / restore the row.
 *
 * The chunked-upload + player paths are covered by the unit suite
 * (mocked S3) because real S3 round-trips aren't part of the CI
 * environment.
 *
 * Requires E2E_MODE=true on the backend (registerUser uses
 * /auth/dev/auto-register).
 */
import { test, expect } from "./fixtures";
import { registerUser, setAuthTokens } from "./helpers";

const API_BASE = "http://localhost:8100/api";

interface CreatedSetup {
  candidateId: string;
  vacancyId: string;
  cvId: string;
}

async function createSetup(
  page: import("@playwright/test").Page,
  accessToken: string,
): Promise<CreatedSetup> {
  const authHeader = { Authorization: `Bearer ${accessToken}` };
  const vacancyResp = await page.request.post(
    `${API_BASE}/recruitment/vacancies`,
    {
      headers: authHeader,
      data: { title: `Interview Vacancy ${Date.now()}` },
    },
  );
  if (!vacancyResp.ok()) {
    throw new Error(
      `createVacancy failed (${vacancyResp.status()}): ${await vacancyResp.text()}`,
    );
  }
  const vacancy = await vacancyResp.json();

  const candResp = await page.request.post(
    `${API_BASE}/recruitment/candidates`,
    {
      headers: authHeader,
      data: {
        first_name: "HRP",
        last_name: `Two-O-Two ${Date.now()}`,
        email: `cand-${Date.now()}@test.com`,
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
      headers: authHeader,
      data: {
        candidate_id: candidate.id,
        vacancy_id: vacancy.id,
      },
    },
  );
  if (!cvResp.ok()) {
    throw new Error(
      `attachCandidate failed (${cvResp.status()}): ${await cvResp.text()}`,
    );
  }
  const cv = await cvResp.json();
  return { candidateId: candidate.id, vacancyId: vacancy.id, cvId: cv.id };
}

test.describe("Recruitment interview upload (HRP-202)", () => {
  // HRP-202 REDO restored the candidate-card surface: the Interviews
  // section (list + schedule + bulk upload) lives on the candidate page
  // again, and each row links to /recruitment/interviews/{id}. This spec
  // covers schedule via API, the detail page, text transcript paste and
  // archive/restore; the candidate-card section has its own test below.
  test("schedule + paste text transcript + archive/restore", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const setup = await createSetup(page, admin.accessToken);
    const authHeader = { Authorization: `Bearer ${admin.accessToken}` };

    // Schedule an interview on the candidate-vacancy link.
    const ivResp = await page.request.post(
      `${API_BASE}/recruitment/candidate-vacancies/${setup.cvId}/interviews`,
      {
        headers: authHeader,
        data: { title: "Tech screen", duration_minutes: 45 },
      },
    );
    expect(ivResp.ok()).toBeTruthy();
    const interview = await ivResp.json();

    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    await page.goto(`/recruitment/interviews/${interview.id}`);
    await expect(
      page.getByTestId("recruitment-interview-detail"),
    ).toBeVisible({ timeout: 15000 });

    // Paste a text transcript (the no-media path HRP-202 shipped).
    await page.getByTestId("recruitment-interview-btn-paste-text").click();
    const dialog = page.getByTestId(
      "recruitment-interview-text-transcript-dialog",
    );
    await expect(dialog).toBeVisible();
    await dialog
      .getByTestId("recruitment-interview-input-paste-text")
      .fill(
        "Interviewer: welcome to the tech screen.\n" +
          "Candidate: thanks, happy to walk through my experience.",
      );
    await dialog
      .getByTestId("recruitment-interview-btn-save-text-transcript")
      .click();
    await expect(dialog).toBeHidden({ timeout: 10000 });

    // Transcript renders on the detail page.
    await expect(
      page.getByTestId("recruitment-interview-transcript"),
    ).toBeVisible({ timeout: 15000 });
    await expect(
      page.getByText("happy to walk through my experience", { exact: false }),
    ).toBeVisible();

    // Archive → restore lifecycle.
    const archResp = await page.request.post(
      `${API_BASE}/recruitment/interviews/${interview.id}/archive`,
      { headers: authHeader },
    );
    expect(archResp.ok()).toBeTruthy();
    const listArchived = await page.request.get(
      `${API_BASE}/recruitment/candidate-vacancies/${setup.cvId}/interviews`,
      { headers: authHeader },
    );
    expect((await listArchived.json()).length).toBe(0);

    const restResp = await page.request.post(
      `${API_BASE}/recruitment/interviews/${interview.id}/restore`,
      { headers: authHeader },
    );
    expect(restResp.ok()).toBeTruthy();
    const listRestored = await page.request.get(
      `${API_BASE}/recruitment/candidate-vacancies/${setup.cvId}/interviews`,
      { headers: authHeader },
    );
    expect((await listRestored.json()).length).toBe(1);

    // The detail page still renders after the round-trip.
    await page.reload();
    await expect(
      page.getByTestId("recruitment-interview-detail"),
    ).toBeVisible({ timeout: 15000 });
  });

  // HRP-202 REDO: the candidate card hosts an Interviews section again —
  // rounds list, Schedule dialog, consent banner and the multi-file
  // upload dropzone (chunked upload itself is unit-tested with mock S3).
  test("candidate card interviews section: list, schedule, consent gate", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const setup = await createSetup(page, admin.accessToken);
    const authHeader = { Authorization: `Bearer ${admin.accessToken}` };

    // One pre-existing round created through the API.
    const ivResp = await page.request.post(
      `${API_BASE}/recruitment/candidate-vacancies/${setup.cvId}/interviews`,
      {
        headers: authHeader,
        data: { title: "Screening call", duration_minutes: 30 },
      },
    );
    expect(ivResp.ok()).toBeTruthy();
    const interview = await ivResp.json();

    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    await page.goto(`/recruitment/candidates/${setup.candidateId}`);

    const section = page.getByTestId(
      "recruitment-candidate-interviews-section",
    );
    await expect(section).toBeVisible({ timeout: 15000 });

    // Existing round is listed with a working detail link.
    await expect(
      section.getByTestId(
        `recruitment-candidate-interview-row-${interview.id}`,
      ),
    ).toBeVisible({ timeout: 15000 });

    // HRP-418: the count sits in the block header, the row carries a
    // status chip and the "Interview N · added yyyy-mm-dd" meta line.
    await expect(
      section.getByTestId("recruitment-candidate-interviews-count"),
    ).toHaveText("(1)");
    await expect(
      section.getByTestId(
        `recruitment-candidate-interview-status-${interview.id}`,
      ),
    ).toBeVisible();
    await expect(
      section.getByTestId(
        `recruitment-candidate-interview-meta-${interview.id}`,
      ),
    ).toContainText("added");

    // No signed consent yet → banner explains why uploads are locked.
    await expect(
      section.getByTestId("recruitment-candidate-interviews-consent-banner"),
    ).toBeVisible();
    await expect(
      section.getByTestId("recruitment-candidate-interviews-dropzone"),
    ).toBeVisible();

    // Schedule a second round through the dialog.
    await section
      .getByTestId("recruitment-candidate-interviews-schedule-btn")
      .click();
    const dialog = page.getByTestId(
      "recruitment-candidate-interviews-schedule-dialog",
    );
    await expect(dialog).toBeVisible();
    await dialog
      .getByTestId("recruitment-candidate-interviews-schedule-title")
      .fill("Final round");
    await dialog
      .getByTestId("recruitment-candidate-interviews-schedule-save")
      .click();
    await expect(dialog).toBeHidden({ timeout: 10000 });
    await expect(section.getByText("Final round")).toBeVisible({
      timeout: 15000,
    });

    // HRP-386: the newest card lands at the TOP of the list.
    const rows = section.locator(
      '[data-testid^="recruitment-candidate-interview-row-"]',
    );
    await expect(rows.first()).toContainText("Final round");

    // HRP-418: the kebab offers Edit + Archive; archiving hides the row
    // until "Show archived" is ticked, and Restore brings it back.
    await section
      .getByTestId(`recruitment-candidate-interview-menu-${interview.id}`)
      .click();
    await page
      .getByTestId(`recruitment-candidate-interview-archive-${interview.id}`)
      .click();
    await page
      .getByTestId("recruitment-candidate-interviews-archive-confirm-confirm")
      .click();
    await expect(
      section.getByTestId(
        `recruitment-candidate-interview-row-${interview.id}`,
      ),
    ).toBeHidden({ timeout: 15000 });

    await section
      .getByTestId("recruitment-candidate-interviews-show-archived")
      .click();
    await expect(
      section.getByTestId(
        `recruitment-candidate-interview-row-${interview.id}`,
      ),
    ).toBeVisible({ timeout: 15000 });

    // HRP-418 / HRP-387: the title itself is the link to the detail page.
    await section
      .getByTestId(`recruitment-candidate-interview-title-${interview.id}`)
      .click();
    await expect(
      page.getByTestId("recruitment-interview-detail"),
    ).toBeVisible({ timeout: 15000 });

    // HRP-387: the detail page renders Details + Notes blocks.
    await expect(
      page.getByTestId("recruitment-interview-details"),
    ).toBeVisible();
    await expect(page.getByTestId("recruitment-interview-notes")).toBeVisible();
    await expect(page.getByTestId("recruitment-interview-title")).toHaveText(
      "Screening call",
    );
  });
});
