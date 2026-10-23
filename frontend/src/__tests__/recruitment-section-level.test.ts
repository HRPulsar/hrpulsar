// HRP-830: recruitment follows the tenant's matrix. `manage` runs hiring -
// vacancies, candidates, interviews, AI analyses, reports - for the whole
// workspace; below it the hiring manager evaluates and the manager runs
// hiring rounds on the vacancies in their scope. The settings tabs follow
// their APIs' audiences (HRP-1045); GDPR and the audit log stay admin's
// and hr's.

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
    // An unrestricted RecruitmentScope (UNRESTRICTED_ROLE_CODES, HRP-830 REDO).
    expect(permissions).toContain("seesAllHiring: holdsAdminLevel(roles) || isRecruiter,");
    // The role list the sidebar and the layout used is gone - the matrix
    // opens the section.
    expect(permissions).not.toContain("canRecruit");
  });

  it("runs hiring at manage, not by the admin/manager flag", () => {
    expect(requisitions).toContain('const canManage = usePermissions().canManageSection("recruitment");');
    expect(candidates).toContain('const canManage = canManageSection("recruitment");');
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
    // HRP-630: writing questions is `manage`; the hiring manager exports.
    expect(questionSets).toContain('const canEvaluate = canExport && canManageSection("recruitment");');
    expect(canvas).toContain("const canScore = Boolean(inviteToken) || canEvaluateCandidates;");
    // HRP-836: the vacancy's status freezes its rounds on top of the role.
    expect(rounds).toContain(
      "const canManageRounds = canManageRecruitment && !activeVacancy?.read_only;",
    );
    // HRP-630: one's own sheet is filled in at any level; the rest of the
    // round is `manage`'s (HRP-629).
    expect(rounds).toContain("const canFillSheet = !activeVacancy?.read_only;");
    expect(rounds).toContain("disabled={roundClosed || !canFillSheet}");
    // Mirrors resolve_user_role: the full payload wins before the slice.
    expect(candidatePage).toContain(
      '!(seesAllHiring || canManageSection("recruitment"));',
    );
  });

  // HRP-1045: the settings follow the audiences their APIs already admit.
  it("opens each settings tab to its API's audience", () => {
    expect(tabs).toContain(
      'return isAdmin || isHr || canManageSection("recruitment");',
    );
    expect(tabs).toContain("if (tab.auditRoles) return isAdmin || isHr;");
    expect(read("../app/(dashboard)/recruitment/settings/layout.tsx")).toContain(
      "<RequireRecruitmentSettings>",
    );
    // Retention and roles read as admin | hr; providers stay admin-only;
    // branding and consent templates read as `manage` or admin; the
    // hiring-round scales keep their own `manage` gate.
    for (const route of ["retention", "roles"]) {
      expect(
        read(`../app/(dashboard)/recruitment/settings/${route}/layout.tsx`),
      ).toContain("<RequireAdminOrHr>");
    }
    for (const route of ["llm-providers", "transcription-providers"]) {
      expect(
        read(`../app/(dashboard)/recruitment/settings/${route}/layout.tsx`),
      ).toContain("<RequireRole admin>");
    }
    for (const route of ["branding", "consent-templates"]) {
      expect(
        read(`../app/(dashboard)/recruitment/settings/${route}/layout.tsx`),
      ).toContain("<RequireReadsHiringSettings>");
    }
    expect(
      read("../app/(dashboard)/recruitment/settings/scales/layout.tsx"),
    ).toContain('<RequireSection code="recruitment" level="manage">');
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
