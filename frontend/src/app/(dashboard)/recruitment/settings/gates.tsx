"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { useAuth } from "@/context/auth-context";
import { usePermissions } from "@/hooks/use-permissions";

/**
 * HRP-1045: the settings tabs follow what the API already allows instead
 * of a blanket admin wall. One place mirrors the backend audiences:
 *
 * - scales — `manage` on recruitment, writes included (`runs_hiring`;
 *   the scales layout keeps its own RequireSection);
 * - branding, consent templates — read for `manage` or the admin role
 *   (`reads_hiring_settings`), writes stay the admin role's;
 * - retention, roles (and the GDPR / audit tiles) — the admin or hr role
 *   (`require_role("admin", "hr")`), saving retention stays admin's;
 * - LLM and transcription providers — the admin role only.
 */
export function useRecruitmentSettingsAccess() {
  const { isAdmin, isHr, canManageSection } = usePermissions();
  const managesRecruitment = canManageSection("recruitment");
  return {
    isAdmin,
    managesRecruitment,
    /** GET branding / consent-templates (`reads_hiring_settings`). */
    readsHiringSettings: isAdmin || managesRecruitment,
    /** GET retention / roles / gdpr / audit-log (`admin` or `hr`). */
    readsTenantSettings: isAdmin || isHr,
    /** Whoever can open at least one tab sees the hub and the menu entry. */
    any: isAdmin || isHr || managesRecruitment,
  };
}

/** Same contract as RequireRole: judge only a user we have, toast + bounce. */
function Gate({
  allowed,
  children,
}: {
  allowed: boolean;
  children: React.ReactNode;
}) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const t = useTranslations("common");
  const undecided = loading || !user;

  useEffect(() => {
    if (!undecided && !allowed) {
      toast.error(t("noPermissionPage"), { id: "require-role-denied" });
      router.replace("/dashboard");
    }
  }, [undecided, allowed, router, t]);

  if (undecided || !allowed) return null;
  return <>{children}</>;
}

export function RequireRecruitmentSettings({
  children,
}: {
  children: React.ReactNode;
}) {
  return <Gate allowed={useRecruitmentSettingsAccess().any}>{children}</Gate>;
}

export function RequireAdminOrHr({ children }: { children: React.ReactNode }) {
  return (
    <Gate allowed={useRecruitmentSettingsAccess().readsTenantSettings}>
      {children}
    </Gate>
  );
}

export function RequireReadsHiringSettings({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <Gate allowed={useRecruitmentSettingsAccess().readsHiringSettings}>
      {children}
    </Gate>
  );
}
