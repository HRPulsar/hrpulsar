"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { usePermissions } from "@/hooks/use-permissions";

const tabs = [
  {
    href: "/recruitment/requisitions",
    label: "Vacancies",
    testId: "recruitment-tab-vacancies",
  },
  {
    href: "/recruitment/candidates",
    label: "Candidates",
    testId: "recruitment-tab-candidates",
  },
  {
    href: "/recruitment/reports",
    label: "Reports",
    testId: "recruitment-tab-reports",
  },
  {
    href: "/recruitment/audit-log",
    label: "Audit",
    testId: "recruitment-tab-audit",
    // GET /recruitment/audit-log is admin|hrd-gated on the backend.
    auditRoles: true,
  },
  {
    href: "/recruitment/settings",
    label: "Settings",
    testId: "recruitment-tab-settings",
    adminOnly: true,
  },
];

export function RecruitmentTabs() {
  const pathname = usePathname() ?? "";
  const { roles, isAdmin, isPlatformAdmin } = usePermissions();
  const adminTier = isAdmin || isPlatformAdmin;
  const visibleTabs = tabs.filter((tab) => {
    if (tab.adminOnly) return adminTier;
    if (tab.auditRoles) return adminTier || roles.includes("hrd");
    return true;
  });
  return (
    <nav className="flex gap-1 border-b">
      {visibleTabs.map((tab) => {
        const active = pathname.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            data-testid={tab.testId}
            className={
              active
                ? "border-b-2 border-primary px-4 py-2 text-sm font-medium text-primary"
                : "border-b-2 border-transparent px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground"
            }
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
