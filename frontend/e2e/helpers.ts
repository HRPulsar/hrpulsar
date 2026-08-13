import { expect, test, Page } from "@playwright/test";

/**
 * Backend API root.
 *
 * Defaults to the standard local/CI stack. `E2E_API_BASE` overrides it so a
 * git worktree can be driven on its own ports (scripts/new-worktree.sh gives
 * every branch a deterministic offset) without two branches racing for 8100
 * — and, worse, one branch's specs silently writing into the other's database.
 */
export const API_BASE =
  process.env.E2E_API_BASE ?? "http://localhost:8100/api";

// ---------------------------------------------------------------------------
// Unique generators
// ---------------------------------------------------------------------------

/** Generate a unique email for test isolation. */
export function uniqueEmail(): string {
  return `e2e-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@test.com`;
}

/**
 * Deployment mode this e2e run targets (HRP-390). Mirrors the backend's
 * DEPLOYMENT_MODE: monorepo CI exports saas, community/public CI runs
 * onprem (see ci.yml "Set deployment mode"); local runs must export the
 * same value to Playwright as the servers use. Mode-dependent specs gate
 * themselves on this flag — in onprem /register renders the self-serve
 * form instead of the moderated funnel. (Marketing-home specs moved to
 * marketing/e2e with HRP-389 — the product frontend serves no landing.)
 */
export const SAAS_E2E = process.env.DEPLOYMENT_MODE === "saas";

/** i18n F7 (HRP-481): CI runs the multi-locale deployment shape
 * (AVAILABLE_LOCALES=de,en on servers AND the Playwright process).
 * Locale-select/switcher assertions gate on this flag so a local run
 * against a single-locale stack skips them instead of failing. */
export const MULTI_LOCALE_E2E =
  (process.env.AVAILABLE_LOCALES ?? "").split(",").filter(Boolean).length > 1;

/**
 * Locales the stand under test actually serves, read from the runtime env
 * script (window.__ENV__) rather than the Playwright process env.
 *
 * Call after a page has loaded — __ENV__ is injected by the app layout.
 */
export async function standAvailableLocales(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const env = (window as unknown as {
      __ENV__?: Record<string, string | undefined>;
    }).__ENV__;
    return (env?.NEXT_PUBLIC_AVAILABLE_LOCALES ?? "")
      .split(",")
      .map((code) => code.trim())
      .filter(Boolean);
  });
}

/**
 * Gate a locale-dependent assertion on the stand, not on hearsay
 * (HRP-511 e).
 *
 * MULTI_LOCALE_E2E only describes the Playwright process. If the frontend
 * was started without NEXT_PUBLIC_AVAILABLE_LOCALES, the flag said
 * "multi-locale" while the switcher was not rendered at all — the specs
 * then failed with a mystery timeout, or (in the mirror case) skipped and
 * reported green while covering nothing. The two must agree; disagreement
 * is a misconfigured stand and is reported as such.
 */
export async function skipUnlessMultiLocaleStand(page: Page): Promise<void> {
  const locales = await standAvailableLocales(page);
  const standIsMultiLocale = locales.length > 1;
  expect(
    standIsMultiLocale,
    `stand serves [${locales.join(",")}] but the Playwright process has ` +
      `AVAILABLE_LOCALES=${process.env.AVAILABLE_LOCALES ?? "<unset>"} — ` +
      "set the same locale list on backend, frontend and Playwright " +
      "(HRP-481 multi-locale contract)",
  ).toBe(MULTI_LOCALE_E2E);
  test.skip(!standIsMultiLocale, "requires AVAILABLE_LOCALES=de,en");
}

// ---------------------------------------------------------------------------
// Auth helpers
// ---------------------------------------------------------------------------

export interface RegisterResult {
  email: string;
  password: string;
  accessToken: string;
  refreshToken: string;
  userId: string;
  tenantId: string;
}

/**
 * Register a new user via the dev auto-register endpoint.
 * Requires E2E_MODE=true on the backend.
 * Creates tenant + user + admin role + auto-verifies email in one step.
 */
