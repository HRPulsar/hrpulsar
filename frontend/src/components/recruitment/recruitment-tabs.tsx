"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { usePermissions } from "@/hooks/use-permissions";

// `labelKey` points at the `recruitment` i18n namespace; `testId` stays a
// stable identifier and is never derived from the translation.
const tabs = [
  {
    href: "/recruitment/requisitions",
    labelKey: "vacanciesTitle",
    testId: "recruitment-tab-vacancies",
  },
  {
    href: "/recruitment/candidates",
    labelKey: "candidatesTitle",
    testId: "recruitment-tab-candidates",
  },
  {
    href: "/recruitment/reports",
    labelKey: "breadcrumbReports",
    testId: "recruitment-tab-reports",
  },
  {
    href: "/recruitment/audit-log",
    labelKey: "tabAudit",
    testId: "recruitment-tab-audit",
    // GET /recruitment/audit-log is admin|hr-gated on the backend.
    auditRoles: true,
  },
  {
    href: "/recruitment/settings",
    labelKey: "tabSettings",
    testId: "recruitment-tab-settings",
    // HRP-1045: the settings hub opens to whoever can open at least one
    // tab — `manage` on recruitment (scales, branding, consents), the hr
    // role (retention, roles) or the admin role.
    settingsAccess: true,
  },
];

export function RecruitmentTabs() {
  const t = useTranslations("recruitment");
  const pathname = usePathname() ?? "";
  // HRP-830: both tabs follow the role gates behind them - the audit log
  // is `require_role("admin", "hr")`; neither names platform_admin.
  const { isAdmin, isHr, canManageSection } = usePermissions();
  const visibleTabs = tabs.filter((tab) => {
    if (tab.settingsAccess)
      return isAdmin || isHr || canManageSection("recruitment");
    if (tab.auditRoles) return isAdmin || isHr;
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
            {t(tab.labelKey)}
          </Link>
        );
      })}
    </nav>
  );
}
