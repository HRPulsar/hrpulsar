"use client";

import { useAuth } from "@/context/auth-context";

export function usePermissions() {
  const { user } = useAuth();
  const roles = user?.roles ?? [];

  const isAdmin = roles.includes("admin");
  const isManager = roles.includes("manager");
  const isEmployee = roles.includes("employee");
  const isPlatformAdmin = roles.includes("platform_admin");
  const isHr = roles.includes("hr");
  const isRecruiter = roles.includes("recruiter");
  const isHiringManager = roles.includes("hiring_manager");

  return {
    roles,
    isAdmin,
    isManager,
    isEmployee,
    isPlatformAdmin,
    isHr,
    isRecruiter,
    isHiringManager,
    /** Admin or Manager */
    canManage: isAdmin || isManager,
    /**
     * HRP-732: who may open the read-only management surface /analytics.
     * Deliberately its own flag rather than widening ``canManage`` — that
     * one also unlocks every edit affordance in the product, which HR must
     * not get for free. Mirrors ``require_role("admin", "manager", "hr")``
     * on the analytics routes.
     */
    canViewManagementData: isAdmin || isManager || isHr,
    /**
     * HRP-810: Coverage opens by /auth/me, not by a role list - the roles
     * that run it get "manage", anyone who reads at least one process gets
     * "view". Editing one process is that process's `my_access`.
     */
    canViewCoverage: Boolean(user?.sections?.coverage),
    canCreateCoverage: user?.sections?.coverage === "manage",
    /**
     * HRP-623: sees the HR record rather than the directory row. Mirrors
     * ``is_employee_only`` in backend/app/core/access_scope.py, inverted —
     * a wider set here renders columns the API does not send.
     */
    canViewHrData: isAdmin || isPlatformAdmin || isHr || isManager,
    /**
     * HRP-637: sees a position's grade and specialization — the hiring
     * roles read the pair (a requisition cannot be raised without it),
     * everyone else only while the tenant switched ``directory_show_grades``
     * on. HRP-710: ``/auth/me`` answers this outright via
     * ``can_see_position_grades``; this used to re-derive it from the role
     * list, which is the backend's role set copied out by hand.
     */
    canViewJobProfile: user?.can_view_job_profile === true,
    /** Can create/edit assessments, exams, PDPs */
    canCreateAssessments: isAdmin || isManager,
    /**
     * HRP-631: may edit the workspace-wide catalogues — competences,
     * groups, indicators, materials, answer scales, and the grade ladder
     * and matrices of a specialization. Those rows carry no owning
     * column, so a division head cannot be scoped to a slice of them and
     * the gate on the API is `admin` / `hr`. A wider set here is a button
     * that lands on 403.
     */
    canManageCatalogues: isAdmin || isHr,
    /** Can import data */
    canImport: isAdmin,
    /** Can manage roles and settings */
    canAdminister: isAdmin,
    /**
     * Gates the two invitation affordances the UI actually has: the link to
     * the invitation registry and "resend set-password link". Both sit behind
     * ``require_admin()`` on the API (GET/PATCH/cancel/resend `/invitations`,
     * POST `/employees/{id}/set-password-link`), so admin-only is correct
     * here even though `POST /invitations` itself also accepts `hr` and
     * `manager` — those two have no invitation UI (see rbac.md).
     */
    canInvite: isAdmin || isPlatformAdmin,
    /** HRP-621: can change another user's role (PUT /employees/{id}/role) */
    canAssignRoles: isAdmin || isPlatformAdmin,
    /**
     * HRP-622: may open the recruitment section at all. Must stay identical
     * to ``RECRUITMENT_VIEWER_ROLES`` in
     * backend/app/modules/recruitment/routers/common.py — a wider set here
     * is a menu entry that lands on 403.
     */
    canRecruit:
      isAdmin ||
      isPlatformAdmin ||
      isHr ||
      isRecruiter ||
      isHiringManager ||
      isManager,
  };
}
