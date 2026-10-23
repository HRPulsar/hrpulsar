"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";

/**
 * HRP-823…826 (QA 13.10): one pattern for the four section lists - the
 * section's own tab (`all`) at `manage`, then the caller's own side of it,
 * which every level opens. The tab rides in `?tab=` so a link - an e-mail
 * button included - opens it; a tab the caller does not see falls back to
 * the first visible one. Switching drops the other params: each tab starts
 * with its own filters.
 */
export interface SectionTab {
  id: string;
  label: string;
}

export function useSectionTab(ids: readonly string[]): string {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const asked = searchParams.get("tab");
  const tab = asked && ids.includes(asked) ? asked : ids[0];
  // A tab the caller does not see (a `view` caller on `?tab=all`) opens the
  // first visible one, and the URL says so rather than naming the other.
  // Safe on first render: AuthProvider renders nothing until /auth/me is in.
  useEffect(() => {
    if (asked === null || asked === tab) return;
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", tab);
    router.replace(`${pathname}?${params}`, { scroll: false });
  }, [asked, tab, pathname, router, searchParams]);
  return tab;
}

/** The N of "To do (N)" - the backend's count, re-read on every tab switch
 *  and whenever the list says it changed. `null` until it arrives. */
export function useTodoCount(url: string, tab: string) {
  const t = useTranslations("sectionTabs");
  const [count, setCount] = useState<number | null>(null);
  const reload = useCallback(() => {
    api
      .get<{ count: number }>(url)
      .then((r) => setCount(r.count))
      .catch(() => setCount(null));
  }, [url]);
  useEffect(() => {
    reload();
  }, [reload, tab]);
  return { label: count === null ? t("todo") : t("todoCount", { count }), reload };
}

export function SectionTabs({
  tabs,
  active,
  testIdPrefix,
}: {
  tabs: SectionTab[];
  active: string;
  testIdPrefix: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  return (
    <Tabs
      defaultValue={active}
      value={active}
      onValueChange={(id) => router.replace(`${pathname}?tab=${id}`, { scroll: false })}
    >
      <TabsList data-testid={`${testIdPrefix}-tabs`}>
        {tabs.map((tab) => (
          <TabsTrigger key={tab.id} value={tab.id} data-testid={`${testIdPrefix}-tab-${tab.id}`}>
            {tab.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
