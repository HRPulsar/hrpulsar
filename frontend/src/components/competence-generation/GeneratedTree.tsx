"use client";

import { ChevronDown, ChevronRight, Lock, Sparkles, Star } from "lucide-react";
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
import { useMemo, useState } from "react";
import type {
  ExistingTreeGroup,
  GeneratedCompetence,
  GeneratedGroup,
  GeneratedIndicator,
  GeneratedTreePayload,
} from "@/lib/api/competence-generation";

type TriState = "checked" | "unchecked" | "partial";

interface NodeStateMap {
  [tempId: string]: TriState;
}

export interface GeneratedTreeProps {
  payload: GeneratedTreePayload;
  selection: Record<string, boolean>;
  onToggle: (nodeId: string, selected: boolean) => void;
  /** Ids that come from the existing DB tree — locked, cannot be unchecked. */
  lockedIds?: Set<string>;
  /** HRP-114 re-spec: pre-existing subgroups + competences + indicators
   * surrounding the target. Rendered read-only above the generated nodes so
   * the user can compare what's already in the library vs. what AI is
   * about to add. Empty/undefined ⇒ no preview block. */
  existingTree?: ExistingTreeGroup[] | null;
}

function collectDescendantTempIds(
  group: GeneratedGroup,
  acc: string[],
): void {
  if (group.temp_id) acc.push(group.temp_id);
  for (const child of group.children ?? []) {
    collectDescendantTempIds(child, acc);
  }
  for (const comp of group.competences ?? []) {
    if (comp.temp_id) acc.push(comp.temp_id);
    for (const ind of comp.indicators ?? []) {
      if (ind.temp_id) acc.push(ind.temp_id);
    }
  }
}

function competenceTempIds(comp: GeneratedCompetence): string[] {
  const ids: string[] = [];
  if (comp.temp_id) ids.push(comp.temp_id);
  for (const ind of comp.indicators ?? []) {
    if (ind.temp_id) ids.push(ind.temp_id);
  }
  return ids;
}

function deriveStateForIds(
  ids: string[],
  selection: Record<string, boolean>,
): TriState {
  if (ids.length === 0) return "unchecked";
  let checked = 0;
  for (const id of ids) {
    if (selection[id]) checked += 1;
  }
  if (checked === 0) return "unchecked";
  if (checked === ids.length) return "checked";
  return "partial";
}

function buildStateMap(
  payload: GeneratedTreePayload,
  selection: Record<string, boolean>,
): NodeStateMap {
  const map: NodeStateMap = {};
  for (const group of payload.groups ?? []) {
    walkGroup(group, selection, map);
  }
  for (const ind of payload.indicators ?? []) {
    if (ind.temp_id) {
      map[ind.temp_id] = selection[ind.temp_id] ? "checked" : "unchecked";
    }
  }
  return map;
}

function walkGroup(
  group: GeneratedGroup,
  selection: Record<string, boolean>,
  map: NodeStateMap,
): void {
  for (const child of group.children ?? []) walkGroup(child, selection, map);
  for (const comp of group.competences ?? []) {
    for (const ind of comp.indicators ?? []) {
      if (ind.temp_id) {
        map[ind.temp_id] = selection[ind.temp_id] ? "checked" : "unchecked";
      }
    }
    if (comp.temp_id) {
      map[comp.temp_id] = deriveStateForIds(
        competenceTempIds(comp),
        selection,
      );
    }
  }
  if (group.temp_id) {
    const ids: string[] = [];
    collectDescendantTempIds(group, ids);
    map[group.temp_id] = deriveStateForIds(ids, selection);
  }
}

function countSelectedCompetences(
  payload: GeneratedTreePayload,
  selection: Record<string, boolean>,
): number {
  let count = 0;
  function visit(group: GeneratedGroup) {
    for (const c of group.competences ?? []) {
      if (c.temp_id && selection[c.temp_id]) count += 1;
    }
    for (const ch of group.children ?? []) visit(ch);
  }
  for (const g of payload.groups ?? []) visit(g);
  return count;
}

