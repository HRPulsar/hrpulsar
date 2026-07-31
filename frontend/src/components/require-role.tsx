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
}

export function RequireRole({ children, manage, admin }: RequireRoleProps) {
  const { canManage, isAdmin } = usePermissions();
  const { user, loading } = useAuth();
  const router = useRouter();
  const t = useTranslations("common");

  // Only judge a user we actually have. `loading` can go false with `user`
  // still null — an aborted /auth/me leaves exactly that state — and reading
  // "no roles" as "not permitted" would bounce an entitled admin off the page.
  const undecided = loading || !user;
  const allowed = admin ? isAdmin : manage ? canManage : true;

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
