"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { usePermissions } from "@/hooks/use-permissions";

const tabs = [
  { href: "/company", labelKey: "tabOverview", testId: "company-tab-overview" },
  {
    href: "/company/profile",
    labelKey: "tabProfile",
    testId: "company-tab-profile",
  },
  {
    href: "/company/positions",
    labelKey: "tabPositions",
    testId: "company-tab-positions",
  },
  {
    href: "/company/specializations",
    labelKey: "tabSpecializations",
    testId: "company-tab-specializations",
  },
];

export function CompanyTabs() {
  const pathname = usePathname() ?? "";
  const t = useTranslations("company");
  // HRP-622: a plain employee keeps the overview only.
  const { canViewCompanyDetails } = usePermissions();
  const visible = canViewCompanyDetails ? tabs : tabs.slice(0, 1);
  return (
    <nav className="flex gap-1 border-b">
      {visible.map((tab) => {
        const active =
          tab.href === "/company"
            ? pathname === "/company"
            : pathname.startsWith(tab.href);
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
