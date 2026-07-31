"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2, RotateCcw, X } from "lucide-react";

import { api } from "@/lib/api";
import type {
  AssessmentHistoryEvent,
  AssessmentHistoryResponse,
} from "@/lib/types";
import { formatDateTime } from "@/lib/date-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { toast } from "sonner";

interface CanvasVersionsSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Vacancy whose audit log feeds the timeline (HRP-266). */
  vacancyId: string;
  /** Optional pre-filter — pin one candidate when the sheet is launched
   * from a row-level button. The Candidate input inside the sheet stays
   * disabled in that case so the user cannot widen scope by accident. */
  candidateVacancyId?: string;
  /** Optional pre-filter — same posture, pins one evaluator. */
  evaluatorId?: string;
  /** Triggered after every successful revert so the parent grid can
   * refetch matrix aggregates and clear local optimistic state. */
  onReverted?: () => void;
}

interface FilterState {
  candidateVacancyId: string;
  evaluatorId: string;
  since: string;
  until: string;
  onlyDivergence: boolean;
}

function emptyFilters(
  candidateVacancyId?: string,
  evaluatorId?: string,
): FilterState {
  return {
    candidateVacancyId: candidateVacancyId ?? "",
    evaluatorId: evaluatorId ?? "",
    since: "",
    until: "",
    onlyDivergence: false,
  };
}

function operationLabel(
  t: (key: string) => string,
  op: AssessmentHistoryEvent["operation"],
): string {
  if (op === "upsert") return t("canvasVersionsOpCreated");
  if (op === "revert") return t("canvasVersionsOpReverted");
  return t("canvasVersionsOpUpdated");
}

function formatChange(event: AssessmentHistoryEvent): string {
  const fmt = (v: number | null) => (v === null ? "—" : v.toFixed(1));
  return `${fmt(event.old_score)} → ${fmt(event.new_score)}`;
}

