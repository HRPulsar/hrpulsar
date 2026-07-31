"use client";

import { useState } from "react";
import { Lock } from "lucide-react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type {
  ExistingTreeIndicator,
  GeneratedIndicator,
  GeneratedTreePayload,
} from "@/lib/api/competence-generation";

export interface IndicatorsListProps {
  payload: GeneratedTreePayload;
  selection: Record<string, boolean>;
  onToggle: (nodeId: string, selected: boolean) => void | Promise<void>;
  lockedIds?: Set<string>;
  /** HRP-114 re-spec: existing indicators of the competence, rendered
   * read-only above the generated ones so the user can compare. */
  existingIndicators?: ExistingTreeIndicator[] | null;
}

export function IndicatorsList({
  payload,
  selection,
  onToggle,
  lockedIds,
  existingIndicators,
}: IndicatorsListProps) {
  const t = useTranslations("competences");
  const indicators: GeneratedIndicator[] = payload.indicators ?? [];
  const toggleable = indicators.filter((i) => {
    if (!i.temp_id) return false;
    const isLocked =
      !!i.snapshot_id || (lockedIds?.has(i.temp_id) ?? false);
    // A locked-and-already-checked row can't be unchecked, so it can't be
    // part of a bulk toggle either — exclude it from the all/none totals.
    return !(isLocked && selection[i.temp_id]);
  });
  const selectedCount = indicators.filter(
    (i) => i.temp_id && selection[i.temp_id],
  ).length;
  const allSelected =
    toggleable.length > 0 &&
    toggleable.every((i) => i.temp_id && selection[i.temp_id]);
  const [bulkBusy, setBulkBusy] = useState(false);

  async function toggleAll(target: boolean) {
    if (bulkBusy) return;
    setBulkBusy(true);
    let failed = 0;
    try {
      for (const ind of toggleable) {
        if (!ind.temp_id) continue;
        if (!!selection[ind.temp_id] === target) continue;
        // Per-row failures already surface as individual toasts via the
        // drawer's onToggle handler — swallow here and aggregate counts so
        // the user gets a single bulk summary instead of N toasts.
        try {
          await onToggle(ind.temp_id, target);
        } catch {
          failed += 1;
        }
      }
      if (failed > 0) {
        toast.error(t("toastIndicatorsUpdateFailed", { count: failed }));
      }
    } finally {
      setBulkBusy(false);
    }
  }

  const existing = (existingIndicators ?? []).filter(Boolean);
  const newCount = indicators.filter((ind) => !ind.snapshot_id).length;
  const [view, setView] = useState<"all" | "new-only">("all");
  const onlyDuplicates = existing.length > 0 && newCount === 0;

  return (
    <div data-testid="compgen-indicators-list" className="space-y-2">
      {existing.length > 0 && (
        <div
          data-testid="compgen-result-summary"
          className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 text-xs"
        >
          <span className="text-muted-foreground">
            {t.rich("resultSummaryIndicators", {
              newCount: selectedCount,
              existingCount: existing.length,
              new: (chunks) => (
                <span
                  data-testid="compgen-result-summary-new-count"
                  className="font-medium text-foreground"
                >
                  {chunks}
                </span>
              ),
              existing: (chunks) => (
                <span
                  data-testid="compgen-result-summary-existing-count"
                  className="font-medium text-foreground"
                >
                  {chunks}
                </span>
              ),
            })}
          </span>
          <div className="ml-auto inline-flex rounded-md border bg-background p-0.5">
            <Button
              data-testid="compgen-result-filter-show-all"
              type="button"
              size="sm"
              variant={view === "all" ? "default" : "ghost"}
              className="h-6 px-2 text-[11px]"
              onClick={() => setView("all")}
            >
              {t("filterAll")}
            </Button>
            <Button
              data-testid="compgen-result-filter-show-new-only"
              type="button"
              size="sm"
              variant={view === "new-only" ? "default" : "ghost"}
              className="h-6 px-2 text-[11px]"
              onClick={() => setView("new-only")}
            >
              {t("filterNewOnly")}
            </Button>
          </div>
        </div>
      )}
      {onlyDuplicates && view === "all" && (
        <div
          data-testid="compgen-result-empty-state-only-duplicates"
          className="rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-900 dark:text-amber-200"
        >
          {t("resultOnlyDuplicatesIndicators")}
        </div>
      )}
      {existing.length > 0 && view === "all" && (
        <div
          data-testid="compgen-result-existing"
          className="space-y-0.5 rounded-md border border-dashed bg-muted/20 p-2"
        >
          <div className="mb-1.5 flex items-center gap-2 px-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <Lock className="h-3 w-3" /> {t("resultExistingIndicatorsHeader")}
          </div>
          <TooltipProvider>
            {existing.map((ind) => (
              <div
                key={ind.id}
                data-testid={`compgen-result-item-existing-indicator-${ind.id}`}
                className="flex items-center gap-2 rounded-md bg-slate-50 px-2 py-1 text-[11px] text-slate-500 dark:bg-slate-900/40 dark:text-slate-400"
              >
                <Tooltip>
                  <TooltipTrigger>
                    <Checkbox
                      data-testid={`compgen-result-item-existing-indicator-${ind.id}-checkbox`}
                      checked
                      disabled
                      className="cursor-not-allowed"
                    />
                  </TooltipTrigger>
                  <TooltipContent side="right" className="max-w-xs text-xs">
                    {t("resultExistingTooltip")}
                  </TooltipContent>
                </Tooltip>
                <span className="flex-1 truncate">{ind.title}</span>
                {ind.skill_level && (
                  <Badge variant="outline" className="text-[10px]">
                    {ind.skill_level}
                  </Badge>
                )}
                <Badge
                  data-testid={`compgen-result-item-existing-indicator-${ind.id}-status-existing`}
                  variant="outline"
                  className="text-[10px] text-muted-foreground"
                >
                  {t("badgeExisting")}
                </Badge>
              </div>
            ))}
          </TooltipProvider>
        </div>
      )}
      {indicators.length > 0 && (
        <div className="flex items-center justify-between gap-2 pb-1">
          <span className="text-xs text-muted-foreground">
            {t("selectedOfTotal", {
              selected: selectedCount,
              total: indicators.length,
            })}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={bulkBusy || toggleable.length === 0}
            data-testid="compgen-indicators-btn-toggle-all"
            onClick={() => toggleAll(!allSelected)}
          >
            {bulkBusy
              ? t("bulkUpdating")
              : allSelected
                ? t("deselectAll")
                : t("selectAll")}
          </Button>
        </div>
      )}
      {indicators.map((ind, i) => {
        const tempId = ind.temp_id;
        const checked = !!(tempId && selection[tempId]);
        const isLocked =
          !!ind.snapshot_id || (lockedIds?.has(tempId ?? "") ?? false);
        return (
          <div
            key={tempId ?? `i${i}`}
            data-testid={`compgen-tree-node-${tempId ?? ""}`}
            className="flex items-center gap-2 rounded-md bg-muted/30 px-3 py-2 text-sm"
          >
            <Checkbox
              data-testid={`compgen-tree-checkbox-${tempId ?? ""}`}
              checked={checked}
              disabled={(isLocked && checked) || bulkBusy}
              onCheckedChange={(v) => {
                if (!tempId) return;
                onToggle(tempId, Boolean(v));
              }}
            />
            <span className="flex-1">{ind.title}</span>
            <Badge variant="secondary" className="text-[10px]">
              {ind.skill_level}
            </Badge>
          </div>
        );
      })}
      <div
        data-testid="compgen-drawer-counter"
        className="sticky bottom-0 mt-2 rounded-md border bg-background/95 px-3 py-2 text-xs text-muted-foreground"
      >
        {t.rich("counterIndicators", {
          selected: selectedCount,
          total: indicators.length,
          count: (chunks) => (
            <span className="font-medium text-foreground">{chunks}</span>
          ),
        })}
      </div>
    </div>
  );
}
