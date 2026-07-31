"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAuth } from "@/context/auth-context";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

function tenantInitials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0])
    .join("")
    .toUpperCase();
}

export function SidebarTenantSwitcher() {
  const { user, tenants, switchTenant } = useAuth();
  const [switching, setSwitching] = useState(false);
  const router = useRouter();
  const t = useTranslations("common");
  const tPlatform = useTranslations("platform");

  if (!user) return null;
  const current = tenants.find((t) => t.id === user.tenant_id);
  if (!current) return null;

  const isPlatformAdmin = user.is_platform_admin;
  const others = tenants.filter((t) => t.id !== user.tenant_id);
  const hasMenu = others.length > 0 || isPlatformAdmin;

  async function handleSwitch(tenantId: string) {
    setSwitching(true);
    try {
      await switchTenant(tenantId);
    } finally {
      setSwitching(false);
    }
  }

  const trigger = (
    <span className="flex w-full items-center gap-2 rounded-md border border-sidebar-border bg-card px-2 py-1.5 text-left text-[12.5px]">
      <span
        aria-hidden
        className="flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded text-[10px] font-bold text-white"
        style={{ background: "linear-gradient(135deg,var(--brand-accent),var(--brand-accent-deep))" }}
      >
        {tenantInitials(current.name)}
      </span>
      <span className="min-w-0 flex-1 truncate font-medium">{current.name}</span>
      {hasMenu && (
        <svg
          className="h-3 w-3 shrink-0 text-muted-foreground"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={2}
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 15 12 18.75 15.75 15m-7.5-6L12 5.25 15.75 9" />
        </svg>
      )}
    </span>
  );

  if (!hasMenu) {
    return <div data-testid="sidebar-tenant">{trigger}</div>;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="w-full outline-none"
        disabled={switching}
        data-testid="sidebar-tenant"
      >
        {trigger}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-60">
        <div className="flex items-center justify-between px-2 py-1.5">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{current.name}</p>
            <p className="truncate text-xs text-muted-foreground">{current.slug}</p>
          </div>
          <div className="flex shrink-0 gap-1">
            {current.roles.map((role) => (
              <Badge key={role} variant="secondary" className="text-xs">
                {role}
              </Badge>
            ))}
          </div>
        </div>
        {others.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <p className="px-2 py-1 text-xs text-muted-foreground">{t("switchTo")}</p>
            {others.map((t) => (
              <DropdownMenuItem
                key={t.id}
                onClick={() => handleSwitch(t.id)}
                className="cursor-pointer"
                disabled={switching}
              >
                <div className="flex w-full items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm">{t.name}</p>
                    <p className="truncate text-xs text-muted-foreground">{t.slug}</p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    {t.roles.map((role) => (
                      <Badge key={role} variant="outline" className="text-xs">
                        {role}
                      </Badge>
                    ))}
                  </div>
                </div>
              </DropdownMenuItem>
            ))}
          </>
        )}
        {isPlatformAdmin && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => router.push("/platform")}
              className="cursor-pointer"
            >
              <span className="flex items-center gap-2">
                <svg className="h-4 w-4 text-accent" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                </svg>
                {tPlatform("title")}
              </span>
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function TenantSwitcher() {
  const { user, tenants, switchTenant } = useAuth();
  const [switching, setSwitching] = useState(false);
  const router = useRouter();
  const t = useTranslations("common");
  const tPlatform = useTranslations("platform");

  const isPlatformAdmin = user?.is_platform_admin;

  if (!user || (tenants.length <= 1 && !isPlatformAdmin)) {
    // Single tenant, not platform admin — show name without dropdown
    const current = tenants.find((t) => t.id === user?.tenant_id);
    if (!current) return null;
    return (
      <div className="flex items-center gap-2 rounded-md px-2 py-1 text-sm">
        <span className="font-medium text-foreground">{current.name}</span>
      </div>
    );
  }

  const current = tenants.find((t) => t.id === user.tenant_id);
  const others = tenants.filter((t) => t.id !== user.tenant_id);

  async function handleSwitch(tenantId: string) {
    setSwitching(true);
    try {
      await switchTenant(tenantId);
    } finally {
      setSwitching(false);
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="flex items-center gap-1.5 rounded-md px-2 py-1 text-sm hover:bg-muted outline-none"
        disabled={switching}
        data-testid="header-btn-tenant-switcher"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="text-muted-foreground"
        >
          <rect width="18" height="18" x="3" y="3" rx="2" />
          <path d="M9 3v18" />
        </svg>
        <span className="hidden font-medium sm:inline">
          {current?.name ?? t("unknown")}
        </span>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="text-muted-foreground"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        {current && (
          <div className="flex items-center justify-between px-2 py-1.5">
            <div>
              <p className="text-sm font-medium">{current.name}</p>
              <p className="text-xs text-muted-foreground">{current.slug}</p>
            </div>
            <div className="flex gap-1">
              {current.roles.map((role) => (
                <Badge key={role} variant="secondary" className="text-xs">
                  {role}
                </Badge>
              ))}
            </div>
          </div>
        )}
        {others.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <p className="px-2 py-1 text-xs text-muted-foreground">
              {t("switchTo")}
            </p>
            {others.map((t) => (
              <DropdownMenuItem
                key={t.id}
                onClick={() => handleSwitch(t.id)}
                className="cursor-pointer"
                disabled={switching}
              >
                <div className="flex w-full items-center justify-between">
                  <div>
                    <p className="text-sm">{t.name}</p>
                    <p className="text-xs text-muted-foreground">{t.slug}</p>
                  </div>
                  <div className="flex gap-1">
                    {t.roles.map((role) => (
                      <Badge key={role} variant="outline" className="text-xs">
                        {role}
                      </Badge>
                    ))}
                  </div>
                </div>
              </DropdownMenuItem>
            ))}
          </>
        )}
        {isPlatformAdmin && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => router.push("/platform")}
              className="cursor-pointer"
            >
              <div className="flex w-full items-center justify-between">
                <div className="flex items-center gap-2">
                  <svg className="h-4 w-4 text-primary" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                  </svg>
                  <p className="text-sm font-medium">{tPlatform("title")}</p>
                </div>
              </div>
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
