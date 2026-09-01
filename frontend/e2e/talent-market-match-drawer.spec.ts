import { test, expect } from "./fixtures";
import {
  registerUser,
  setAuthTokens,
  createDictionaryItem,
  createCompetenceGroup,
  createCompetence,
  createIndicator,
  pickFirstSkillLevel,
} from "./helpers";

const API_BASE = "http://localhost:8100/api";

// HRP-172 redo: the breakdown drawer surfaces the level percent per
// required competence and stays scrollable when the requirement list
// overflows the viewport.
// HRP-657: the click target grew back to the whole Match cell. The
// chips-inert rule from HRP-172 hid the affordance — operators read the
// coloured chips as a static readout and never reached the explanation.
// The chevron is now the trailing icon of that one button and keeps the
// `-match-trigger` testid, so the click path below is unchanged.
test.describe("HRP-172 redo: Talent Market match drawer", () => {
  let accessToken: string;
  let refreshToken: string;
  let cardId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const reg = await registerUser(page);
    accessToken = reg.accessToken;
    refreshToken = reg.refreshToken;
    const opts = { page, accessToken };
    const headers = { Authorization: `Bearer ${accessToken}` };
    const stamp = Date.now().toString(36);

    await createDictionaryItem(opts, "specialization", `TM-spec-${stamp}`);
    await createDictionaryItem(opts, "grade", `TM-grade-${stamp}`);
    const group = await createCompetenceGroup(opts, `TM-grp-${stamp}`);
    const comp = await createCompetence(opts, group.id, `TM-comp-${stamp}`);
    const level = await pickFirstSkillLevel(opts);
    await createIndicator(opts, comp.id, "Basic indicator", level.id);

    // Invite + accept to land a second user in the same tenant, then
    // wrap them in an employee row so the candidate picker can attach
    // them to the talent-market card.
    const inv = await page.request.post(`${API_BASE}/invitations`, {
      headers,
      data: {
        email: `member-${stamp}@test.com`,
        name: "Pool Member",
        role_code: "employee",
      },
    });
    if (!inv.ok()) throw new Error(`invite failed: ${await inv.text()}`);
    const invJson = await inv.json();
    const token = await page.request.get(
      `${API_BASE}/auth/dev/invitations/${invJson.id}/token`,
      { headers },
    );
    if (!token.ok()) throw new Error(`token reveal failed: ${await token.text()}`);
    const { token: invToken } = await token.json();
    const accept = await page.request.post(`${API_BASE}/auth/accept-invite`, {
      data: {
        token: invToken,
        password: "memberpass123",
        first_name: "Pool",
        last_name: "Member",
      },
    });
    if (!accept.ok()) throw new Error(`accept failed: ${await accept.text()}`);
    const accepted = await accept.json();

    const empResp = await page.request.post(`${API_BASE}/employees`, {
      headers,
      data: {
        user_id: accepted.user.id,
        position_title: "TM Pool",
        hire_date: "2024-01-15",
      },
    });
    if (!empResp.ok()) throw new Error(`emp create failed: ${await empResp.text()}`);
    const emp = await empResp.json();

    const cardResp = await page.request.post(`${API_BASE}/talent-market`, {
      headers,
      data: {
        title: `TM-card-${stamp}`,
        description: "Card with one required competence",
        card_type: "vacancy",
        start_date: "2026-01-01",
        end_date: "2026-12-31",
        match_percent: 60,
      },
    });
    if (!cardResp.ok()) throw new Error(`card create failed: ${await cardResp.text()}`);
    const card = await cardResp.json();
    cardId = card.id;
    const reqResp = await page.request.post(
      `${API_BASE}/talent-market/${cardId}/required-competences`,
      {
        headers,
        data: {
          items: [{ competence_id: comp.id, skill_level_id: level.id }],
        },
      },
    );
    if (!reqResp.ok())
      throw new Error(`required-comp failed: ${await reqResp.text()}`);
    const attach = await page.request.post(
      `${API_BASE}/talent-market/${cardId}/candidates`,
      {
        headers,
        data: { employee_id: emp.id },
      },
    );
    if (!attach.ok()) throw new Error(`attach failed: ${await attach.text()}`);
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("the whole match cell opens the drawer", async ({ page }) => {
    await page.goto(`/talent-market/${cardId}`);
    const trigger = page
      .getByTestId("talent-market-candidate-match-trigger")
      .first();
    await expect(trigger).toBeVisible({ timeout: 10000 });

    await trigger.click();
    await expect(page.getByTestId("talent-market-match-drawer")).toBeVisible({
      timeout: 5000,
    });
    await expect(trigger).toHaveAttribute("aria-pressed", "true");

    await expect(
      page.getByTestId("talent-market-match-drawer-competences"),
    ).toBeVisible();
    await expect(
      page
        .getByTestId("talent-market-match-drawer-competence-percent")
        .first(),
    ).toBeVisible();
    // HRP-657: the verdict states in words why this candidate does or
    // does not match, so the operator does not decode chip colours.
    await expect(
      page.getByTestId("talent-market-match-drawer-verdict"),
    ).toBeVisible();
  });

  test("clicking the competence chip opens the drawer too", async ({
    page,
  }) => {
    // HRP-657: the chips used to be deliberately inert. They are inside
    // the trigger button now — a click anywhere on the indicator explains
    // the verdict.
    await page.goto(`/talent-market/${cardId}`);
    const chip = page
      .getByTestId("talent-market-candidate-match-competence")
      .first();
    await expect(chip).toBeVisible({ timeout: 10000 });
    await chip.click();
    await expect(page.getByTestId("talent-market-match-drawer")).toBeVisible({
      timeout: 5000,
    });
  });

  test("the gap plan is created from the drawer", async ({ page }) => {
    // HRP-665: the employee has no Done assessment on the required
    // competence, so it is a gap and the plan action is offered.
    await page.goto(`/talent-market/${cardId}`);
    const trigger = page
      .getByTestId("talent-market-candidate-match-trigger")
      .first();
    await expect(trigger).toBeVisible({ timeout: 10000 });
    await trigger.click();

    const createPlan = page.getByTestId(
      "talent-market-match-drawer-create-plan",
    );
    await expect(createPlan).toBeVisible({ timeout: 5000 });
    await createPlan.click();

    // The row picks up the plan badge once the card reloads.
    await expect(
      page.getByTestId("talent-market-candidate-plan").first(),
    ).toBeVisible({ timeout: 10000 });
  });
});
