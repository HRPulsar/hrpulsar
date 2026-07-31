"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Building2,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Info,
  Layers,
  Sliders,
  Target,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { DictionaryItem } from "@/lib/types";

interface UsedData {
  specializations: string[];
  divisions: string[];
  companyDescription: string | null;
  hasAiSettings: boolean;
}

interface UsedDataTooltipProps {
  defaultOpen?: boolean;
  testId?: string;
  /** Pre-fetched data; if absent we fetch on mount. */
  data?: UsedData;
}

const EMPTY: UsedData = {
  specializations: [],
  divisions: [],
  companyDescription: null,
  hasAiSettings: false,
};

/**
 * Renders the tenant context the AI generator will read: specializations,
 * divisions, company description, AI settings. Each section deep-links to the
 * dictionary/profile/settings page so the user can edit the source of truth
 * before starting the run.
 */
export function UsedDataTooltip({
  defaultOpen = true,
  testId = "compgen-tooltip-used-data",
  data: providedData,
}: UsedDataTooltipProps) {
  const t = useTranslations("competences");
  const [open, setOpen] = useState(defaultOpen);
  const [fetched, setFetched] = useState<UsedData | null>(null);
  const data = providedData ?? fetched;

  useEffect(() => {
    if (providedData) return;
    let cancelled = false;
    (async () => {
      try {
        const [specs, divs, company, settings] = await Promise.all([
          api
            .get<DictionaryItem[]>("/dictionaries/specialization")
            .catch(() => [] as DictionaryItem[]),
          api
            .get<{ id: string; title: string }[]>("/divisions")
            .catch(() => []),
          api
            .get<{ description?: string }>("/settings/company-profile")
            .catch(() => ({})),
          api.get<unknown>("/admin/ai-settings").catch(() => null),
        ]);
        if (cancelled) return;
        setFetched({
          // HRP-479 review: deliberately RAW titles — the panel claims to
          // show "data sent to the model", and the backend prompt is
          // built from the stored DB titles, not the localized labels.
          specializations: specs
            .map((s) => s.title?.trim())
            .filter((t): t is string => Boolean(t)),
          divisions: divs
            .map((d) => d.title?.trim())
            .filter((t): t is string => Boolean(t)),
          companyDescription:
            (company as { description?: string })?.description?.trim() || null,
          hasAiSettings: settings != null,
        });
      } catch {
        if (!cancelled) setFetched(EMPTY);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [providedData]);

  return (
    <div data-testid={testId} className="rounded-md border bg-muted/30">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium hover:bg-muted/50"
      >
        {open ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
        <Info className="h-4 w-4 text-muted-foreground" />
        {t("usedDataTitle")}
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          {t("usedDataSentToModel")}
        </span>
      </button>
      {open && (
        <div className="space-y-3 px-3 py-3 text-sm">
          <Section
            icon={<Target className="h-4 w-4 text-muted-foreground" />}
            title={t("sectionSpecializations")}
            href="/dictionaries"
            hrefLabel={t("usedDataEditSpecializations")}
            empty={data ? data.specializations.length === 0 : false}
            emptyHint={t("usedDataSpecializationsEmpty")}
          >
            {data?.specializations.length ? (
              <ChipList items={data.specializations} />
            ) : null}
          </Section>

          <Section
            icon={<Building2 className="h-4 w-4 text-muted-foreground" />}
            title={t("sectionDivisions")}
            href="/company"
            hrefLabel={t("usedDataEditDivisions")}
            empty={data ? data.divisions.length === 0 : false}
            emptyHint={t("usedDataDivisionsEmpty")}
          >
            {data?.divisions.length ? (
              <ChipList items={data.divisions} />
            ) : null}
          </Section>

          <Section
            icon={<Layers className="h-4 w-4 text-muted-foreground" />}
            title={t("sectionCompanyDescription")}
            href="/company/profile"
            hrefLabel={t("usedDataEditCompanyProfile")}
            empty={!data?.companyDescription}
            emptyHint={t("usedDataCompanyEmpty")}
          >
            {data?.companyDescription ? (
              <p className="whitespace-pre-wrap rounded-sm bg-background/60 p-2 text-xs text-foreground/90">
                {data.companyDescription}
              </p>
            ) : null}
          </Section>

          <Section
            icon={<Sliders className="h-4 w-4 text-muted-foreground" />}
            title={t("usedDataAiSettings")}
            href="/settings/ai"
            hrefLabel={t("usedDataOpenAiSettings")}
            empty={false}
          >
            <p className="text-xs text-muted-foreground">
              {data?.hasAiSettings
                ? t("usedDataAiSettingsTenant")
                : t("usedDataAiSettingsDefaults")}
            </p>
          </Section>
        </div>
      )}
    </div>
  );
}

function Section({
  icon,
  title,
  href,
  hrefLabel,
  empty,
  emptyHint,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  href: string;
  hrefLabel: string;
  empty: boolean;
  emptyHint?: string;
  children?: React.ReactNode;
}) {
  const t = useTranslations("competences");
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {title}
        </span>
        <Link
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          {hrefLabel}
          <ExternalLink className="h-3 w-3" />
        </Link>
      </div>
      {empty ? (
        <p className="rounded-sm border border-dashed px-2 py-1.5 text-xs text-muted-foreground">
          {emptyHint ?? t("usedDataNoData")}
        </p>
      ) : (
        children
      )}
    </div>
  );
}

function ChipList({ items }: { items: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item, i) => (
        <span
          key={`${item}-${i}`}
          className="inline-flex items-center rounded-md border bg-background px-2 py-0.5 text-xs text-foreground"
        >
          {item}
        </span>
      ))}
    </div>
  );
}
