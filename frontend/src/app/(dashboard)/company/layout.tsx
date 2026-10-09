"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { useAuth } from "@/context/auth-context";
import { usePermissions } from "@/hooks/use-permissions";

const DETAIL_PATHS = ["/company/profile", "/company/positions", "/company/specializations"];

/**
 * HRP-622: the tabs a plain employee does not get stay closed by direct
 * link too. Same contract as RequireSection: judge only a user we have,
 * then toast + bounce to the dashboard.
 */
export default function CompanyLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "";
  const { canViewCompanyDetails } = usePermissions();
  const { user, loading } = useAuth();
  const router = useRouter();
  const t = useTranslations("common");

  const undecided = loading || !user;
  const gated = DETAIL_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
  const allowed = !gated || canViewCompanyDetails;

  useEffect(() => {
    if (!undecided && !allowed) {
      toast.error(t("noPermissionPage"), { id: "require-company-details-denied" });
      router.replace("/dashboard");
    }
  }, [undecided, allowed, router, t]);

  if (gated && (undecided || !allowed)) return null;
  return <>{children}</>;
}
