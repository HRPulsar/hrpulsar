"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Link2, Plus, Search, X } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  competenceGenerationApi,
  type ContextOptions,
} from "@/lib/api/competence-generation";

/** HRP-159 REDO: search + filter only appear once the divisions list crosses
 * this length, matching the threshold used by the AI-generation context
 * picker for specializations/divisions (HRP-114) and the materials dialog
 * (HRP-51). Keep the three pickers in lockstep so the UX stays uniform. */
const DIVISIONS_FILTER_THRESHOLD = 15;

export interface MatrixContextPickerProps {
  /** Target specialization id — required to load context. */
  targetId?: string | null;
  /** Controlled set of context_excludes keys. */
  excludes: Set<string>;
  /** Called with the next set whenever the user toggles a chip. */
  onChange: (next: Set<string>) => void;
}

/**
 * HRP-159: preflight context picker for AI Generate matrix.
 *
 * Pulls `/competence-generation/context-options?scope=specialization_matrix
 * &target_id=<spec>` and renders four toggleable blocks:
 * - Specialization description
 * - Positions linked to the specialization
 * - Tenant divisions (pre-checked when linked through any position)
 * - Existing competences already in the matrix
 *
 * Excludes use the standard per-item / category key scheme:
 * - `position:<uuid>`, `division:<uuid>`, `competence:<uuid>`
 * - `positions`, `divisions`, `company`, `existing_competences`,
 *   `specialization_description`
 */
