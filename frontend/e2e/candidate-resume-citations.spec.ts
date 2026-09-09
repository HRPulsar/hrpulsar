import { test, expect } from "./fixtures";

import { API_BASE, SAAS_E2E } from "./helpers";

/**
 * HRP-680 — the resume citation link, both ways.
 *
 * A citation chip in AI Insights points at the resume item it was taken
 * from, and that item points back at the chip. One direction working is
 * not the feature: the recruiter reads a claim, jumps to the evidence,
 * and jumps back to the claim it supported.
 *
 * The fixture is the demo sandbox rather than API seeding, deliberately.
 * Citations live on a completed `AIAnalysisRun` in `resume_only` mode
 * together with a parsed resume the excerpts can match against; the
 * E2E_MODE `_test/seed-verdict` shortcut writes the verdict columns on
 * `CandidateVacancy` and nothing else — no run row, no `resume_excerpts`,
 * so the chips never render. The demo seed is the only fixture in the
 * product that produces the whole pair (HRP-680 added it for exactly this
 * reason), and it costs one API call.
 *
 * Requires DEPLOYMENT_MODE=saas on backend + frontend + Playwright and
 * DEMO_ENABLED=true on the backend; skips when the pool is unavailable,
 * mirroring demo-persona.spec.ts.
 */

test.skip(!SAAS_E2E, "demo sandbox endpoints only exist in saas mode");

// The seed's one resume-only candidate: no interview, so a full run has
// nothing to read and the resume-only run is the active one.
const CITED_CANDIDATE_EMAIL = "priya.shah@example.com";

test.describe("HRP-680 — resume citations link both ways", () => {
  test("chip focuses the resume item, and the item focuses the chip", async ({
    page,
  }) => {
    const start = await page.request.post(`${API_BASE}/demo/start`, {
      data: {},
    });
    test.skip(start.status() === 503, "demo sandbox disabled on this stack");
    expect(start.ok(), `demo/start failed: ${start.status()}`).toBeTruthy();
    const { access_token } = await start.json();
    const headers = { Authorization: `Bearer ${access_token}` };

    // Resolve the candidate by email — the ids are minted per sandbox and
    // the display name is seed content, not a contract.
    const found = await page.request.get(
      `${API_BASE}/recruitment/candidates?q=${encodeURIComponent(CITED_CANDIDATE_EMAIL)}`,
      { headers },
    );
    expect(found.ok(), `candidate lookup failed: ${found.status()}`).toBeTruthy();
    const { items } = await found.json();
    expect(
      items.length,
      `demo seed must ship the resume-only candidate ${CITED_CANDIDATE_EMAIL}`,
    ).toBe(1);
    const candidateId: string = items[0].id;

    const links = await page.request.get(
      `${API_BASE}/recruitment/candidates/${candidateId}/vacancies`,
      { headers },
    );
    expect(links.ok(), `vacancy lookup failed: ${links.status()}`).toBeTruthy();
    const vacancies = await links.json();
    expect(vacancies.length, "the candidate must sit on a vacancy").toBeGreaterThan(0);
    const vacancyId: string = vacancies[0].vacancy_id;

    // Mirror lib/demo.ts::persistDemoSession — same dance as demo-persona.
    await page.goto("/login");
    await page.evaluate((token: string) => {
      localStorage.setItem("access_token", token);
      localStorage.removeItem("refresh_token");
      document.cookie = "has_token=1; path=/; SameSite=Lax";
      document.cookie = "demo_session=1; path=/; SameSite=Lax";
    }, access_token);

    await page.goto(
      `/recruitment/candidates/${candidateId}?vacancyId=${vacancyId}`,
    );

    const resumeCard = page.getByTestId("candidate-card-section-resume");
    await expect(resumeCard).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId("ai-analysis-resume-excerpts")).toBeVisible({
      timeout: 30000,
    });

    // The chips and the marked resume items are the two halves of one
    // pair — neither exists without the other.
    const chips = page.locator(
      '[data-testid^="ai-analysis-resume-excerpt-experience-"]',
    );
    await expect(chips.first()).toBeVisible({ timeout: 15000 });
    const citedItems = resumeCard.locator('[data-resume-cited="true"]');
    await expect(citedItems.first()).toBeVisible({ timeout: 15000 });

    // --- Forward leg: chip → resume item -------------------------------
    // HRP-680 (redo): the chip marks the words it quoted, inside the one
    // entry it came from. Nothing is marked before the click — the card
    // used to open with every cited entry washed over, which is what made
    // the click's own target indistinguishable from its neighbours.
    await expect(resumeCard.locator("mark")).toHaveCount(0);
    await chips.first().click();
    const marked = resumeCard.locator("[data-resume-item-key] mark");
    await expect(marked).toHaveCount(1, { timeout: 5000 });

    // --- Return leg: resume item → chip --------------------------------
    // The chip the item was marked with picks up `data-focused` for the
    // same 2 s window, so the recruiter sees which claim it supported.
    await citedItems.first().click();
    await expect(
      page.locator(
        '[data-testid^="ai-analysis-resume-excerpt-"][data-focused="true"]',
      ),
    ).toHaveCount(1, { timeout: 5000 });
  });
});
