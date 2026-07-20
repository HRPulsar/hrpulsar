"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";
import { cn } from "@/lib/utils";
import { usePermissions } from "@/hooks/use-permissions";
import { useAuth } from "@/context/auth-context";
import { useEENavItems } from "@/lib/ee-hooks";
import { getBrandName, getLogoUrl } from "@/lib/brand";
import { AppVersion } from "@/components/app-version";
import { SidebarTenantSwitcher } from "@/components/tenant-switcher";

const emptySubscribe = () => () => {};

interface NavItem {
  id: string;
  name: string;
  href: string;
  icon: React.ReactNode;
  badge?: string;
  requireManage?: boolean;
  requireAdmin?: boolean;
}

interface NavSection {
  label: string;
  items: string[];
}

const navigation: NavItem[] = [
  {
    id: "dashboard",
    name: "Dashboard",
    href: "/dashboard",
    icon: (
      <svg className="h-[15px] w-[15px]" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
      </svg>
    ),
  },
  {
    id: "employees",
    name: "Employees",
    href: "/employees",
    icon: (
      <svg className="h-[15px] w-[15px]" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 0 0 2.625.372 9.337 9.337 0 0 0 4.121-.952 4.125 4.125 0 0 0-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 0 1 8.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0 1 11.964-3.07M12 6.375a3.375 3.375 0 1 1-6.75 0 3.375 3.375 0 0 1 6.75 0Zm8.25 2.25a2.625 2.625 0 1 1-5.25 0 2.625 2.625 0 0 1 5.25 0Z" />
      </svg>
    ),
  },
  {
    id: "company",
    name: "Company",
    href: "/company",
    icon: (
      <svg className="h-[15px] w-[15px]" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 21h16.5M4.5 3h15M5.25 3v18m13.5-18v18M9 6.75h1.5m-1.5 3h1.5m-1.5 3h1.5m3-6H15m-1.5 3H15m-1.5 3H15M9 21v-3.375c0-.621.504-1.125 1.125-1.125h3.75c.621 0 1.125.504 1.125 1.125V21" />
      </svg>
    ),
  },
  {
    id: "assessments",
    name: "Assessments",
    href: "/assessments",
    icon: (
      <svg className="h-[15px] w-[15px]" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M11.35 3.836c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 0 0 .75-.75 2.25 2.25 0 0 0-.1-.664m-5.8 0A2.251 2.251 0 0 1 13.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m8.9-4.414c.376.023.75.05 1.124.08 1.131.094 1.976 1.057 1.976 2.192V16.5A2.25 2.25 0 0 1 18 18.75h-2.25" />
      </svg>
    ),
  },
  {
    id: "development",
    name: "Development",
    href: "/development",
    icon: (
      <svg className="h-[15px] w-[15px]" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487 18.549 2.799a2.121 2.121 0 1 1 3 3L5.232 22.118a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125" />
      </svg>
    ),
  },
  {
    id: "exams",
    name: "Exams",
    href: "/exams",
    icon: (
      <svg className="h-[15px] w-[15px]" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z" />
      </svg>
    ),
  },
  {
    id: "competences",
    name: "Competences",
    href: "/competences",
    icon: (
      <svg className="h-[15px] w-[15px]" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="m6.75 7.5 3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0 0 21 18V6a2.25 2.25 0 0 0-2.25-2.25H5.25A2.25 2.25 0 0 0 3 6v12a2.25 2.25 0 0 0 2.25 2.25Z" />
      </svg>
    ),
  },
  {
    id: "talent-market",
    name: "Talent Market",
    href: "/talent-market",
    icon: (
      <svg className="h-[15px] w-[15px]" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18 9 11.25l4.306 4.306a11.95 11.95 0 0 1 5.814-5.518l2.74-1.22m0 0-5.94-2.281m5.94 2.28-2.28 5.941" />
      </svg>
    ),
  },
  {
    id: "recruitment",
    name: "Recruitment",
    href: "/recruitment",
    icon: (
      <svg className="h-[15px] w-[15px]" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 14.15v4.25c0 1.094-.787 2.036-1.872 2.18-2.087.277-4.216.42-6.378.42s-4.291-.143-6.378-.42c-1.085-.144-1.872-1.086-1.872-2.18v-4.25m16.5 0a2.18 2.18 0 0 0 .75-1.661V8.706c0-1.081-.768-2.015-1.837-2.175a48.114 48.114 0 0 0-3.413-.387m4.5 8.006c-.194.165-.42.295-.673.38A23.978 23.978 0 0 1 12 15.75c-2.648 0-5.195-.429-7.577-1.22a2.016 2.016 0 0 1-.673-.38m0 0A2.18 2.18 0 0 1 3 12.489V8.706c0-1.081.768-2.015 1.837-2.175a48.111 48.111 0 0 1 3.413-.387m7.5 0V5.25A2.25 2.25 0 0 0 13.5 3h-3a2.25 2.25 0 0 0-2.25 2.25v.894m7.5 0a48.667 48.667 0 0 0-7.5 0" />
      </svg>
    ),
  },
  {
    id: "analytics",
    name: "Analytics",
    href: "/analytics",
    requireManage: true,
    icon: (
      <svg className="h-[15px] w-[15px]" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
      </svg>
    ),
  },
  {
    id: "dictionaries",
    name: "Dictionaries",
    href: "/dictionaries",
    requireManage: true,
    icon: (
      <svg className="h-[15px] w-[15px]" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
      </svg>
    ),
  },
  {
    id: "import",
    name: "Data Import",
    href: "/settings/import",
    requireAdmin: true,
    icon: (
      <svg className="h-[15px] w-[15px]" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5" />
      </svg>
    ),
  },
  {
    id: "invitations",
    name: "Invitations",
    href: "/settings/invitations",
    requireManage: true,
    icon: (
      <svg className="h-[15px] w-[15px]" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M21.75 6.75v10.5a2.25 2.25 0 0 1-2.25 2.25h-15a2.25 2.25 0 0 1-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0 0 19.5 4.5h-15a2.25 2.25 0 0 0-2.25 2.25m19.5 0v.243a2.25 2.25 0 0 1-1.07 1.916l-7.5 4.615a2.25 2.25 0 0 1-2.36 0L3.32 8.91a2.25 2.25 0 0 1-1.07-1.916V6.75" />
      </svg>
    ),
  },
  {
    id: "ai-settings",
    name: "AI settings",
    href: "/settings/ai",
    requireAdmin: true,
    icon: (
      <svg className="h-[15px] w-[15px]" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
      </svg>
    ),
  },
];

