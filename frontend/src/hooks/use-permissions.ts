"use client";

import { useAuth } from "@/context/auth-context";
import type { SectionCode } from "@/lib/sections";
import { holdsAdminLevel } from "@/lib/user-role-label";

export function usePermissions() {
  const { user } = useAuth();
  const roles = user?.roles ?? [];
  const sections = user?.sections ?? {};

  const isAdmin = roles.includes("admin");
  const isManager = roles.includes("manager");
  const isPlatformAdmin = roles.includes("platform_admin");
  const isHr = roles.includes("hr");
  const isRecruiter = roles.includes("recruiter");
  const isHiringManager = roles.includes("hiring_manager");

  return {
    roles,
    isAdmin,
    isManager,
    isPlatformAdmin,
    isHr,
    isRecruiter,
    isHiringManager,
    /** Admin or Manager */
    canManage: isAdmin || isManager,
    /**
     * HRP-828: mirrors ADMIN_ROLE_CODES in backend/app/core/access_scope.py
     * - the roles whose write scope is the whole workspace rather than a
     * managed subtree, so they alone file a top-level division or a
     * position with no division.
     */
    isAdminLevel: holdsAdminLevel(roles),
    /**
     * HRP-810: Coverage opens by /auth/me, not by a role list - the roles
     * that run it get "manage", anyone who reads at least one process gets
     * "view". Editing one process is that process's `my_access`.
     */
    canViewCoverage: Boolean(user?.sections?.coverage),
    canCreateCoverage: user?.sections?.coverage === "manage",
    /**
     * HRP-820: what /auth/me opened per section. The sidebar and the
     * section gate read these; every section is translated (HRP-821…831),
     * so the role flags above only ever add an admin piece on top.
     */
    canViewSection: (code: SectionCode) => Boolean(sections[code]),
    canManageSection: (code: SectionCode) => sections[code] === "manage",
    /**
     * HRP-623: sees the HR record rather than the directory row. Mirrors
     * ``is_employee_only`` in backend/app/core/access_scope.py, inverted —
     * a wider set here renders columns the API does not send.
     */
    canViewHrData: isAdmin || isPlatformAdmin || isHr || isManager,
    /**
     * HRP-829: the employee list answers full rows rather than the
     * directory - an admin-level role or `manage` on employees. Mirrors
     * `directory` in backend/app/modules/employee/router.py, inverted.
     * `canViewHrData` above stays the role rule of the salary bands and the
     * position / specialization drill-downs.
     */
    canViewEmployeeRecords: holdsAdminLevel(roles) || sections.employees === "manage",
    /**
     * HRP-637: sees a position's grade and specialization — the hiring
     * roles read the pair (a requisition cannot be raised without it),
     * everyone else only while the tenant switched ``directory_show_grades``
     * on. HRP-710: ``/auth/me`` answers this outright via
     * ``can_see_position_grades``; this used to re-derive it from the role
     * list, which is the backend's role set copied out by hand.
     */
    canViewJobProfile: user?.can_view_job_profile === true,
    /**
     * HRP-631: may edit the workspace-wide catalogues still on a role
     * gate — answer scales, and the grade ladder and matrices of a
     * specialization. Those rows carry no owning column, so a division
     * head cannot be scoped to a slice of them and the gate on the API is
     * `admin` / `hr`. A wider set here is a button that lands on 403. The
     * competence catalogue follows its section instead (HRP-827).
     */
    canManageCatalogues: isAdmin || isHr,
    /**
     * HRP-827: deleting from the competence catalogue and generating it
     * with AI stay the admin role's on top of `manage` on competences —
     * authoring alone is `canManageSection("competences")`.
     */
    canAdministerCompetences: isAdmin && sections.competences === "manage",
    /**
     * HRP-632: below `manage` a division head adds personal competence
     * drafts and edits and deletes their own; HR or an admin publishes them.
     * Mirrors `writes_personal_drafts` in
     * backend/app/modules/competence/dependencies.py.
     */
    canDraftCompetences: isManager && sections.competences === "view",
    /**
     * HRP-830: `manage` on recruitment runs hiring (`canManageSection`);
     * below it two roles keep a piece on the vacancies in their scope -
     * the hiring manager evaluates, the manager runs hiring rounds. Mirrors
     * `evaluates` / `runs_rounds` in
     * backend/app/modules/recruitment/routers/common.py.
     */
    canEvaluateCandidates:
      sections.recruitment === "manage" ||
      (isHiringManager && Boolean(sections.recruitment)),
    canRunHiringRounds:
      sections.recruitment === "manage" ||
      (isManager && Boolean(sections.recruitment)),
    /**
     * HRP-830: sees the whole hiring surface and the full AI payload -
     * mirrors an unrestricted `RecruitmentScope` (admin-level or `manage`).
     */
    seesAllHiring: holdsAdminLevel(roles) || sections.recruitment === "manage",
    /** HRP-831: starts an import - `manage` on the import section. */
    canImport: sections.import === "manage",
    /**
     * The admin pieces of the company section - the section-access screen
     * and the company profile - stay the admin role's (HRP-828).
     */
    canAdminister: isAdmin,
    /**
     * HRP-831: sends invitations - `manage` on the invitations section.
     * Below the admin level the API takes only a division the caller
     * heads, so the page offers those.
     */
    canInvite: sections.invitations === "manage",
    /**
     * HRP-621: the two admin pieces on the employee card - changing a role
     * (PUT /employees/{id}/role) and resending the set-password link - sit
     * behind `require_admin()`, the rbac seam, not a section.
     */
    canAssignRoles: isAdmin || isPlatformAdmin,
  };
}
