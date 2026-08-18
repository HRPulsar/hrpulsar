import { expect, test } from "./fixtures";
import {
  createDivision,
  createPDP,
  createPosition,
  provisionTenantMember,
  registerUser,
  seedPDPItemWithMaterial,
  setDivisionManager,
} from "./helpers";

const API = "http://localhost:8100/api";

/**
 * Tests for the role-aware list scope introduced alongside
 * `app/core/access_scope.py`. The same tenant is reused across cases:
 *
 *   admin     — fixture from registerUser (admin role, no Employee row)
 *   employee  — invited member with division+position (auto-employee, employee role)
 *   manager   — invited member promoted to division manager
 */
test.describe("Access scope (role-aware list filters)", () => {
  test("admin sees full tenant; employee sees only self; manager sees subtree", async ({
    page,
  }) => {
    // --- Admin tenant setup ---
    const admin = await registerUser(page);
    const adminOpts = { page, accessToken: admin.accessToken };

    const division = await createDivision(adminOpts, "Engineering");
    const position = await createPosition(adminOpts, "Backend Dev");

    // Plain employee (auto-employee row created via invitation w/ division)
    const employee = await provisionTenantMember(adminOpts, {
      roleCode: "employee",
      divisionId: division.id,
      positionId: position.id,
    });
    expect(employee.employeeId).not.toBeNull();

    // Manager: needs to be in the division and promoted via Division.manager_id
    const manager = await provisionTenantMember(adminOpts, {
      roleCode: "employee",
      divisionId: division.id,
      positionId: position.id,
    });
    expect(manager.employeeId).not.toBeNull();
    await setDivisionManager(adminOpts, division.id, manager.employeeId!);

    // --- /api/employees ---
    const list = async (token: string) =>
      page.request
        .get(`${API}/employees?limit=100`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        .then(async (r) => {
          expect(r.ok(), await r.text()).toBeTruthy();
          return r.json() as Promise<{
            items: Array<{ id: string; user_id: string }>;
            total: number;
          }>;
        });

    // Admin sees both (no admin-employee row, but the two members)
    const adminList = await list(admin.accessToken);
    expect(adminList.total).toBeGreaterThanOrEqual(2);
    expect(adminList.items.map((e) => e.id)).toEqual(
      expect.arrayContaining([employee.employeeId, manager.employeeId]),
    );

    // Employee sees only themselves
    const empList = await list(employee.accessToken);
    expect(empList.total).toBe(1);
    expect(empList.items[0].id).toBe(employee.employeeId);

    // Manager sees self + every employee in the managed subtree (= self + employee)
    const mgrList = await list(manager.accessToken);
    expect(mgrList.total).toBe(2);
    expect(mgrList.items.map((e) => e.id)).toEqual(
      expect.arrayContaining([employee.employeeId, manager.employeeId]),
    );
  });

  test("PDP list filters by scope", async ({ page }) => {
    const admin = await registerUser(page);
    const adminOpts = { page, accessToken: admin.accessToken };
    const division = await createDivision(adminOpts, "Ops");
    const position = await createPosition(adminOpts, "SRE");

    const alice = await provisionTenantMember(adminOpts, {
      roleCode: "employee",
      divisionId: division.id,
      positionId: position.id,
    });
    const bob = await provisionTenantMember(adminOpts, {
      roleCode: "employee",
      divisionId: division.id,
      positionId: position.id,
    });

    // Admin creates a PDP for each member and moves them past Draft so
    // non-admin viewers can see them — HRP-19 hides Draft plans from
    // employees / managers.
    const alicePdp = await createPDP(adminOpts, alice.employeeId!);
    const bobPdp = await createPDP(adminOpts, bob.employeeId!);
    for (const pdp of [alicePdp, bobPdp]) {
      await seedPDPItemWithMaterial(adminOpts, pdp.id);
      await page.request.post(`${API}/pdp/${pdp.id}/status`, {
        headers: { Authorization: `Bearer ${admin.accessToken}` },
        data: { status_code: "sent" },
      });
    }

    const listPdp = async (token: string) =>
      page.request
        .get(`${API}/pdp`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        .then(async (r) => {
          expect(r.ok(), await r.text()).toBeTruthy();
          return r.json() as Promise<Array<{ id: string }>>;
        });

    expect((await listPdp(admin.accessToken)).map((p) => p.id)).toEqual(
      expect.arrayContaining([alicePdp.id, bobPdp.id]),
    );
    const aliceView = await listPdp(alice.accessToken);
    expect(aliceView.map((p) => p.id)).toEqual([alicePdp.id]);
  });

  test("/api/exams 403s when caller asks for another employee's id", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const adminOpts = { page, accessToken: admin.accessToken };
    const division = await createDivision(adminOpts, "Sales");
    const position = await createPosition(adminOpts, "AE");

    const alice = await provisionTenantMember(adminOpts, {
      roleCode: "employee",
      divisionId: division.id,
      positionId: position.id,
    });
    const bob = await provisionTenantMember(adminOpts, {
      roleCode: "employee",
      divisionId: division.id,
      positionId: position.id,
    });

    // Alice asks for Bob's exams → 403
    const forbidden = await page.request.get(
      `${API}/exams?employee_id=${bob.employeeId}`,
      { headers: { Authorization: `Bearer ${alice.accessToken}` } },
    );
    expect(forbidden.status()).toBe(403);

    // Alice asks for own exams → 200
    const allowed = await page.request.get(
      `${API}/exams?employee_id=${alice.employeeId}`,
      { headers: { Authorization: `Bearer ${alice.accessToken}` } },
    );
    expect(allowed.ok()).toBeTruthy();
  });

  test("talent-market: regular employee only sees published cards", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const adminOpts = { page, accessToken: admin.accessToken };
    const division = await createDivision(adminOpts, "Product");
    const position = await createPosition(adminOpts, "PM");

    const alice = await provisionTenantMember(adminOpts, {
      roleCode: "employee",
      divisionId: division.id,
      positionId: position.id,
    });

    // Admin creates two cards: one stays draft, one is published.
    const draft = await page.request
      .post(`${API}/talent-market`, {
        headers: { Authorization: `Bearer ${admin.accessToken}` },
        data: { title: "Hidden draft", card_type: "vacancy" },
      })
      .then((r) => r.json());
    const pub = await page.request
      .post(`${API}/talent-market`, {
        headers: { Authorization: `Bearer ${admin.accessToken}` },
        data: { title: "Public vacancy", card_type: "vacancy" },
      })
      .then((r) => r.json());
    // HRP-87: publish refuses an empty Required Competences block, so wire one
    // up before publishing. The Required-Competence row needs a competence and
    // a skill level — create the minimal pair via the API.
    const adminHeaders = {
      Authorization: `Bearer ${admin.accessToken}`,
    } as const;
    const group = await page.request
      .post(`${API}/competence-groups`, {
        headers: adminHeaders,
        data: { title: `Pub-grp-${Date.now()}` },
      })
      .then((r) => r.json());
    const competence = await page.request
      .post(`${API}/competences`, {
        headers: adminHeaders,
        data: { title: `Pub-comp-${Date.now()}`, group_id: group.id },
      })
      .then((r) => r.json());
    const skillLevel = await page.request
      .post(`${API}/skill-levels`, {
        headers: adminHeaders,
        data: { title: `Pub-lv-${Date.now()}`, sort_index: 0 },
      })
      .then((r) => r.json());
    const reqResp = await page.request.post(
      `${API}/talent-market/${pub.id}/required-competences`,
      {
        headers: adminHeaders,
        data: {
          items: [
            { competence_id: competence.id, skill_level_id: skillLevel.id },
          ],
          match_percent: 80,
        },
      },
    );
    expect(reqResp.ok(), await reqResp.text()).toBeTruthy();

    // HRP-150: publish also requires at least one Candidate attached to the
    // card. Alice has no done assessments so the HRP-129 auto-pool stays
    // empty — attach her manually before publishing.
    const candResp = await page.request.post(
      `${API}/talent-market/${pub.id}/candidates`,
      {
        headers: adminHeaders,
        data: { employee_id: alice.employeeId },
      },
    );
    expect(candResp.ok(), await candResp.text()).toBeTruthy();

    const publishResp = await page.request.post(
      `${API}/talent-market/${pub.id}/publish`,
      { headers: adminHeaders },
    );
    expect(publishResp.ok(), await publishResp.text()).toBeTruthy();

    const search = async (token: string) =>
      page.request
        .post(`${API}/talent-market/search`, {
          headers: { Authorization: `Bearer ${token}` },
          data: { skip: 0, limit: 100 },
        })
        .then(async (r) => {
          expect(r.ok(), await r.text()).toBeTruthy();
          return r.json() as Promise<{
            items: Array<{ id: string; is_published: boolean }>;
            total: number;
          }>;
        });

    const adminCards = await search(admin.accessToken);
    expect(adminCards.items.map((c) => c.id)).toEqual(
      expect.arrayContaining([draft.id, pub.id]),
    );

    const aliceCards = await search(alice.accessToken);
    expect(aliceCards.items.map((c) => c.id)).toEqual([pub.id]);
    expect(aliceCards.items[0].is_published).toBe(true);
  });
});

