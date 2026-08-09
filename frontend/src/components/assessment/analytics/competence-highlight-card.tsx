"use client";

import { Sprout, TrendingUp } from "lucide-react";
import { useTranslations } from "next-intl";

import { MatchPercentChip } from "@/components/assessment/match-percent-chip";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { GroupAnalyticsCompetenceAverage } from "@/lib/types";

interface CompetenceHighlightCardProps {
  variant: "growth" | "top";
  items: GroupAnalyticsCompetenceAverage[];
}

/**
 * "Growth zones" / "Top competences". The caller hides the card when the
 * list is empty — the spec asks for the block to disappear, not to render
 * an empty state.
 */
export function CompetenceHighlightCard({
  variant,
  items,
}: CompetenceHighlightCardProps) {
  const t = useTranslations("assessments");
  const isGrowth = variant === "growth";
  const testId = isGrowth
    ? "group-analytics-growth-zones"
    : "group-analytics-top-competences";
  const Icon = isGrowth ? Sprout : TrendingUp;

  return (
    <Card data-testid={testId}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <Icon
            className={
              isGrowth
                ? "h-4 w-4 text-amber-600"
                : "h-4 w-4 text-green-600"
            }
          />
          {isGrowth ? t("analyticsGrowthZones") : t("analyticsTopCompetences")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {items.map((item) => (
          <div
            key={item.competence_id}
            className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-muted/60"
            data-testid={`${testId}-row-${item.competence_id}`}
          >
            <span className="min-w-0 flex-1 truncate text-sm">
              {item.competence_title}
            </span>
            <MatchPercentChip percent={item.percent} />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
