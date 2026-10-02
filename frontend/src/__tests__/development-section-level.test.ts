// HRP-825: authoring a development plan follows the tenant's matrix -
// `manage` on development - not the admin / manager role. Every entry into
// authoring reads the same row: the section's own pages, "Create plan" on an
// assessment, and the employee card's plan button and tab.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (rel: string) => readFileSync(resolve(__dirname, rel), "utf8");
const listPage = read("../app/(dashboard)/development/page.tsx");
const planPage = read("../app/(dashboard)/development/[id]/page.tsx");
const assessmentPage = read("../app/(dashboard)/assessments/[id]/page.tsx");
const employeePage = read("../app/(dashboard)/employees/[id]/page.tsx");

describe("development plans follow the section level (HRP-825)", () => {
  it("gates authoring on the section pages on the level, not on a role flag", () => {
    for (const page of [listPage, planPage]) {
      expect(page).toContain('const canManage = canManageSection("development");');
      expect(page).not.toMatch(/const \{ canManage[ ,]/);
    }
  });

  it("offers the full status graph only to who runs plans, as the API does", () => {
    expect(planPage).toContain("const runsPlans = canManage || adminTier;");
    expect(planPage).toMatch(/: runsPlans\s*\? pdpNextStatuses\(pdp\.status\)\s*: \[\];/);
  });

  it("offers Create plan from an assessment only to who may author one", () => {
    expect(assessmentPage).toMatch(
      /canManageSection\("development"\) && \(\s*<Button[^>]*\s+data-testid="assessment-create-plan"/,
    );
  });

  it("reads the level on the employee card's plan button and tab", () => {
    expect(employeePage).toMatch(
      /canManageSection\("development"\) && \([\s\S]{0,400}employee-competences-btn-development-plan/,
    );
    expect(employeePage).toMatch(
      /canViewSection\("development"\) && \(\s*<TabsTrigger value="development"/,
    );
  });
});
