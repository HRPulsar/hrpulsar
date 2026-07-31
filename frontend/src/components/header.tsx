"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/context/auth-context";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { GlobalSearch } from "@/components/global-search";
import { NotificationBell } from "@/components/notification-bell";
import { LanguageSwitcher } from "@/components/language-switcher";
import { ThemeToggle } from "@/components/theme-toggle";
import { MobileSidebar } from "@/components/mobile-sidebar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/** URL segment → message key in the `sidebar` namespace (shared with the
 * sidebar nav so a section is named the same way everywhere). */
const SEGMENT_KEYS: Record<string, string> = {
  dashboard: "dashboard",
  employees: "employees",
  company: "company",
  assessments: "assessments",
  development: "development",
  exams: "exams",
  competences: "competences",
  dictionaries: "dictionaries",
  "talent-market": "talentMarket",
  analytics: "analytics",
  onboarding: "onboarding",
  settings: "settings",
  profile: "profile",
  invitations: "invitations",
  import: "dataImport",
  notifications: "notifications",
  billing: "billing",
  transactions: "transactions",
  prices: "prices",
  ai: "aiSettings",
  recruitment: "recruitment",
  requisitions: "requisitions",
  candidates: "candidates",
  interviews: "interviews",
  reports: "reports",
  "audit-log": "auditLog",
  admin: "admin",
  "ai-generate": "aiGenerate",
  "assessment-groups": "assessmentGroups",
  branding: "branding",
  canvas: "canvas",
  compare: "compare",
  "consent-templates": "consentTemplates",
  divisions: "divisions",
  edit: "edit",
  gdpr: "gdpr",
  "llm-providers": "llmProviders",
  matrix: "matrix",
  new: "new",
  positions: "positions",
  "report-templates": "reportTemplates",
  retention: "retention",
  roles: "roles",
  scales: "scales",
  specializations: "specializations",
  "transcription-providers": "transcriptionProviders",
  unassigned: "unassigned",
};

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Translate = (key: string) => string;

function buildCrumbs(
  pathname: string,
  tNav: Translate,
  tCommon: Translate,
): { label: string; href: string }[] {
  const parts = pathname.split("/").filter(Boolean);
  const out: { label: string; href: string }[] = [];
  let acc = "";
  for (const p of parts) {
    acc += "/" + p;
    if (UUID_RE.test(p)) {
      out.push({ label: tCommon("detail"), href: acc });
      continue;
    }
    const key = SEGMENT_KEYS[p];
    const label = key
      ? tNav(key)
      : p.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    out.push({ label, href: acc });
  }
  return out;
}

export function Header() {
  const { user, signOut } = useAuth();
  const pathname = usePathname();
  const t = useTranslations("common");
  const tNav = useTranslations("sidebar");
  const crumbs = useMemo(
    () => buildCrumbs(pathname, tNav, t),
    [pathname, tNav, t],
  );

  const initials = user
    ? `${user.first_name[0]}${user.last_name[0]}`.toUpperCase()
    : "?";

  return (
    <header className="flex h-[52px] shrink-0 items-center gap-3.5 border-b border-border bg-background px-4 sm:px-5">
      <MobileSidebar />

      <nav
        aria-label={t("breadcrumb")}
        className="hidden min-w-0 shrink-0 items-center gap-1.5 text-sm text-muted-foreground sm:flex"
      >
        {crumbs.map((c, i) => {
          const isLast = i === crumbs.length - 1;
          return (
            <span key={c.href} className="flex items-center gap-1.5 truncate">
              {i > 0 && <span aria-hidden className="opacity-50">/</span>}
              {isLast ? (
                <span className="truncate font-medium text-foreground">{c.label}</span>
              ) : (
                <Link href={c.href} className="truncate transition-colors hover:text-foreground">
                  {c.label}
                </Link>
              )}
            </span>
          );
        })}
      </nav>

      <GlobalSearch />

      <div className="flex items-center gap-2">
        <LanguageSwitcher />
        <ThemeToggle />
        <NotificationBell />
        <DropdownMenu>
          <DropdownMenuTrigger data-testid="header-btn-user-menu" className="flex items-center gap-2 rounded-md px-1.5 py-1 outline-none hover:bg-muted">
            <Avatar className="h-7 w-7">
              {user?.avatar_url && <AvatarImage src={user.avatar_url} />}
              <AvatarFallback className="bg-accent/15 text-[11px] font-semibold text-accent">
                {initials}
              </AvatarFallback>
            </Avatar>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <div className="px-2 py-1.5">
              <p className="truncate text-sm font-medium">
                {user ? `${user.first_name} ${user.last_name}` : ""}
              </p>
              <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
            </div>
            <DropdownMenuSeparator />
            <DropdownMenuItem render={<Link href="/settings/profile" />} className="cursor-pointer" data-testid="header-menu-settings">
              {t("settings")}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={signOut} className="cursor-pointer text-destructive" data-testid="header-menu-signout">
              {t("signOut")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}