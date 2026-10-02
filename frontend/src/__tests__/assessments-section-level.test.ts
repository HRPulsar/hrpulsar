// HRP-826: running assessments follows the tenant's matrix - `manage` on
// assessments - not the admin / manager role. Every entry into it reads the
// same row: the list, the assessment and mass-assessment pages, and the
// employee card's action and tab. A respondent (`view`) sees neither the
// authoring buttons nor the results the API withholds from them.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (rel: string) => readFileSync(resolve(__dirname, rel), "utf8");
const listPage = read("../app/(dashboard)/assessments/page.tsx");
const assessmentPage = read("../app/(dashboard)/assessments/[id]/page.tsx");
const groupPage = read("../app/(dashboard)/assessment-groups/[id]/page.tsx");
const employeePage = read("../app/(dashboard)/employees/[id]/page.tsx");
const permissions = read("../hooks/use-permissions.ts");

describe("assessments follow the section level (HRP-826)", () => {
  it("gates the section pages on the level, not on a role flag", () => {
    for (const page of [listPage, assessmentPage, groupPage]) {
      expect(page).toContain('const canManage = canManageSection("assessments");');
      expect(page).not.toMatch(/const \{ canManage[ ,]/);
    }
    expect(permissions).not.toContain("canCreateAssessments");
  });

  it("shows detailed results and scores only to who runs assessments", () => {
    expect(assessmentPage).toContain("const canViewDetailedResults = canManage;");
    expect(assessmentPage).toContain("const isPrivileged = canManage;");
    expect(assessmentPage).not.toContain('roles.includes("platform_admin")');
  });

  it("asks the analytics row before offering the CPA round comparison", () => {
    expect(assessmentPage).toContain('{assessment.cpa_id && canViewSection("analytics") && (');
  });

  it("reads each section's own level in the employee card's action menu", () => {
    expect(employeePage).toMatch(
      /canManageSection\("assessments"\) && \(\s*<DropdownMenuItem\s+data-testid="employee-action-create-assessment"/,
    );
    expect(employeePage).toMatch(
      /canManageSection\("development"\) && \(\s*<DropdownMenuItem\s+data-testid="employee-action-development-plan"/,
    );
    expect(employeePage).toMatch(
      /canViewSection\("assessments"\) && \(\s*<TabsTrigger value="assessments"/,
    );
  });
});