export async function registerUser(page: Page): Promise<RegisterResult> {
  const email = uniqueEmail();
  const password = "testpass123";
  const companyName = `E2E Corp ${Date.now()}`;

  const resp = await page.request.post(`${API_BASE}/auth/dev/auto-register`, {
    data: {
      email,
      password,
      first_name: "E2E",
      last_name: "Tester",
      company_name: companyName,
    },
  });

  if (!resp.ok()) {
    const text = await resp.text();
    throw new Error(`registerUser failed (${resp.status()}): ${text}`);
  }

  const data = await resp.json();
  return {
    email,
    password,
    accessToken: data.access_token,
    refreshToken: data.refresh_token,
    userId: data.user.id,
    tenantId: data.user.tenant_id,
  };
}

/**
 * Register a platform admin user.
 * Requires E2E_MODE=true and deployment_mode=saas on backend.
 */
export async function registerPlatformAdmin(page: Page): Promise<RegisterResult> {
  const email = uniqueEmail();
  const password = "testpass123";
  const companyName = `E2E Platform ${Date.now()}`;

  const resp = await page.request.post(
    `${API_BASE}/auth/dev/auto-register?system_role=platform_admin`,
    {
      data: {
        email,
        password,
        first_name: "Platform",
        last_name: "Admin",
        company_name: companyName,
      },
    },
  );

  if (!resp.ok()) {
    const text = await resp.text();
    throw new Error(`registerPlatformAdmin failed (${resp.status()}): ${text}`);
  }

  const data = await resp.json();
  return {
    email,
    password,
    accessToken: data.access_token,
    refreshToken: data.refresh_token,
    userId: data.user.id,
    tenantId: data.user.tenant_id,
  };
}

/** Log in via the UI using data-testid selectors. */
export async function loginViaUI(
  page: Page,
  email: string,
  password: string,
) {
  await page.goto("/login");
  await page.getByTestId("login-input-email").fill(email);
  await page.getByTestId("login-input-password").fill(password);
  await page.getByTestId("login-btn-submit").click();
  await page.waitForURL("**/dashboard", { timeout: 10000 });
}

/** Set auth tokens directly in localStorage (skip UI login). */
export async function setAuthTokens(
  page: Page,
  accessToken: string,
  refreshToken: string,
) {
  await page.goto("/login");
  await page.evaluate(
    ({ at, rt }) => {
      localStorage.setItem("access_token", at);
      localStorage.setItem("refresh_token", rt);
      document.cookie = "has_token=1; path=/; SameSite=Lax";
    },
    { at: accessToken, rt: refreshToken },
  );
}

// ---------------------------------------------------------------------------
// API data helpers — create test entities via API (faster than UI)
// ---------------------------------------------------------------------------

interface ApiHelperOpts {
  page: Page;
  accessToken: string;
}