export function MatrixContextPicker({
  targetId,
  excludes,
  onChange,
}: MatrixContextPickerProps) {
  const [data, setData] = useState<ContextOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!targetId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    const run = async () => {
      try {
        const res = await competenceGenerationApi.contextOptions(
          "specialization_matrix",
          targetId,
        );
        if (!cancelled) setData(res);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Failed to load context",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [targetId]);

  function toggle(key: string) {
    const next = new Set(excludes);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    onChange(next);
  }

  function setBulk(keys: string[], include: boolean) {
    const next = new Set(excludes);
    for (const k of keys) {
      if (include) {
        next.delete(k);
      } else {
        next.add(k);
      }
    }
    onChange(next);
  }

  if (!targetId) {
    return null;
  }
  if (loading) {
    return (
      <div
        data-testid="matrix-context-loading"
        className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground"
      >
        Loading available context…
      </div>
    );
  }
  if (error || !data) {
    return (
      <div
        data-testid="matrix-context-error"
        className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive"
      >
        {error || "No context available."}
      </div>
    );
  }

  const positions = data.positions ?? [];
  const matrixDivisions = data.matrix_divisions ?? [];
  const existingCompetences = data.existing_competences ?? [];

  const positionKeys = positions.map((p) => `position:${p.id}`);
  const competenceKeys = existingCompetences.map((c) => `competence:${c.id}`);

  return (
    <div
      data-testid="matrix-context-controls"
      className="space-y-3 rounded-md border bg-muted/30 p-3"
    >
      <div className="flex items-center justify-between">
        <Label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Context sent to the model
        </Label>
      </div>

      <SpecializationDescriptionSection
        description={data.specialization_description ?? null}
        excluded={excludes.has("specialization_description")}
        onToggle={() => toggle("specialization_description")}
      />

      <ChipSection
        title="Positions"
        subtitle="Job positions linked to this specialization."
        items={positions.map((p) => ({
          key: `position:${p.id}`,
          label: p.title,
        }))}
        categoryKey="positions"
        excludes={excludes}
        onToggle={toggle}
        onBulk={(include) => setBulk([...positionKeys, "positions"], include)}
        emptyHint="No positions linked to this specialization."
        testIdSuffix="positions"
      />

      <DivisionsLinkedAwareSection
        divisions={matrixDivisions}
        excludes={excludes}
        onChange={onChange}
      />

      <CompanyDescriptionSection
        description={data.company_description}
        excluded={excludes.has("company")}
        onToggle={() => toggle("company")}
      />

      <ChipSection
        title="Existing competences"
        subtitle="Competences already present in this matrix. Useful as context for the model — toggle off any you want excluded."
        items={existingCompetences.map((c) => ({
          key: `competence:${c.id}`,
          label: c.title,
        }))}
        categoryKey="existing_competences"
        excludes={excludes}
        onToggle={toggle}
        onBulk={(include) =>
          setBulk([...competenceKeys, "existing_competences"], include)
        }
        emptyHint="Matrix is empty — no competences yet."
        testIdSuffix="existing_competences"
      />
    </div>
  );
}

interface ChipItem {
  key: string;
  label: string;
}

interface ChipSectionProps {
  title: string;
  subtitle?: string;
  items: ChipItem[];
  categoryKey: string;
  excludes: Set<string>;
  onToggle: (key: string) => void;
  onBulk: (include: boolean) => void;
  emptyHint: string;
  testIdSuffix: string;
}

function ChipSection({
  title,
  subtitle,
  items,
  categoryKey,
  excludes,
  onToggle,
  onBulk,
  emptyHint,
  testIdSuffix,
}: ChipSectionProps) {
  const categoryDropped = excludes.has(categoryKey);
  const active = items.filter((i) => !categoryDropped && !excludes.has(i.key));
  const removed = items.filter(
    (i) => !categoryDropped && excludes.has(i.key),
  );

  return (
    <div
      data-testid={`matrix-context-section-${testIdSuffix}`}
      className="space-y-1.5"
    >
      <div className="flex items-center justify-between">
        <div className="flex flex-col">
          <Label className="text-xs font-medium text-foreground">{title}</Label>
          {subtitle && (
            <span className="text-[11px] text-muted-foreground">{subtitle}</span>
          )}
        </div>
        {items.length > 0 && (
          <Button
            data-testid={`matrix-context-bulk-${testIdSuffix}`}
            type="button"
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-xs"
            onClick={() => onBulk(categoryDropped || active.length === 0)}
          >
            {categoryDropped || active.length === 0 ? "Add all back" : "Remove all"}
          </Button>
        )}
      </div>
      {items.length === 0 ? (
        <span className="text-xs text-muted-foreground">{emptyHint}</span>
      ) : categoryDropped ? (
        <span className="text-xs text-muted-foreground">
          Category dropped. Use “Add all back” to include items again.
        </span>
      ) : (
        <>
          <div className="flex flex-wrap gap-1.5">
            {active.length === 0 && (
              <span
                data-testid={`matrix-context-empty-${testIdSuffix}`}
                className="text-xs text-muted-foreground"
              >
                All items removed.
              </span>
            )}
            {active.map((item) => (
              <button
                key={item.key}
                type="button"
                data-testid={`matrix-context-chip-${item.key}`}
                onClick={() => onToggle(item.key)}
                className="inline-flex items-center gap-1 rounded-md border bg-background px-2 py-1 text-xs text-foreground hover:bg-destructive/10 hover:border-destructive/40"
                title="Remove from context"
              >
                {item.label}
                <X className="h-3 w-3" />
              </button>
            ))}
          </div>
          {removed.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 pt-1">
              <span className="text-xs text-muted-foreground">Add back:</span>
              {removed.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  data-testid={`matrix-context-add-${item.key}`}
                  onClick={() => onToggle(item.key)}
                  className="inline-flex items-center gap-1 rounded-md border border-dashed bg-background px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  <Plus className="h-3 w-3" />
                  {item.label}
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function SpecializationDescriptionSection({
  description,
  excluded,
  onToggle,
}: {
  description: string | null;
  excluded: boolean;
  onToggle: () => void;
}) {
  if (!description) {
    return (
      <div className="space-y-1.5">
        <Label className="text-xs font-medium text-foreground">
          Specialization description
        </Label>
        <span className="text-xs text-muted-foreground">
          No description set on this specialization.
        </span>
      </div>
    );
  }
  return (
    <div
      data-testid="matrix-context-section-specialization_description"
      className="space-y-1.5"
    >
      <Label className="text-xs font-medium text-foreground">
        Specialization description
      </Label>
      {excluded ? (
        <button
          type="button"
          data-testid="matrix-context-add-specialization_description"
          onClick={onToggle}
          className="inline-flex items-center gap-1 rounded-md border border-dashed bg-background px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <Plus className="h-3 w-3" />
          Add specialization description
        </button>
      ) : (
        <button
          type="button"
          data-testid="matrix-context-chip-specialization_description"
          onClick={onToggle}
          className="group flex w-full items-start gap-2 rounded-md border bg-background px-2 py-1.5 text-left text-xs text-foreground hover:bg-destructive/10 hover:border-destructive/40"
          title="Remove from context"
        >
          <span className="flex-1 leading-snug">{description}</span>
          <X className="mt-0.5 h-3 w-3 shrink-0" />
        </button>
      )}
    </div>
  );
}

function CompanyDescriptionSection({
  description,
  excluded,
  onToggle,
}: {
  description: string | null;
  excluded: boolean;
  onToggle: () => void;
}) {
  if (!description) {
    return (
      <div className="space-y-1.5">
        <Label className="text-xs font-medium text-foreground">
          Company description
        </Label>
        <span className="text-xs text-muted-foreground">
          No description set on the tenant profile.
        </span>
      </div>
    );
  }
  return (
    <div
      data-testid="matrix-context-section-company"
      className="space-y-1.5"
    >
      <Label className="text-xs font-medium text-foreground">
        Company description
      </Label>
      {excluded ? (
        <button
          type="button"
          data-testid="matrix-context-add-company"
          onClick={onToggle}
          className="inline-flex items-center gap-1 rounded-md border border-dashed bg-background px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <Plus className="h-3 w-3" />
          Add company description
        </button>
      ) : (
        <button
          type="button"
          data-testid="matrix-context-chip-company"
          onClick={onToggle}
          className="group flex w-full items-start gap-2 rounded-md border bg-background px-2 py-1.5 text-left text-xs text-foreground hover:bg-destructive/10 hover:border-destructive/40"
          title="Remove from context"
        >
          <span className="flex-1 leading-snug">{description}</span>
          <X className="mt-0.5 h-3 w-3 shrink-0" />
        </button>
      )}
    </div>
  );
}

/**
 * HRP-159 REDO: pure helper that returns the initial `context_excludes`
 * additions needed so only the linked (`related: true`) divisions are
 * pre-checked when the modal opens. Exposed for unit testing — the
 * component below applies it via `useEffect` on first load.
 */
export function seedDivisionExcludesForLinkedOnly(
  divisions: Array<{ id: string; related: boolean }>,
): string[] {
  return divisions
    .filter((d) => !d.related)
    .map((d) => `division:${d.id}`);
}

interface DivisionsLinkedAwareSectionProps {
  divisions: Array<{ id: string; name: string; related: boolean }>;
  excludes: Set<string>;
  onChange: (next: Set<string>) => void;
}

/**
 * HRP-159 REDO: the Divisions block surfaces every tenant division (not
 * only the ones reachable through the specialization's positions). Linked
 * divisions are pre-checked, unlinked ones present but off; once the list
 * grows beyond 15 rows a search input and a "Show linked only" filter
 * appear. The filter is purely cosmetic — it never toggles excludes.
 */
function DivisionsLinkedAwareSection({
  divisions,
  excludes,
  onChange,
}: DivisionsLinkedAwareSectionProps) {
  const [search, setSearch] = useState("");
  const [linkedOnly, setLinkedOnly] = useState(false);
  // Seed `excludes` on first render so unlinked divisions stay unchecked
  // by default. Subsequent renders honour the user's edits — we only seed
  // once per divisions-array identity, set by the parent on each
  // context-options resolve.
  const seedRef = useRef(false);
  useEffect(() => {
    if (seedRef.current) return;
    if (divisions.length === 0) return;
    seedRef.current = true;
    const seed = seedDivisionExcludesForLinkedOnly(divisions);
    if (seed.length === 0) return;
    const next = new Set(excludes);
    let dirty = false;
    for (const key of seed) {
      if (!next.has(key)) {
        next.add(key);
        dirty = true;
      }
    }
    if (dirty) onChange(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [divisions]);

  const categoryDropped = excludes.has("divisions");
  const selectedCount = useMemo(
    () =>
      categoryDropped
        ? 0
        : divisions.filter((d) => !excludes.has(`division:${d.id}`)).length,
    [categoryDropped, divisions, excludes],
  );
  const linkedTotal = divisions.filter((d) => d.related).length;
  const showControls = divisions.length > DIVISIONS_FILTER_THRESHOLD;

  const visible = useMemo(() => {
    let list = divisions;
    if (linkedOnly) list = list.filter((d) => d.related);
    const term = search.trim().toLowerCase();
    if (term) list = list.filter((d) => d.name.toLowerCase().includes(term));
    return list;
  }, [divisions, linkedOnly, search]);

  function toggleOne(id: string) {
    const key = `division:${id}`;
    const next = new Set(excludes);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(next);
  }

  function toggleCategory(include: boolean) {
    const next = new Set(excludes);
    if (include) {
      next.delete("divisions");
      for (const d of divisions) {
        next.delete(`division:${d.id}`);
      }
    } else {
      next.add("divisions");
    }
    onChange(next);
  }

  return (
    <div
      data-testid="ai-generate-matrix-divisions-section"
      className="space-y-1.5"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex flex-col">
          <Label className="text-xs font-medium text-foreground">
            Divisions ({selectedCount} of {divisions.length} selected
            {linkedTotal > 0 ? `, ${linkedTotal} linked` : ""})
          </Label>
          <span className="text-[11px] text-muted-foreground">
            Every tenant division is listed. Linked entries (through this
            specialization&apos;s positions) are pre-checked.
          </span>
        </div>
        {showControls ? (
          <div className="flex items-center gap-2">
            <label
              className="flex items-center gap-1 text-[11px] text-muted-foreground"
              data-testid="ai-generate-matrix-divisions-filter-linked-only"
            >
              <Checkbox
                checked={linkedOnly}
                onCheckedChange={(v) => setLinkedOnly(Boolean(v))}
              />
              <span>Show linked only</span>
            </label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search…"
                className="h-7 w-44 pl-7 text-xs"
                data-testid="ai-generate-matrix-divisions-search"
              />
            </div>
          </div>
        ) : null}
        {divisions.length > 0 ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-xs"
            onClick={() => toggleCategory(categoryDropped || selectedCount === 0)}
          >
            {categoryDropped || selectedCount === 0 ? "Add all back" : "Remove all"}
          </Button>
        ) : null}
      </div>
      <div
        data-testid="ai-generate-matrix-divisions-counter"
        className="sr-only"
        aria-live="polite"
      >
        {selectedCount}/{divisions.length}
      </div>
      {divisions.length === 0 ? (
        <span className="text-xs text-muted-foreground">
          No divisions configured for this tenant.
        </span>
      ) : categoryDropped ? (
        <span className="text-xs text-muted-foreground">
          Category dropped. Use “Add all back” to include items again.
        </span>
      ) : visible.length === 0 ? (
        <span className="text-xs text-muted-foreground">
          Nothing matches the current filter.
        </span>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {visible.map((d) => {
            const key = `division:${d.id}`;
            const checked = !excludes.has(key);
            return (
              <label
                key={d.id}
                data-testid={`ai-generate-matrix-divisions-item-${d.id}`}
                className={
                  "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs " +
                  (checked
                    ? "border-primary bg-primary/10 text-foreground"
                    : "border-input bg-background text-muted-foreground hover:text-foreground")
                }
              >
                <Checkbox
                  checked={checked}
                  onCheckedChange={() => toggleOne(d.id)}
                  data-testid={`ai-generate-matrix-divisions-item-${d.id}-toggle`}
                />
                <span>{d.name}</span>
                {d.related ? (
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <span
                          data-testid={`ai-generate-matrix-divisions-item-${d.id}-linked-marker`}
                          aria-label="Linked via positions"
                          className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-primary/15 text-primary"
                        >
                          <Link2 className="h-3 w-3" />
                        </span>
                      }
                    />
                    <TooltipContent side="top" className="text-xs">
                      Linked through this specialization&apos;s positions
                    </TooltipContent>
                  </Tooltip>
                ) : null}
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}