const sections: NavSection[] = [
  { label: "Workspace", items: ["dashboard", "employees", "company"] },
  { label: "Talent", items: ["assessments", "development", "exams", "competences"] },
  { label: "Discover", items: ["talent-market", "recruitment", "analytics"] },
  { label: "Admin", items: ["dictionaries", "import", "invitations", "ai-settings", "billing"] },
];

export function Sidebar() {
  const pathname = usePathname();
  const { resolvedTheme } = useTheme();
  const { canManage, isAdmin } = usePermissions();
  const { user } = useAuth();
  const mounted = useSyncExternalStore(emptySubscribe, () => true, () => false);

  const logoSrc = getLogoUrl(mounted && resolvedTheme === "dark" ? "dark" : "light");

  const { items: eeNavItems, credits } = useEENavItems(isAdmin);

  const eeAsNav: NavItem[] = eeNavItems.map((item) => {
    let id = "";
    if (item.href === "/settings/billing") id = "billing";
    return {
      id,
      name: item.name,
      href: item.href,
      icon: item.icon,
      requireAdmin: item.requireAdmin,
      requireManage: item.requireManage,
    };
  });
  const fullNav = [...navigation, ...eeAsNav];
  const byId = new Map(fullNav.map((n) => [n.id, n]));

  const isLowCredits = credits !== null && credits.total < 500;

  const initials = user
    ? `${user.first_name[0] ?? ""}${user.last_name[0] ?? ""}`.toUpperCase()
    : "?";
  const userName = user ? `${user.first_name} ${user.last_name}`.trim() : "";
  const userRole =
    user && user.roles.length > 0 ? user.roles[0].replace(/_/g, " ") : "";

  return (
    <aside className="flex h-full w-[232px] flex-col border-r border-sidebar-border bg-sidebar">
      <Link
        href="/dashboard"
        className="flex h-14 items-center justify-between border-b border-sidebar-border px-4"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={logoSrc} alt={getBrandName()} className="h-5" />
        <AppVersion className="rounded border border-sidebar-border px-1.5 py-px font-mono text-[10px] text-muted-foreground" />
      </Link>

      <div className="px-3 pt-2 pb-1">
        <SidebarTenantSwitcher />
      </div>

      <nav
        className="flex flex-1 flex-col gap-3 overflow-y-auto px-2.5 py-2"
        data-testid="sidebar-nav"
      >
        {sections.map((sec) => {
          const visible = sec.items
            .map((id) => byId.get(id))
            .filter((item): item is NavItem => {
              if (!item) return false;
              if (item.requireAdmin && !isAdmin) return false;
              if (item.requireManage && !canManage) return false;
              return true;
            });
          if (visible.length === 0) return null;
          return (
            <div key={sec.label} className="flex flex-col gap-px">
              <div className="px-2.5 pt-1 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {sec.label}
              </div>
              {visible.map((item) => {
                const isActive =
                  pathname === item.href ||
                  pathname.startsWith(item.href + "/");
                const slug = item.id || item.name.toLowerCase().replace(/\s+/g, "-");
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    data-testid={`sidebar-link-${slug}`}
                    className={cn(
                      "relative flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] transition-colors",
                      isActive
                        ? "bg-accent/10 font-medium text-accent"
                        : "text-foreground hover:bg-foreground/5",
                    )}
                  >
                    {isActive && (
                      <span className="absolute -left-2.5 top-2 bottom-2 w-0.5 rounded-full bg-accent" />
                    )}
                    {item.icon}
                    <span className="flex-1">{item.name}</span>
                    {item.badge && (
                      <span
                        className={cn(
                          "rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                          isActive
                            ? "bg-accent text-accent-foreground"
                            : "bg-muted text-muted-foreground",
                        )}
                      >
                        {item.badge}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          );
        })}
      </nav>

      {user?.is_platform_admin && (
        <Link
          href="/platform"
          data-testid="sidebar-link-platform"
          className="mx-3 mb-2 flex items-center gap-2 rounded-md border border-accent/20 bg-accent/5 px-2.5 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent/10"
        >
          <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
          </svg>
          Platform Admin
        </Link>
      )}

      {credits !== null && isAdmin && (
        <Link
          href="/settings/billing"
          data-testid="sidebar-credits"
          className="mx-3 mb-2 flex items-center gap-2 rounded-md border border-sidebar-border px-2.5 py-1.5 text-xs transition-colors hover:bg-foreground/5"
        >
          <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75Z" />
          </svg>
          <span className="flex-1 truncate text-muted-foreground">Credits</span>
          <span
            className={cn(
              "font-semibold tabular-nums",
              isLowCredits ? "text-red-600" : "text-foreground",
            )}
          >
            {credits.total.toLocaleString()}
          </span>
        </Link>
      )}

      <div className="flex items-center gap-2.5 border-t border-sidebar-border px-3 py-2.5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/10 text-[11px] font-semibold text-accent">
          {initials}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium">{userName}</div>
          {userRole && (
            <div className="truncate text-[11px] capitalize text-muted-foreground">
              {userRole}
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}