export function GeneratedTree({
  payload,
  selection,
  onToggle,
  lockedIds,
  existingTree,
}: GeneratedTreeProps) {
  const t = useTranslations("competences");
  const stateMap = buildStateMap(payload, selection);
  const selectedTotal = countSelectedCompetences(payload, selection);
  // HRP-114 re-spec: filter and summary only kick in when the caller passes
  // an existing tree (group scope today). Other surfaces keep the legacy
  // single-list rendering.
  const [view, setView] = useState<"all" | "new-only">("all");
  const existingCount = useMemo(
    () => countExistingItems(existingTree ?? []),
    [existingTree],
  );
  const newSuggestionsCount = useMemo(
    () => countNewSuggestions(payload),
    [payload],
  );
  const showExistingBlock =
    !!existingTree && existingTree.length > 0 && view === "all";
  const onlyDuplicates =
    !!existingTree && newSuggestionsCount === 0 && existingCount > 0;

  return (
    <div data-testid="compgen-tree" className="space-y-2">
      {existingTree && existingTree.length > 0 && (
        <div
          data-testid="compgen-result-summary"
          className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 text-xs"
        >
          <span className="text-muted-foreground">
            {t.rich("resultSummaryTree", {
              newCount: selectedTotal,
              existingCount,
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
          <div className="ml-auto inline-flex rounded-md border bg-background p-0.5 text-[11px]">
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
          {t("resultOnlyDuplicatesTree")}
        </div>
      )}

      {showExistingBlock && (
        <div
          data-testid="compgen-result-existing"
          className="rounded-md border border-dashed bg-muted/20 p-2"
        >
          <div className="mb-1.5 flex items-center gap-2 px-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <Lock className="h-3 w-3" /> {t("resultExistingGroupHeader")}
          </div>
          <TooltipProvider>
            <div className="space-y-1">
              {(existingTree ?? []).map((eg) => (
                <ExistingGroupRow key={eg.id} group={eg} depth={0} />
              ))}
            </div>
          </TooltipProvider>
        </div>
      )}

      <div className="space-y-1">
        {(payload.groups ?? []).map((g, i) => (
          <GroupRow
            key={g.temp_id ?? `g${i}`}
            group={g}
            depth={0}
            selection={selection}
            stateMap={stateMap}
            onToggle={onToggle}
            lockedIds={lockedIds}
          />
        ))}
      </div>
      <div
        data-testid="compgen-drawer-counter"
        className="sticky bottom-0 mt-2 rounded-md border bg-background/95 px-3 py-2 text-xs text-muted-foreground"
      >
        {t.rich("counterCompetences", {
          selected: selectedTotal,
          count: (chunks) => (
            <span className="font-medium text-foreground">{chunks}</span>
          ),
        })}
      </div>
    </div>
  );
}

function GroupRow({
  group,
  depth,
  selection,
  stateMap,
  onToggle,
  lockedIds,
}: {
  group: GeneratedGroup;
  depth: number;
  selection: Record<string, boolean>;
  stateMap: NodeStateMap;
  onToggle: (nodeId: string, selected: boolean) => void;
  lockedIds?: Set<string>;
}) {
  const t = useTranslations("competences");
  const [expanded, setExpanded] = useState(true);
  const tempId = group.temp_id;
  const tri = tempId ? stateMap[tempId] : "unchecked";
  const isLocked =
    !!group.snapshot_id || (lockedIds?.has(tempId ?? "") ?? false);
  const isNew = !group.snapshot_id;

  return (
    <div data-testid={`compgen-tree-node-${tempId ?? ""}`}>
      <div
        className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted/50"
        style={{ paddingLeft: `${depth * 20 + 8}px` }}
      >
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex h-5 w-5 items-center justify-center text-muted-foreground"
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </button>
        <Checkbox
          data-testid={`compgen-tree-checkbox-${tempId ?? ""}`}
          checked={tri === "checked"}
          indeterminate={tri === "partial"}
          disabled={isLocked && tri === "checked"}
          onCheckedChange={(v) => {
            if (!tempId) return;
            onToggle(tempId, Boolean(v));
          }}
        />
        <span
          className={`text-sm font-medium ${isNew ? "text-primary" : ""}`}
          title={group.description ?? undefined}
        >
          {group.title}
        </span>
        {isNew && (
          <Badge variant="secondary" className="text-[10px]">
            {t("badgeNew")}
          </Badge>
        )}
      </div>
      {expanded && (
        <>
          {(group.children ?? []).map((c, i) => (
            <GroupRow
              key={c.temp_id ?? `c${i}`}
              group={c}
              depth={depth + 1}
              selection={selection}
              stateMap={stateMap}
              onToggle={onToggle}
              lockedIds={lockedIds}
            />
          ))}
          {(group.competences ?? []).map((comp, i) => (
            <CompetenceRow
              key={comp.temp_id ?? `cmp${i}`}
              comp={comp}
              depth={depth + 1}
              selection={selection}
              stateMap={stateMap}
              onToggle={onToggle}
              lockedIds={lockedIds}
            />
          ))}
        </>
      )}
    </div>
  );
}

function CompetenceRow({
  comp,
  depth,
  selection,
  stateMap,
  onToggle,
  lockedIds,
}: {
  comp: GeneratedCompetence;
  depth: number;
  selection: Record<string, boolean>;
  stateMap: NodeStateMap;
  onToggle: (nodeId: string, selected: boolean) => void;
  lockedIds?: Set<string>;
}) {
  const t = useTranslations("competences");
  const [expanded, setExpanded] = useState(false);
  const tempId = comp.temp_id;
  const tri = tempId ? stateMap[tempId] : "unchecked";
  const isLocked =
    !!comp.snapshot_id || (lockedIds?.has(tempId ?? "") ?? false);
  const isNew = !comp.snapshot_id;
  const indicatorsTotal = comp.indicators?.length ?? 0;
  const indicatorsSelected =
    comp.indicators?.filter((i) => i.temp_id && selection[i.temp_id]).length ??
    0;

  return (
    <div data-testid={`compgen-tree-node-${tempId ?? ""}`}>
      <div
        className="flex items-center gap-2 rounded-md bg-muted/30 px-2 py-1 text-sm"
        style={{ paddingLeft: `${depth * 20 + 8}px` }}
      >
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex h-5 w-5 items-center justify-center text-muted-foreground"
          disabled={indicatorsTotal === 0}
        >
          {indicatorsTotal > 0 &&
            (expanded ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            ))}
        </button>
        <Checkbox
          data-testid={`compgen-tree-checkbox-${tempId ?? ""}`}
          checked={tri === "checked"}
          indeterminate={tri === "partial"}
          disabled={isLocked && tri === "checked"}
          onCheckedChange={(v) => {
            if (!tempId) return;
            onToggle(tempId, Boolean(v));
          }}
        />
        <Star className="h-3.5 w-3.5 text-muted-foreground" />
        <span
          className={`flex-1 ${isNew ? "text-foreground" : "text-muted-foreground"}`}
          title={comp.description ?? undefined}
        >
          {comp.title}
        </span>
        {indicatorsTotal > 0 && (
          <Badge
            data-testid={`compgen-tree-chip-indicators-${tempId ?? ""}`}
            variant="outline"
            className="text-[10px]"
          >
            {t("treeChipIndicators", {
              total: indicatorsTotal,
              selected: indicatorsSelected,
            })}
          </Badge>
        )}
        {isNew && <Sparkles className="h-3 w-3 text-primary" />}
      </div>
      {expanded && (
        <div className="space-y-0.5">
          {(comp.indicators ?? []).map((ind, i) => (
            <IndicatorRow
              key={ind.temp_id ?? `i${i}`}
              ind={ind}
              depth={depth + 1}
              selection={selection}
              onToggle={onToggle}
              lockedIds={lockedIds}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function countExistingItems(existingTree: ExistingTreeGroup[]): number {
  // HRP-114 re-spec: count groups + competences + indicators inside the
  // snapshot so the summary line ("X existing in this group") is meaningful
  // — anything the user could potentially see in the read-only block.
  let total = 0;
  const walk = (g: ExistingTreeGroup) => {
    total += 1;
    for (const c of g.competences ?? []) {
      total += 1;
      total += (c.indicators ?? []).length;
    }
    for (const child of g.descendants ?? g.children ?? []) walk(child);
  };
  existingTree.forEach(walk);
  return total;
}

function countNewSuggestions(payload: GeneratedTreePayload): number {
  let total = 0;
  const walk = (g: GeneratedGroup) => {
    if (!g.snapshot_id) total += 1;
    for (const c of g.competences ?? []) {
      if (!c.snapshot_id) total += 1;
      for (const ind of c.indicators ?? []) {
        if (!ind.snapshot_id) total += 1;
      }
    }
    for (const child of g.children ?? []) walk(child);
  };
  (payload.groups ?? []).forEach(walk);
  for (const ind of payload.indicators ?? []) {
    if (!ind.snapshot_id) total += 1;
  }
  return total;
}

function ExistingGroupRow({
  group,
  depth,
}: {
  group: ExistingTreeGroup;
  depth: number;
}) {
  const t = useTranslations("competences");
  const [expanded, setExpanded] = useState(true);
  const children = group.descendants ?? group.children ?? [];
  const competences = group.competences ?? [];
  const hasChildren = children.length > 0 || competences.length > 0;
  return (
    <div data-testid={`compgen-result-item-existing-group-${group.id}`}>
      <div
        className="flex items-center gap-2 rounded-md bg-slate-50 px-2 py-1 text-xs text-slate-500 dark:bg-slate-900/40 dark:text-slate-400"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {hasChildren && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-muted-foreground"
            aria-label={expanded ? t("collapse") : t("expand")}
          >
            {expanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
          </button>
        )}
        <Tooltip>
          <TooltipTrigger>
            <Checkbox
              data-testid={`compgen-result-item-existing-group-${group.id}-checkbox`}
              checked
              disabled
              className="cursor-not-allowed"
            />
          </TooltipTrigger>
          <TooltipContent side="right" className="max-w-xs text-xs">
            {t("resultExistingTooltip")}
          </TooltipContent>
        </Tooltip>
        <span className="flex-1 truncate" title={group.description ?? undefined}>
          {group.title}
        </span>
        <Badge
          data-testid={`compgen-result-item-existing-group-${group.id}-status-existing`}
          variant="outline"
          className="text-[10px] text-muted-foreground"
        >
          {t("badgeExisting")}
        </Badge>
      </div>
      {expanded && hasChildren && (
        <div className="space-y-0.5">
          {children.map((child) => (
            <ExistingGroupRow
              key={child.id}
              group={child}
              depth={depth + 1}
            />
          ))}
          {competences.map((comp) => (
            <ExistingCompetenceRow
              key={comp.id}
              comp={comp}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ExistingCompetenceRow({
  comp,
  depth,
}: {
  comp: NonNullable<ExistingTreeGroup["competences"]>[number];
  depth: number;
}) {
  const t = useTranslations("competences");
  const [expanded, setExpanded] = useState(false);
  const indicators = comp.indicators ?? [];
  return (
    <div data-testid={`compgen-result-item-existing-competence-${comp.id}`}>
      <div
        className="flex items-center gap-2 rounded-md bg-slate-50/70 px-2 py-1 text-[11px] text-slate-500 dark:bg-slate-900/30 dark:text-slate-400"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-muted-foreground"
          disabled={indicators.length === 0}
        >
          {indicators.length > 0 &&
            (expanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            ))}
        </button>
        <Tooltip>
          <TooltipTrigger>
            <Checkbox
              data-testid={`compgen-result-item-existing-competence-${comp.id}-checkbox`}
              checked
              disabled
              className="cursor-not-allowed"
            />
          </TooltipTrigger>
          <TooltipContent side="right" className="max-w-xs text-xs">
            {t("resultExistingTooltip")}
          </TooltipContent>
        </Tooltip>
        <Star className="h-3 w-3 text-muted-foreground" />
        <span className="flex-1 truncate" title={comp.description ?? undefined}>
          {comp.title}
        </span>
        <Badge
          data-testid={`compgen-result-item-existing-competence-${comp.id}-status-existing`}
          variant="outline"
          className="text-[10px] text-muted-foreground"
        >
          {t("badgeExisting")}
        </Badge>
      </div>
      {expanded && indicators.length > 0 && (
        <div className="space-y-0.5">
          {indicators.map((ind) => (
            <div
              key={ind.id}
              data-testid={`compgen-result-item-existing-indicator-${ind.id}`}
              className="flex items-center gap-2 px-2 py-0.5 text-[11px] text-muted-foreground"
              style={{ paddingLeft: `${(depth + 1) * 16 + 8}px` }}
            >
              <span className="w-3" />
              <Checkbox
                data-testid={`compgen-result-item-existing-indicator-${ind.id}-checkbox`}
                checked
                disabled
                className="cursor-not-allowed"
              />
              <span className="flex-1 truncate">{ind.title}</span>
              {ind.skill_level && (
                <Badge variant="outline" className="text-[10px]">
                  {ind.skill_level}
                </Badge>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function IndicatorRow({
  ind,
  depth,
  selection,
  onToggle,
  lockedIds,
}: {
  ind: GeneratedIndicator;
  depth: number;
  selection: Record<string, boolean>;
  onToggle: (nodeId: string, selected: boolean) => void;
  lockedIds?: Set<string>;
}) {
  const tempId = ind.temp_id;
  const checked = !!(tempId && selection[tempId]);
  const isLocked =
    !!ind.snapshot_id || (lockedIds?.has(tempId ?? "") ?? false);
  return (
    <div
      data-testid={`compgen-tree-node-${tempId ?? ""}`}
      className="flex items-center gap-2 px-2 py-0.5 text-xs text-muted-foreground"
      style={{ paddingLeft: `${depth * 20 + 8}px` }}
    >
      <span className="w-5" />
      <Checkbox
        data-testid={`compgen-tree-checkbox-${tempId ?? ""}`}
        checked={checked}
        disabled={isLocked && checked}
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
}
