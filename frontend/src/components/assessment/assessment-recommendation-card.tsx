"use client";

import { AlertTriangle, Star } from "lucide-react";
import { useTranslations } from "next-intl";

import type { AssessmentRecommendation, GradeRecommendationItem } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export interface AssessmentRecommendationCardProps {
  recommendation: AssessmentRecommendation;
}

function formatPercent(value: number): string {
  return `${Math.round(value)}%`;
}

function ProgressBar({ percent, passed }: { percent: number; passed: boolean }) {
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
      <div
        className={
          passed ? "h-full bg-green-500 transition-all" : "h-full bg-red-500 transition-all"
        }
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

function GradeRow({ item }: { item: GradeRecommendationItem }) {
  const t = useTranslations("assessments");

  if (item.excluded) {
    return (
      <div
        className="flex items-center justify-between rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground"
        data-testid={`assessment-recommendation-grade-${item.grade_id}`}
      >
        <span className="font-medium text-foreground">{item.grade_title ?? "—"}</span>
        <span className="text-xs">{t("recNoRequirements")}</span>
      </div>
    );
  }

  return (
    <div
      className="space-y-1.5"
      data-testid={`assessment-recommendation-grade-${item.grade_id}`}
    >
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{item.grade_title ?? "—"}</span>
        <span className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="font-mono text-foreground">{formatPercent(item.percent)}</span>
          {item.passed ? (
            <span className="text-green-600">{t("recConfirmedShort")}</span>
          ) : item.missing_percent != null ? (
            <span className="text-red-600">
              {t("recShortBy", { percent: formatPercent(item.missing_percent) })}
            </span>
          ) : (
            <span className="text-red-600">{t("recNotConfirmedShort")}</span>
          )}
        </span>
      </div>
      <ProgressBar percent={item.percent} passed={item.passed} />
    </div>
  );
}

export function AssessmentRecommendationCard({
  recommendation,
}: AssessmentRecommendationCardProps) {
  const t = useTranslations("assessments");
  const items = [...recommendation.grades].sort((a, b) => a.sort_index - b.sort_index);
  const evaluable = items.filter((g) => !g.excluded);
  const recommended = items.find(
    (g) => g.grade_id === recommendation.recommended_grade_id,
  );
  const passed = recommendation.recommended_grade_passed;
  const threshold = recommendation.passing_score;

  // Case C: a single evaluable grade — render compact summary.
  if (evaluable.length === 1 && recommended && !recommended.excluded) {
    return (
      <Card data-testid="assessment-recommendation-card">
        <CardHeader>
          <CardTitle className="text-base">{t("gradeMatch")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="flex items-baseline justify-between">
              <span className="text-base font-semibold">
                {recommended.grade_title ?? "—"}
              </span>
              <span className="text-sm text-muted-foreground">
                {t("matchLabel")}{" "}
                <span className="font-mono text-foreground">
                  {formatPercent(recommended.percent)}
                </span>
              </span>
            </div>
            <p
              className="text-xs text-muted-foreground"
              data-testid="assessment-recommendation-status"
            >
              {passed
                ? t("recConfirmed", { threshold: threshold ?? "—" })
                : t("recNotConfirmed", { threshold: threshold ?? "—" })}
            </p>
            <ProgressBar percent={recommended.percent} passed={passed} />
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card data-testid="assessment-recommendation-card">
      <CardHeader>
        <CardTitle className="text-base">{t("recommendedGrade")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {recommended && !recommended.excluded ? (
          <div className="flex items-start gap-3">
            {passed ? (
              <Star className="mt-0.5 h-5 w-5 fill-amber-400 text-amber-500" />
            ) : (
              <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-600" />
            )}
            <div className="flex-1">
              <div className="flex items-baseline justify-between">
                <span className="text-base font-semibold">
                  {recommended.grade_title ?? "—"}
                </span>
                <span className="text-sm text-muted-foreground">
                  {t("matchLabel")}{" "}
                  <span className="font-mono text-foreground">
                    {formatPercent(recommended.percent)}
                  </span>
                </span>
              </div>
              <p
                className="mt-1 text-xs text-muted-foreground"
                data-testid="assessment-recommendation-status"
              >
                {passed
                  ? t("recConfirmed", { threshold: threshold ?? "—" })
                  : recommended.missing_percent != null
                    ? t("recClosest", {
                        threshold: threshold ?? "—",
                        missing: formatPercent(recommended.missing_percent),
                      })
                    : t("recNotConfirmed", { threshold: threshold ?? "—" })}
              </p>
            </div>
          </div>
        ) : (
          <p
            className="text-sm text-muted-foreground"
            data-testid="assessment-recommendation-status"
          >
            {t("recUndetermined")}
          </p>
        )}

        {items.length > 0 && (
          <div className="space-y-3 border-t pt-3">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{t("allGradesInSpecialization")}</span>
              {threshold != null && (
                <Badge variant="outline" className="text-[10px]">
                  {t("thresholdBadge", { threshold })}
                </Badge>
              )}
            </div>
            <div className="space-y-2.5">
              {items.map((g) => (
                <GradeRow key={g.grade_id} item={g} />
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
