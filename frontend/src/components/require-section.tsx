"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { useAuth } from "@/context/auth-context";
import { usePermissions } from "@/hooks/use-permissions";
import { type SectionCode, type SectionLevel, sectionForPath } from "@/lib/sections";

/**
 * HRP-820: the page belongs to a section the tenant's matrix may have
 * closed for this caller. Same contract as RequireRole: judge only a user
 * we have, then toast + bounce to the dashboard.
 */
export function RequireSection({
  code,
  level = "view",
  children,
}: {
  code: SectionCode;
  /** HRP-823: a page whose every call asks for `manage` says so here -
   *  otherwise a caller the tenant left at `view` gets the page frame and
   *  a row of failed requests instead of the toast. */
  level?: SectionLevel;
  children: React.ReactNode;
}) {
  const { canViewSection, canManageSection } = usePermissions();
  const { user, loading } = useAuth();
  const router = useRouter();
  const t = useTranslations("common");

  const undecided = loading || !user;
  const allowed = level === "manage" ? canManageSection(code) : canViewSection(code);

  useEffect(() => {
    if (!undecided && !allowed) {
      toast.error(t("noPermissionPage"), { id: "require-section-denied" });
      router.replace("/dashboard");
    }
  }, [undecided, allowed, router, t]);

  if (undecided || !allowed) return null;
  return <>{children}</>;
}

/** Resolves the section from the route so pages need no wrapper of their own. */
export function SectionGate({ children }: { children: React.ReactNode }) {
  const code = sectionForPath(usePathname() ?? "");
  if (!code) return <>{children}</>;
  return <RequireSection code={code}>{children}</RequireSection>;
}
