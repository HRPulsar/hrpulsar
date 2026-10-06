"use client";

import { type FormEvent, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Loader2, Search } from "lucide-react";
import { api } from "@/lib/api";
import type { Candidate, CandidateList } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { FormErrorBanner } from "@/components/ui/form-error";
import { Input } from "@/components/ui/input";
import { RecruitmentBreadcrumbs, RecruitmentTabs } from "@/components/recruitment";

// HRP-989: GDPR export and erasure run per candidate; this page is where
// the settings point to find that candidate without knowing the address.
export default function RecruitmentGdprPage() {
  const t = useTranslations("recruitment");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Candidate[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch(e: FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setError(null);
    try {
      const data = await api.get<CandidateList>(
        `/recruitment/candidates?q=${encodeURIComponent(q)}&limit=25`,
      );
      setResults(data.items);
    } catch (err) {
      // A failed search is not "nobody found": say what went wrong.
      setResults(null);
      setError(err instanceof Error ? err.message : t("toastGenericError"));
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="space-y-5" data-testid="recruitment-gdpr-page">
      <RecruitmentBreadcrumbs segments={[{ label: t("gdprTitle") }]} />
      <RecruitmentTabs />
      <header>
        <h1 className="text-xl font-semibold tracking-tight">
          {t("gdprTitle")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("gdprHubDescription")}
        </p>
      </header>

      <form onSubmit={handleSearch} className="flex max-w-xl gap-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("gdprHubSearchPlaceholder")}
          aria-label={t("gdprHubSearchPlaceholder")}
          data-testid="recruitment-gdpr-search-input"
        />
        <Button
          type="submit"
          disabled={searching || !query.trim()}
          data-testid="recruitment-gdpr-search-btn"
        >
          {searching ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Search className="size-4" />
          )}
          {t("gdprHubSearchBtn")}
        </Button>
      </form>

      <FormErrorBanner message={error} testId="recruitment-gdpr-search-error" />

      {results !== null &&
        (results.length === 0 ? (
          <p
            className="text-sm text-muted-foreground"
            data-testid="recruitment-gdpr-no-results"
          >
            {t("gdprHubNoResults")}
          </p>
        ) : (
          <Card>
            <CardContent className="divide-y p-0">
              {results.map((c) => (
                <Link
                  key={c.id}
                  href={`/recruitment/candidates/${c.id}/gdpr`}
                  className="flex items-center justify-between gap-3 px-4 py-3 text-sm hover:bg-muted/50"
                  data-testid={`recruitment-gdpr-candidate-${c.id}`}
                >
                  <span className="font-medium">{c.full_name}</span>
                  <span className="text-muted-foreground">{c.email}</span>
                </Link>
              ))}
            </CardContent>
          </Card>
        ))}
    </div>
  );
}