export function CanvasVersionsSheet({
  open,
  onOpenChange,
  vacancyId,
  candidateVacancyId,
  evaluatorId,
  onReverted,
}: CanvasVersionsSheetProps) {
  const t = useTranslations("recruitment");
  const [filters, setFilters] = useState<FilterState>(() =>
    emptyFilters(candidateVacancyId, evaluatorId),
  );
  const [items, setItems] = useState<AssessmentHistoryEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revertEvent, setRevertEvent] = useState<AssessmentHistoryEvent | null>(
    null,
  );

  const queryString = useMemo(() => {
    const qs = new URLSearchParams();
    if (filters.candidateVacancyId)
      qs.set("candidate_vacancy_id", filters.candidateVacancyId);
    if (filters.evaluatorId) qs.set("evaluator_id", filters.evaluatorId);
    if (filters.since) qs.set("since", filters.since);
    if (filters.until) qs.set("until", filters.until);
    if (filters.onlyDivergence) qs.set("only_divergence", "true");
    qs.set("limit", "200");
    return qs.toString();
  }, [filters]);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<AssessmentHistoryResponse>(
        `/recruitment/vacancies/${vacancyId}/assessment-history?${queryString}`,
      );
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t("canvasVersionsLoadFailed"),
      );
    } finally {
      setLoading(false);
    }
  }, [vacancyId, queryString, t]);

  useEffect(() => {
    if (!open) return;
    void fetchHistory();
  }, [open, fetchHistory]);

  const handleRevertConfirm = useCallback(async () => {
    if (!revertEvent) return;
    if (!revertEvent.evaluator_id) {
      toast.error(t("canvasVersionsRevertOnlyManager"));
      return;
    }
    try {
      await api.post(
        `/recruitment/candidate-vacancies/${revertEvent.candidate_vacancy_id}/assessments/${revertEvent.competence_id}/evaluators/${revertEvent.evaluator_id}/revert`,
        { audit_event_id: revertEvent.id },
      );
      toast.success(t("canvasVersionsToastReverted"));
      setRevertEvent(null);
      await fetchHistory();
      onReverted?.();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("canvasVersionsRevertFailed"),
      );
    }
  }, [revertEvent, fetchHistory, onReverted, t]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-[480px] flex-col"
        data-testid="canvas-versions-sheet"
      >
        <SheetHeader>
          <SheetTitle>{t("canvasVersionsTitle")}</SheetTitle>
          <SheetDescription>{t("canvasVersionsDescription")}</SheetDescription>
        </SheetHeader>

        <div className="space-y-2 border-b px-4 pb-3 text-xs">
          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1">
              <span className="block text-[10px] uppercase text-muted-foreground">
                {t("canvasVersionsFilterCandidateLabel")}
              </span>
              <Input
                value={filters.candidateVacancyId}
                onChange={(e) =>
                  setFilters((prev) => ({
                    ...prev,
                    candidateVacancyId: e.target.value.trim(),
                  }))
                }
                placeholder={t("canvasVersionsFilterUuidPlaceholder")}
                data-testid="canvas-versions-filter-candidate"
                disabled={Boolean(candidateVacancyId)}
              />
            </label>
            <label className="space-y-1">
              <span className="block text-[10px] uppercase text-muted-foreground">
                {t("canvasVersionsFilterEvaluatorLabel")}
              </span>
              <Input
                value={filters.evaluatorId}
                onChange={(e) =>
                  setFilters((prev) => ({
                    ...prev,
                    evaluatorId: e.target.value.trim(),
                  }))
                }
                placeholder={t("canvasVersionsFilterUuidPlaceholder")}
                data-testid="canvas-versions-filter-evaluator"
                disabled={Boolean(evaluatorId)}
              />
            </label>
            <label className="space-y-1">
              <span className="block text-[10px] uppercase text-muted-foreground">
                {t("canvasVersionsFilterSince")}
              </span>
              <Input
                type="datetime-local"
                value={filters.since}
                onChange={(e) =>
                  setFilters((prev) => ({
                    ...prev,
                    since: e.target.value,
                  }))
                }
                data-testid="canvas-versions-filter-since"
              />
            </label>
            <label className="space-y-1">
              <span className="block text-[10px] uppercase text-muted-foreground">
                {t("canvasVersionsFilterUntil")}
              </span>
              <Input
                type="datetime-local"
                value={filters.until}
                onChange={(e) =>
                  setFilters((prev) => ({
                    ...prev,
                    until: e.target.value,
                  }))
                }
                data-testid="canvas-versions-filter-until"
              />
            </label>
          </div>
          <label
            className="flex items-center gap-2 pt-1"
            data-testid="canvas-versions-filter-only-divergence-wrapper"
          >
            <Checkbox
              checked={filters.onlyDivergence}
              onCheckedChange={(value) =>
                setFilters((prev) => ({
                  ...prev,
                  onlyDivergence: value === true,
                }))
              }
              data-testid="canvas-versions-filter-only-divergence"
            />
            <span>{t("canvasVersionsOnlyDivergence")}</span>
          </label>
          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <span>{t("canvasVersionsMatchCount", { count: total })}</span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                setFilters(emptyFilters(candidateVacancyId, evaluatorId))
              }
              data-testid="canvas-versions-filter-clear"
            >
              <X className="mr-1 size-3" />
              {t("canvasVersionsClearFilters")}
            </Button>
          </div>
        </div>

        <div
          className="flex-1 overflow-y-auto px-4 pb-4"
          data-testid="canvas-versions-list"
        >
          {loading && (
            <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
              <Loader2 className="mr-2 size-4 animate-spin" />
              {t("loading")}
            </div>
          )}
          {error && !loading && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              {error}
            </div>
          )}
          {!loading && !error && items.length === 0 && (
            <p className="py-10 text-center text-sm text-muted-foreground">
              {t("canvasVersionsEmpty")}
            </p>
          )}
          {!loading && !error && items.length > 0 && (
            <ul className="space-y-2 text-xs">
              {items.map((event) => (
                <li
                  key={event.id}
                  data-testid={`canvas-versions-row-${event.id}`}
                  className="space-y-1 rounded-md border p-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[10px] text-muted-foreground">
                      v{event.version ?? "?"} ·{" "}
                      {operationLabel(t, event.operation)}
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      {formatDateTime(event.created_at)}
                    </span>
                  </div>
                  <p>
                    <strong>{event.user_name ?? "—"}</strong>{" "}
                    <span className="text-muted-foreground">·</span>{" "}
                    <span className="font-mono">{formatChange(event)}</span>
                  </p>
                  {event.new_comment && (
                    <p className="truncate text-muted-foreground">
                      &ldquo;{event.new_comment}&rdquo;
                    </p>
                  )}
                  <div className="flex items-center justify-between gap-2 pt-1">
                    <Badge variant="outline" className="font-mono text-[9px]">
                      {event.action}
                    </Badge>
                    {event.evaluator_id && event.operation !== "revert" && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setRevertEvent(event)}
                        data-testid={`canvas-versions-revert-btn-${event.id}`}
                      >
                        <RotateCcw className="mr-1 size-3" />
                        {t("canvasVersionsRevert")}
                      </Button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="border-t p-3 text-right">
          <SheetClose render={<Button variant="outline" size="sm" />}>
            {t("canvasVersionsClose")}
          </SheetClose>
        </div>

        <ConfirmDialog
          open={revertEvent !== null}
          onOpenChange={(next) => {
            if (!next) setRevertEvent(null);
          }}
          title={t("canvasVersionsRevertTitle")}
          description={
            revertEvent
              ? t("canvasVersionsRevertDescription", {
                  previous:
                    revertEvent.old_score === null
                      ? t("canvasVersionsRevertNoScore")
                      : revertEvent.old_score.toFixed(1),
                  current:
                    revertEvent.new_score === null
                      ? "—"
                      : revertEvent.new_score.toFixed(1),
                })
              : undefined
          }
          confirmLabel={t("canvasVersionsRevert")}
          destructive
          onConfirm={handleRevertConfirm}
          testId="canvas-versions-revert-confirm"
        />
      </SheetContent>
    </Sheet>
  );
}
