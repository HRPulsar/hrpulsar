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
     * HRP-623: sees the HR record rather than the directory row. Mirrors
     * ``is_employee_only`` in backend/app/core/access_scope.py, inverted —
     * a wider set here renders columns the API does not send.
     */
    canViewHrData: isAdmin || isPlatformAdmin || isHr || isManager,
    /**
     * HRP-637: sees a position's grade and specialization. Mirrors
     * ``can_see_position_grades`` in backend/app/core/access_scope.py —
     * the hiring roles read the pair (a requisition cannot be raised
     * without it), everyone else only while the tenant switched
     * ``directory_show_grades`` on. The flag arrives on ``/auth/me``: it
     * is a property of the tenant, and deriving it from whichever rows the
     * current page happens to hold answers wrong on any page whose rows
     * have no pair.
     */
    canViewJobProfile:
      isAdmin ||
      isPlatformAdmin ||
      isHr ||
      isManager ||
      isRecruiter ||
      isHiringManager ||
      user?.tenant_directory_show_grades === true,
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
    /** Can send tenant invitations */
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
