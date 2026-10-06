"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { Input } from "@/components/ui/input";

export interface GalleryItem {
  slug: string;
  title: string;
  domain: string;
  moves: number;
  total: number;
}

/** The gallery's processes by domain, filtered by a search over their
 * names (HRP-930). Domains read in the interface language; the process
 * names are the library's English. */
export function GalleryList({ items, href }: { items: GalleryItem[]; href: string }) {
  const t = useTranslations("publicCheck");
  // The interface locale, not the runtime's: the server and the browser
  // sort alike, so hydration matches.
  const locale = useLocale();
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const shown = items.filter((item) => item.title.toLowerCase().includes(needle));
  const domains = [...new Set(shown.map((item) => item.domain))]
    .map((code) => ({ code, label: t(`galleryDomain_${code}`) }))
    .sort((a, b) => a.label.localeCompare(b.label, locale));

  return (
    <div className="space-y-8">
      <Input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={t("gallerySearchPlaceholder")}
        aria-label={t("gallerySearchLabel")}
        className="h-11 text-base"
        data-testid="check-gallery-search"
      />
      {domains.map(({ code, label }) => (
        <section
          key={code}
          className="space-y-2"
          aria-labelledby={`check-gallery-domain-${code}`}
          data-testid={`check-gallery-domain-${code}`}
        >
          <h2 id={`check-gallery-domain-${code}`} className="text-lg font-semibold">
            {label}
          </h2>
          <ul className="divide-y rounded-lg border">
            {shown
              .filter((item) => item.domain === code)
              .map((item) => (
                <li key={item.slug}>
                  <Link
                    href={`${href}/${item.slug}`}
                    className="flex flex-col gap-0.5 px-4 py-3 hover:bg-muted/50 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4"
                    data-testid={`check-gallery-item-${item.slug}`}
                  >
                    <span className="font-medium text-primary">{item.title}</span>
                    <span className="shrink-0 text-sm text-muted-foreground">
                      {t("galleryStepsLine", { moves: item.moves, total: item.total })}
                    </span>
                  </Link>
                </li>
              ))}
          </ul>
        </section>
      ))}
      {shown.length === 0 ? (
        <p className="text-muted-foreground" data-testid="check-gallery-empty">
          {t("galleryEmpty")}
        </p>
      ) : null}
    </div>
  );
}
