"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { VacancyAnalytics } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2 } from "lucide-react";

interface Props {
  vacancyId: string;
}

/** The unit suffixes live in the `recruitment` namespace — the caller hands
 *  in its own translator so this stays a pure helper. */
function formatDuration(
  t: (key: string, values?: Record<string, string | number>) => string,
  seconds: number | null,
): string {
  if (seconds == null) return "—";
  if (seconds < 60)
    return t("analyticsTabDurationSeconds", { value: Math.round(seconds) });
  if (seconds < 3600)
    return t("analyticsTabDurationMinutes", {
      value: Math.round(seconds / 60),
    });
  if (seconds < 86400)
    return t("analyticsTabDurationHours", {
      value: (seconds / 3600).toFixed(1),
    });
  return t("analyticsTabDurationDays", { value: (seconds / 86400).toFixed(1) });
}

export function VacancyAnalyticsTab({ vacancyId }: Props) {
  const t = useTranslations("recruitment");
  const [data, setData] = useState<VacancyAnalytics | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    let cancelled = false;
    void api
      .get<VacancyAnalytics>(`/recruitment/vacancies/${vacancyId}/analytics`)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        setStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setData(null);
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [vacancyId]);

  const maxCount = useMemo(() => {
    if (!data) return 1;
    return Math.max(1, ...data.funnel.map((s) => s.candidate_count));
  }, [data]);

  if (status === "loading") {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (!data) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("analyticsTabLoadFailed")}
      </p>
    );
  }

  // HRP-425: a vacancy names its own terminal stages, so the tiles carry
  // those names ("Hired" / "Rejected" only stand in when the funnel has no
  // terminal stage of that kind).
  const hiredLabel =
    data.positive_stage_names.length > 0
      ? data.positive_stage_names.join(", ")
      : t("analyticsTabHired");
  const rejectedLabel =
    data.negative_stage_names.length > 0
      ? data.negative_stage_names.join(", ")
      : t("analyticsTabRejected");

  return (
    <div className="space-y-6" data-testid="recruitment-vacancy-analytics">
      <div className="grid gap-4 sm:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">
              {t("analyticsTabTotalCandidates")}
            </CardTitle>
          </CardHeader>
          <CardContent
            className="text-2xl font-semibold"
            data-testid="recruitment-vacancy-analytics-total"
          >
            {data.total_candidates}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">
              {hiredLabel}
            </CardTitle>
          </CardHeader>
          <CardContent
            className="text-2xl font-semibold text-green-700"
            data-testid="recruitment-vacancy-analytics-hired"
          >
            {data.win_loss.hired}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">
              {rejectedLabel}
            </CardTitle>
          </CardHeader>
          <CardContent
            className="text-2xl font-semibold text-red-700"
            data-testid="recruitment-vacancy-analytics-rejected"
          >
            {data.win_loss.rejected}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">
              {t("analyticsTabInProgress")}
            </CardTitle>
          </CardHeader>
          <CardContent
            className="text-2xl font-semibold"
            data-testid="recruitment-vacancy-analytics-in-progress"
          >
            {data.win_loss.in_progress}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("analyticsTabFunnel")}</CardTitle>
        </CardHeader>
        <CardContent>
          {data.funnel.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("analyticsTabNoStages")}
            </p>
          ) : (
            <ul className="space-y-2">
              {data.funnel.map((stage) => (
                <li key={String(stage.stage_id)} className="flex items-center gap-3">
                  <span className="w-32 truncate text-sm">
                    {stage.stage_name ?? t("analyticsTabUnnamedStage")}
                  </span>
                  <div className="relative h-6 flex-1 overflow-hidden rounded bg-muted">
                    <div
                      className="h-full bg-primary/70"
                      style={{ width: `${(stage.candidate_count / maxCount) * 100}%` }}
                    />
                    <span className="absolute inset-0 flex items-center justify-end pr-2 text-xs font-medium">
                      {stage.candidate_count}
                    </span>
                  </div>
                  <span className="w-20 text-right text-xs text-muted-foreground">
                    {formatDuration(t, stage.median_seconds_in_stage)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
