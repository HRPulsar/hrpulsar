"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import type { FunnelStage, CandidateVacancy } from "@/lib/types";

interface FunnelKanbanProps {
  stages: FunnelStage[];
  candidates: CandidateVacancy[];
  onStatusChange?: (
    candidateVacancyId: string,
    newStageId: string,
  ) => void;
}

const DEFAULT_COLOR_TOKENS: Record<string, string> = {
  new: "var(--accent)",
  screening: "var(--rec-ai-accent)",
  interview: "var(--rec-data-partial)",
  offer: "var(--rec-match-high)",
  hired: "var(--rec-data-full)",
  rejected: "var(--rec-red-flag)",
};

function stageColor(stage: FunnelStage): string {
  // HRP-357 REDO: active stages are always blue; only terminal stages
  // keep their own color (same rule as the Candidates block chips).
  if (!stage.is_terminal) return "var(--accent)";
  return stage.color || DEFAULT_COLOR_TOKENS[stage.code] || "var(--muted-foreground)";
}

function CandidateCard({
  cv,
  stages,
  onStatusChange,
}: {
  cv: CandidateVacancy;
  stages: FunnelStage[];
  onStatusChange?: FunnelKanbanProps["onStatusChange"];
}) {
  const t = useTranslations("recruitment");
  return (
    <Card size="sm" data-testid="kanban-card">
      <CardContent className="space-y-2">
        <p className="text-sm font-medium">
          {cv.candidate_name || t("funnelUnknownCandidate")}
        </p>
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
              cv.status === "rejected"
                ? "bg-[color-mix(in_oklch,var(--rec-red-flag)_15%,transparent)] text-[var(--rec-red-flag)]"
                : cv.status === "hired"
                  ? "bg-[color-mix(in_oklch,var(--rec-data-full)_15%,transparent)] text-[var(--rec-data-full)]"
                  : "bg-muted text-muted-foreground",
            )}
          >
            {cv.stage_name || cv.status}
          </span>
          {cv.ranking_score != null && (
            <span className="text-xs text-muted-foreground">
              {t("funnelScore", { score: cv.ranking_score })}
            </span>
          )}
        </div>
        {onStatusChange && stages.length > 1 && (
          <select
            className="w-full rounded-md border bg-transparent px-2 py-1 text-xs text-foreground"
            value={cv.stage_id || ""}
            onChange={(e) => {
              if (e.target.value && e.target.value !== cv.stage_id) {
                onStatusChange(cv.id, e.target.value);
              }
            }}
            data-testid="kanban-stage-select"
          >
            <option value="" disabled>
              {t("funnelMoveTo")}
            </option>
            {stages.map((s) => (
              <option key={s.id} value={s.id} disabled={s.id === cv.stage_id}>
                {s.name}
              </option>
            ))}
          </select>
        )}
      </CardContent>
    </Card>
  );
}

export function FunnelKanban({
  stages,
  candidates,
  onStatusChange,
}: FunnelKanbanProps) {
  const t = useTranslations("recruitment");
  const sortedStages = useMemo(
    () => [...stages].sort((a, b) => a.sort_order - b.sort_order),
    [stages],
  );

  const candidatesByStage = useMemo(() => {
    const map = new Map<string, CandidateVacancy[]>();
    for (const s of sortedStages) {
      map.set(s.id, []);
    }
    // "unassigned" bucket for candidates without a stage
    map.set("__unassigned__", []);

    for (const cv of candidates) {
      const key = cv.stage_id && map.has(cv.stage_id) ? cv.stage_id : "__unassigned__";
      map.get(key)!.push(cv);
    }
    return map;
  }, [sortedStages, candidates]);

  if (sortedStages.length === 0) {
    return (
      <div
        data-testid="recruitment-kanban"
        className="flex items-center justify-center rounded-lg border border-dashed p-8 text-sm text-muted-foreground"
      >
        {t("funnelNoStages")}
      </div>
    );
  }

  const unassigned = candidatesByStage.get("__unassigned__") || [];

  return (
    <div
      data-testid="recruitment-kanban"
      className="overflow-x-auto"
    >
      <div className="flex gap-3 pb-2" style={{ minWidth: sortedStages.length * 296 }}>
        {sortedStages.map((stage) => {
          const cards = candidatesByStage.get(stage.id) || [];
          const color = stageColor(stage);

          return (
            <div
              key={stage.id}
              className="flex w-[280px] shrink-0 flex-col rounded-xl border bg-muted/30"
              data-testid="kanban-column"
            >
              {/* Column header */}
              <div className="flex items-center gap-2 border-b px-3 py-2.5">
                <span
                  className="size-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: color }}
                />
                <span className="text-sm font-semibold">{stage.name}</span>
                <span className="ml-auto text-xs text-muted-foreground">
                  {cards.length}
                </span>
              </div>

              {/* Cards */}
              <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-2">
                {cards.length === 0 && (
                  <p className="py-4 text-center text-xs text-muted-foreground">
                    {t("funnelNoCandidates")}
                  </p>
                )}
                {cards.map((cv) => (
                  <CandidateCard
                    key={cv.id}
                    cv={cv}
                    stages={sortedStages}
                    onStatusChange={onStatusChange}
                  />
                ))}
              </div>
            </div>
          );
        })}

        {/* Unassigned column */}
        {unassigned.length > 0 && (
          <div className="flex w-[280px] shrink-0 flex-col rounded-xl border bg-muted/30">
            <div className="flex items-center gap-2 border-b px-3 py-2.5">
              <span className="size-2.5 shrink-0 rounded-full bg-muted-foreground/40" />
              <span className="text-sm font-semibold">
                {t("funnelUnassigned")}
              </span>
              <span className="ml-auto text-xs text-muted-foreground">
                {unassigned.length}
              </span>
            </div>
            <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-2">
              {unassigned.map((cv) => (
                <CandidateCard
                  key={cv.id}
                  cv={cv}
                  stages={sortedStages}
                  onStatusChange={onStatusChange}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
