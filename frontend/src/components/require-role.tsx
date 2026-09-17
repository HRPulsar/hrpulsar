"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { usePermissions } from "@/hooks/use-permissions";
import { useAuth } from "@/context/auth-context";
import { toast } from "sonner";

interface RequireRoleProps {
  children: React.ReactNode;
  /** Require admin or manager role */
  manage?: boolean;
  /** Require admin role */
  admin?: boolean;
  /** HRP-732: require admin, manager or HR — the read-only management
   *  surface /analytics. */
  managementData?: boolean;
  /** HRP-810: /auth/me opens Coverage. */
  coverage?: boolean;
  /** HRP-810: may create a process. */
  coverageManage?: boolean;
  /** HRP-622: the recruiting roles (usePermissions.canRecruit). */
  recruit?: boolean;
}

export function RequireRole({
  children,
  manage,
  admin,
  managementData,
  coverage,
  coverageManage,
  recruit,
}: RequireRoleProps) {
  const {
    canManage,
    isAdmin,
    canViewManagementData,
    canViewCoverage,
    canCreateCoverage,
    canRecruit,
  } = usePermissions();
  const { user, loading } = useAuth();
  const router = useRouter();
  const t = useTranslations("common");

  // Only judge a user we actually have. `loading` can go false with `user`
  // still null — an aborted /auth/me leaves exactly that state — and reading
  // "no roles" as "not permitted" would bounce an entitled admin off the page.
  const undecided = loading || !user;
  // First match wins: pass exactly one flag, or the page gets the loosest gate.
  const allowed = admin
    ? isAdmin
    : managementData
      ? canViewManagementData
      : coverageManage
        ? canCreateCoverage
        : coverage
          ? canViewCoverage
          : recruit
            ? canRecruit
            : manage
              ? canManage
              : true;

  useEffect(() => {
    if (!undecided && !allowed) {
      // Stable id: a remount (or React's double-invoked effects in dev) would
      // otherwise stack a second identical toast.
      toast.error(t("noPermissionPage"), { id: "require-role-denied" });
      router.replace("/dashboard");
    }
  }, [undecided, allowed, router, t]);

  if (undecided || !allowed) return null;

  return <>{children}</>;
}
