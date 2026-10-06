// HRP-830: recruitment follows the tenant's matrix. `manage` runs hiring -
// vacancies, candidates, interviews, AI analyses, reports - for the whole
// workspace; below it the hiring manager evaluates and the manager runs
// hiring rounds on the vacancies in their scope. The settings stay the
// admin role's, GDPR and the audit log admin's and hr's.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (rel: string) => readFileSync(resolve(__dirname, rel), "utf8");
const permissions = read("../hooks/use-permissions.ts");
const requisitions = read("../app/(dashboard)/recruitment/requisitions/page.tsx");
const candidates = read("../app/(dashboard)/recruitment/candidates/page.tsx");
const vacancyPage = read("../app/(dashboard)/recruitment/requisitions/[id]/page.tsx");
const candidatePage = read("../app/(dashboard)/recruitment/candidates/[id]/page.tsx");
const table = read("../components/recruitment/vacancy-candidates-table.tsx");
const questionSets = read("../components/recruitment/interview-question-sets.tsx");
const rounds = read("../components/recruitment/manager-assessment-section.tsx");
const canvas = read("../components/recruitment/canvas/canvas-grid.tsx");
const tabs = read("../components/recruitment/recruitment-tabs.tsx");
const coverage = read("../app/(dashboard)/coverage/[id]/page.tsx");

describe("recruitment follows the section level (HRP-830)", () => {
  it("mirrors the backend guards in the hook", () => {
    // `evaluates` / `runs_rounds` in recruitment/routers/common.py.
    expect(permissions).toMatch(
      /canEvaluateCandidates:\s*sections\.recruitment === "manage" \|\|\s*\(isHiringManager && Boolean\(sections\.recruitment\)\)/,
    );
    expect(permissions).toMatch(
      /canRunHiringRounds:\s*sections\.recruitment === "manage" \|\|\s*\(isManager && Boolean\(sections\.recruitment\)\)/,
    );
    // An unrestricted RecruitmentScope.
    expect(permissions).toContain(
      'seesAllHiring: holdsAdminLevel(roles) || sections.recruitment === "manage",',
    );
    // The role list the sidebar and the layout used is gone - the matrix
    // opens the section.
    expect(permissions).not.toContain("canRecruit");
  });

  it("runs hiring at manage, not by the admin/manager flag", () => {
    for (const page of [requisitions, candidates]) {
      expect(page).toContain('const canManage = usePermissions().canManageSection("recruitment");');
    }
    expect(vacancyPage).toMatch(/const canEdit =\s*canManageSection\("recruitment"\) &&/);
    expect(vacancyPage).toMatch(/\{canManageSection\("recruitment"\) && \(\s*<VacancyActionsMenu/);
    expect(table).toContain("canRemove={canManage}");
    expect(table).toMatch(/\{canManage && \(\s*<BulkAnalyzeBar/);
    expect(candidatePage).toContain('const insightsSection = canManageSection("recruitment") && (');
    expect(coverage).toContain('const canRunHiring = usePermissions().canManageSection("recruitment");');
  });

  it("keeps evaluation and rounds with their roles at view", () => {
    // HRP-836: a closed or cancelled vacancy freezes its funnel on top.
    expect(table).toContain("const canMoveStage = canEvaluateCandidates && !readOnly;");
    expect(questionSets).toContain("readOnly={!canEvaluate || currentSet.status === \"sample\"}");
    expect(canvas).toContain("const canScore = Boolean(inviteToken) || canEvaluateCandidates;");
    // HRP-836: the vacancy's status freezes its rounds on top of the role.
    expect(rounds).toContain("const { canRunHiringRounds } = usePermissions();");
    expect(rounds).toContain(
      "const canRunRounds = canRunHiringRounds && !activeVacancy?.read_only;",
    );
    expect(rounds).toContain("disabled={roundClosed || !canRunRounds}");
    // Mirrors resolve_user_role: the full payload wins before the slice.
    expect(candidatePage).toContain(
      '(user?.roles ?? []).includes("hiring_manager") && !seesAllHiring;',
    );
  });

  it("leaves the settings to admin and the audit log to admin and hr", () => {
    expect(tabs).toContain("if (tab.adminOnly) return isAdmin;");
    expect(tabs).toContain("if (tab.auditRoles) return isAdmin || isHr;");
    expect(read("../app/(dashboard)/recruitment/settings/layout.tsx")).toContain(
      "<RequireRole admin>",
    );
    expect(read("../app/(fullscreen)/recruitment/layout.tsx")).toContain(
      '<RequireSection code="recruitment">',
    );
    for (const route of ["requisitions/new", "requisitions/[id]/edit", "candidates/new"]) {
      expect(read(`../app/(dashboard)/recruitment/${route}/layout.tsx`)).toContain(
        '<RequireSection code="recruitment" level="manage">',
      );
    }
  });
});
