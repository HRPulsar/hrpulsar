"use client";

import { useAuth } from "@/context/auth-context";

export function usePermissions() {
  const { user } = useAuth();
  const roles = user?.roles ?? [];

  const isAdmin = roles.includes("admin");
  const isManager = roles.includes("manager");
  const isEmployee = roles.includes("employee");
  const isPlatformAdmin = roles.includes("platform_admin");

  return {
    roles,
    isAdmin,
    isManager,
    isEmployee,
    isPlatformAdmin,
    /** Admin or Manager */
    canManage: isAdmin || isManager,
    /** Can create/edit assessments, exams, PDPs */
    canCreateAssessments: isAdmin || isManager,
    /** Can import data */
    canImport: isAdmin,
    /** Can manage roles and settings */
    canAdminister: isAdmin,
    /** Can send tenant invitations */
    canInvite: isAdmin || isPlatformAdmin,
  };
}