async function apiPost(
  opts: ApiHelperOpts,
  path: string,
  data: Record<string, unknown>,
) {
  const resp = await opts.page.request.post(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${opts.accessToken}` },
    data,
  });
  if (!resp.ok()) {
    const text = await resp.text();
    throw new Error(`API POST ${path} failed (${resp.status()}): ${text}`);
  }
  return resp.json();
}

/** Complete onboarding for the current tenant. */
export async function completeOnboarding(opts: ApiHelperOpts) {
  return apiPost(opts, "/onboarding/complete", {});
}

/** Create a division. Returns the full division object. */
export async function createDivision(
  opts: ApiHelperOpts,
  name: string,
  parentId?: string,
) {
  return apiPost(opts, "/divisions", {
    name,
    parent_id: parentId ?? null,
  });
}

/** Create an employee. Returns the full employee object. */
export async function createEmployee(
  opts: ApiHelperOpts,
  userId: string,
  positionTitle: string,
  hireDate: string = "2025-01-15",
  divisionId?: string,
  positionId?: string,
) {
  return apiPost(opts, "/employees", {
    user_id: userId,
    position_id: positionId ?? null,
    position_title: positionId ? undefined : positionTitle,
    hire_date: hireDate,
    division_id: divisionId ?? null,
  });
}

/** Create an assessment. Returns the full assessment object. */
export async function createAssessment(
  opts: ApiHelperOpts,
  employeeId: string,
  title: string,
  typeCode: string = "self",
) {
  return apiPost(opts, "/assessments", {
    employee_id: employeeId,
    type_code: typeCode,
    title,
  });
}

/** Create a competence group. Returns the full group object. */
export async function createCompetenceGroup(
  opts: ApiHelperOpts,
  title: string,
  parentId?: string,
) {
  return apiPost(opts, "/competence-groups", {
    title,
    parent_id: parentId ?? null,
  });
}

/** Create a competence. Returns the full competence object. */
export async function createCompetence(
  opts: ApiHelperOpts,
  groupId: string,
  title: string,
) {
  return apiPost(opts, "/competences", {
    title,
    group_id: groupId,
  });
}

/**
 * Seed an origin (tenant_id IS NULL) competence group via the dev-only
 * endpoint. Origin groups are normally produced by AI generation or
 * platform seeds — neither is reachable from Playwright, so HRP-138's
 * "bulk-add button stays hidden on origin groups" path uses this short-cut.
 */
export async function seedOriginGroup(
  opts: ApiHelperOpts,
  title: string,
): Promise<{ id: string; title: string }> {
  const resp = await opts.page.request.post(
    `${API_BASE}/auth/dev/seed-origin-group`,
    {
      headers: { Authorization: `Bearer ${opts.accessToken}` },
      data: { title },
    },
  );
  if (!resp.ok()) {
    throw new Error(
      `seedOriginGroup failed (${resp.status()}): ${await resp.text()}`,
    );
  }
  return resp.json();
}

/** Create a dictionary item (specialization, grade, role, etc.). */
export async function createDictionaryItem(
  opts: ApiHelperOpts,
  itemType: string,
  title: string,
) {
  return apiPost(opts, `/dictionaries/${itemType}`, { title });
}

/** Create an indicator under a competence. Returns the full indicator. */
export async function createIndicator(
  opts: ApiHelperOpts,
  competenceId: string,
  title: string,
  skillLevelId: string,
) {
  return apiPost(opts, `/competences/${competenceId}/indicators`, {
    title,
    skill_level_id: skillLevelId,
    weight: 1,
  });
}

/** Create a material under a competence. Returns the full material. */
export async function createMaterial(
  opts: ApiHelperOpts,
  competenceId: string,
  title: string,
  skillLevelId: string,
) {
  return apiPost(opts, `/competences/${competenceId}/materials`, {
    title,
    skill_level_id: skillLevelId,
  });
}

/** Publish a competence so it can be used in matrices/assessments. */
export async function publishCompetence(
  opts: ApiHelperOpts,
  competenceId: string,
) {
  return apiPost(opts, `/competences/${competenceId}/publish`, {});
}

/** Resolve the first available skill level for the tenant. */
export async function pickFirstSkillLevel(opts: ApiHelperOpts): Promise<{
  id: string;
  title: string;
}> {
  const resp = await opts.page.request.get(`${API_BASE}/skill-levels`, {
    headers: { Authorization: `Bearer ${opts.accessToken}` },
  });
  if (!resp.ok()) {
    throw new Error(`pickFirstSkillLevel failed (${resp.status()})`);
  }
  const levels: { id: string; title: string; sort_index: number }[] =
    await resp.json();
  if (levels.length === 0) {
    throw new Error("no skill levels seeded");
  }
  levels.sort((a, b) => a.sort_index - b.sort_index);
  return { id: levels[0].id, title: levels[0].title };
}

export interface CriteriaFixture {
  specializationId: string;
  specializationTitle: string;
  gradeId: string;
  gradeTitle: string;
  competenceId: string;
  competenceTitle: string;
  skillLevelId: string;
  chainId: string;
}

/**
 * Create a full grade-system fixture wiring a published competence to a
 * specialization+grade pair, suitable for testing target_position criteria.
 */
export async function setupCriteriaFixture(
  opts: ApiHelperOpts,
): Promise<CriteriaFixture> {
  const stamp = Date.now().toString(36);

  const spec = await createDictionaryItem(opts, "specialization", `Spec-${stamp}`);
  const grade = await createDictionaryItem(opts, "grade", `Grade-${stamp}`);

  const group = await createCompetenceGroup(opts, `CritGroup-${stamp}`);
  const comp = await createCompetence(opts, group.id, `CritComp-${stamp}`);

  // Pick the first available skill level (system-wide seed).
  const slResp = await opts.page.request.get(`${API_BASE}/skill-levels`, {
    headers: { Authorization: `Bearer ${opts.accessToken}` },
  });
  if (!slResp.ok()) {
    throw new Error(`/skill-levels failed (${slResp.status()})`);
  }
  const skillLevels: { id: string; title: string; sort_index: number }[] =
    await slResp.json();
  if (skillLevels.length === 0) {
    throw new Error("no skill levels seeded — fixture cannot continue");
  }
  const skillLevelId = skillLevels[0].id;

  // Publish the competence: at least one indicator at that level.
  await createIndicator(opts, comp.id, `Ind-${stamp}`, skillLevelId);

  const chain = await apiPost(opts, "/grade-system/chains", {
    grade_id: grade.id,
    specialization_id: spec.id,
    competence_links: [
      { competence_id: comp.id, skill_level_id: skillLevelId },
    ],
  });

  return {
    specializationId: spec.id,
    specializationTitle: spec.title,
    gradeId: grade.id,
    gradeTitle: grade.title,
    competenceId: comp.id,
    competenceTitle: comp.title,
    skillLevelId,
    chainId: chain.id,
  };
}

/** Create a mass exam. Returns the full exam object. */
export async function createExam(opts: ApiHelperOpts, title: string) {
  return apiPost(opts, "/mass-exams", { title });
}

/** Create a development plan (PDP). Returns the full PDP object. */
export async function createPDP(
  opts: ApiHelperOpts,
  employeeId: string,
  title: string = "E2E Plan",
) {
  return apiPost(opts, "/pdp", { employee_id: employeeId, title });
}

/**
 * HRP-12: a plan can't move past Draft without at least one item carrying
 * at least one material. Tests that drive the lifecycle through ``sent``
 * use this helper to seed the minimum content.
 */
export async function seedPDPItemWithMaterial(
  opts: ApiHelperOpts,
  pdpId: string,
  title: string = "Seed item",
) {
  const item = await apiPost(opts, `/pdp/${pdpId}/items`, { title });
  await apiPost(opts, `/pdp/${pdpId}/items/${item.id}/materials`, {
    title: "Seed material",
    link: "https://example.com",
  });
  return item;
}

/** Create a position. Returns the full position object. */
export async function createPosition(
  opts: ApiHelperOpts,
  title: string,
  extra?: Record<string, unknown>,
) {
  return apiPost(opts, "/positions", { title, ...extra });
}

/** Create an invitation. Returns the full invitation object. */
export async function createInvitation(
  opts: ApiHelperOpts,
  email: string,
  roleCode: string = "employee",
  extra: { division_id?: string; position_id?: string; name?: string } = {},
) {
  const { name, ...rest } = extra;
  return apiPost(opts, "/invitations", {
    email,
    name: name ?? email.split("@")[0],
    role_code: roleCode,
    ...rest,
  });
}

/**
 * Read an invitation's token via the dev reveal endpoint (E2E_MODE only).
 *
 * Stands in for scraping the invitation email — the InvitationRead schema
 * deliberately hides the token from regular clients.
 */
export async function revealInvitationToken(
  opts: ApiHelperOpts,
  invitationId: string,
): Promise<string> {
  const resp = await opts.page.request.get(
    `${API_BASE}/auth/dev/invitations/${invitationId}/token`,
    { headers: { Authorization: `Bearer ${opts.accessToken}` } },
  );
  if (!resp.ok()) {
    throw new Error(
      `dev_get_invitation_token failed (${resp.status()}): ${await resp.text()}`,
    );
  }
  const { token } = await resp.json();
  return token;
}

/**
 * Provision a second user inside the *current* tenant by inviting them and
 * accepting the invitation programmatically. The token is read off the
 * invitation that was just created (tests run with E2E_MODE=true so emails
 * are best-effort and we don't need to scrape an inbox).
 *
 * Returns the new user's tokens + ids so callers can act as that user.
 */
export async function provisionTenantMember(
  opts: ApiHelperOpts,
  params: {
    roleCode: string;
    divisionId?: string;
    positionId?: string;
    firstName?: string;
    lastName?: string;
  },
): Promise<{
  email: string;
  password: string;
  accessToken: string;
  refreshToken: string;
  userId: string;
  tenantId: string;
  employeeId: string | null;
}> {
  const email = uniqueEmail();
  const password = "memberpass123";

  // HRP-195: manager invitations now require a division. Auto-provision a
  // division when the caller asks for role=manager without one so the
  // existing test helper signature still works.
  let divisionId = params.divisionId;
  if (params.roleCode === "manager" && !divisionId) {
    const divResp = await opts.page.request.post(`${API_BASE}/divisions`, {
      headers: { Authorization: `Bearer ${opts.accessToken}` },
      data: { name: `E2E manager div ${Date.now()}` },
    });
    if (!divResp.ok()) {
      throw new Error(
        `provision division failed (${divResp.status()}): ${await divResp.text()}`,
      );
    }
    const div = await divResp.json();
    divisionId = div.id;
  }

  const inv = await createInvitation(opts, email, params.roleCode, {
    division_id: divisionId,
    position_id: params.positionId,
  });

  const token = await revealInvitationToken(opts, inv.id);

  const accept = await opts.page.request.post(
    `${API_BASE}/auth/accept-invite`,
    {
      data: {
        token,
        password,
        first_name: params.firstName ?? "Member",
        last_name: params.lastName ?? email.slice(0, 6),
      },
    },
  );
  if (!accept.ok()) {
    throw new Error(
      `accept_invitation failed (${accept.status()}): ${await accept.text()}`,
    );
  }
  const data = await accept.json();

  // The invitation auto-creates an employee row only when division_id OR
  // position_id is set. Look it up by user_id.
  let employeeId: string | null = null;
  if (divisionId || params.positionId) {
    const empResp = await opts.page.request.get(
      `${API_BASE}/employees?limit=100`,
      {
        headers: { Authorization: `Bearer ${data.access_token}` },
      },
    );
    if (empResp.ok()) {
      const empData = await empResp.json();
      // Member sees only own row under the new scope rule.
      const own = empData.items.find(
        (e: { user_id: string; id: string }) => e.user_id === data.user.id,
      );
      employeeId = own?.id ?? null;
    }
  }

  return {
    email,
    password,
    accessToken: data.access_token,
    refreshToken: data.refresh_token,
    userId: data.user.id,
    tenantId: data.user.tenant_id,
    employeeId,
  };
}

/** Promote an employee to division manager via PUT /api/divisions/{id}. */
export async function setDivisionManager(
  opts: ApiHelperOpts,
  divisionId: string,
  employeeId: string,
) {
  const resp = await opts.page.request.put(
    `${API_BASE}/divisions/${divisionId}`,
    {
      headers: { Authorization: `Bearer ${opts.accessToken}` },
      data: { manager_id: employeeId },
    },
  );
  if (!resp.ok()) {
    throw new Error(
      `setDivisionManager failed (${resp.status()}): ${await resp.text()}`,
    );
  }
  return resp.json();
}

// ---------------------------------------------------------------------------
// Composite setup helpers
// ---------------------------------------------------------------------------

export interface TenantSetup {
  email: string;
  password: string;
  accessToken: string;
  refreshToken: string;
  userId: string;
  tenantId: string;
  divisionId: string;
  employeeId: string;
}

/**
 * Register a user, create a division and employee — everything needed
 * for most test suites. Returns all IDs and tokens.
 */
export async function setupFullTenant(page: Page): Promise<TenantSetup> {
  const reg = await registerUser(page);
  const opts = { page, accessToken: reg.accessToken };

  const division = await createDivision(opts, "Engineering");
  const employee = await createEmployee(
    opts,
    reg.userId,
    "E2E Tester",
    "2025-01-15",
    division.id,
  );

  return {
    ...reg,
    divisionId: division.id,
    employeeId: employee.id,
  };
}
