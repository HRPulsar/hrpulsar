"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Link2, Plus, X } from "lucide-react";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  competenceGenerationApi,
  type ContextOptions,
  type ContextSourceTreeNode,
  type SessionScope,
} from "@/lib/api/competence-generation";

/** HRP-114 re-spec: keep the modal compact when the tenant has many specs
 * or divisions — show search + linked-only filter only once the list gets
 * long enough to be hard to scan. */
const LINKED_LIST_FILTER_THRESHOLD = 15;

export interface ContextPickerProps {
  /** Scope of the upcoming generation — drives which sections are shown. */
  scope: SessionScope;
  /** ID of the target group / competence for the scope, if any. */
  targetId?: string | null;
  /** Controlled set of context_excludes keys. */
  excludes: Set<string>;
  /** Called with the next set whenever the user toggles a chip. */
  onChange: (next: Set<string>) => void;
  /**
   * HRP-155: hide the existing-subtree sections (source_tree for whole_base,
   * descendants for group) when the parent dialog has the augment toggle
   * off — the chips would be misleading because the payload already
   * force-excludes those categories. The parent still owns the actual
   * exclude keys; this prop only affects what is rendered.
   */
  hideExistingSubtree?: boolean;
}

/**
 * HRP-143 / HRP-114: granular context picker for AI generation.
 *
 * Pulls the available context from
 * `/competence-generation/context-options?scope=...&target_id=...` and
 * renders each category as a list of chips with × controls. Each toggle
 * emits a key into the parent's `excludes` set; the worker applies it
 * server-side.
 *
 * Per-scope sections:
 * - `whole_base` — Specializations, Divisions, Company description, Source tree.
 * - `group` — Specializations, Related specializations, Divisions, Company
 *   description, Ancestor groups, Descendant groups (with competences).
 * - `competence_indicators` — Specializations, Related specializations,
 *   Divisions, Company description, Sibling competences.
 *
 * Keys flow:
 * - Per-item: `specialization:<uuid>`, `related_specialization:<uuid>`,
 *   `division:<uuid>`, `group:<uuid>`, `competence:<uuid>`,
 *   `ancestor:<uuid>`, `descendant:<uuid>`.
 * - Category: `specializations`, `related_specializations`, `divisions`,
 *   `company`, `source_tree`, `ancestors`, `descendants`,
 *   `sibling_competences`, `existing_indicators`.
 */
export function WholeBaseContextPicker({
  scope,
  targetId,
  excludes,
  onChange,
  hideExistingSubtree = false,
}: ContextPickerProps) {
  const [data, setData] = useState<ContextOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // HRP-114 re-spec: group/indicators scope auto-excludes every unlinked
  // spec + division on first data load so the default checked set is the
  // linked subset. The flag pins the seed to a single load per mount so
  // re-renders don't keep re-stamping excludes after the user manually
  // un-checks a linked item.
  const [autoSeeded, setAutoSeeded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        const res = await competenceGenerationApi.contextOptions(
          scope,
          targetId ?? null,
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
  }, [scope, targetId]);

  useEffect(() => {
    // HRP-114 re-spec: seed `excludes` with the unlinked items once the
    // fetched payload tells us which items are linked. Only runs for the
    // two scopes that surface `is_linked`; other scopes keep their legacy
    // "everything in unless explicitly removed" behaviour.
    if (autoSeeded || !data) return;
    if (scope !== "group" && scope !== "competence_indicators") {
      setAutoSeeded(true);
      return;
    }
    const next = new Set(excludes);
    let changed = false;
    for (const s of data.specializations) {
      if (s.is_linked === false) {
        const key = `specialization:${s.id}`;
        if (!next.has(key)) {
          next.add(key);
          changed = true;
        }
      }
    }
    for (const d of data.divisions) {
      if (d.is_linked === false) {
        const key = `division:${d.id}`;
        if (!next.has(key)) {
          next.add(key);
          changed = true;
        }
      }
    }
    if (changed) onChange(next);
    setAutoSeeded(true);
  }, [data, scope, autoSeeded, excludes, onChange]);

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

  if (loading) {
    return (
      <div
        data-testid="compgen-confirm-context-loading"
        className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground"
      >
        Loading available context…
      </div>
    );
  }
  if (error || !data) {
    return (
      <div
        data-testid="compgen-confirm-context-error"
        className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive"
      >
        {error || "No context available."}
      </div>
    );
  }

  const relatedSpecs = data.related_specializations ?? [];
  const ancestors = data.ancestors ?? [];
  const descendants = data.descendants ?? [];
  const siblings = data.sibling_competences ?? [];
  // HRP-114 re-spec: group/indicators surface the full spec + division list
  // with `is_linked` so the modal can pre-check linked ones and dim the rest.
  // whole_base / matrix keep the legacy "remove unwanted chips" UI.
  const scopeHasLinkage =
    scope === "group" || scope === "competence_indicators";

  const allSpecKeys = data.specializations.map((s) => `specialization:${s.id}`);
  const allRelatedKeys = relatedSpecs.map((s) => `related_specialization:${s.id}`);
  const allDivisionKeys = data.divisions.map((d) => `division:${d.id}`);
  const treeGroupKeys = flattenTreeGroupIds(data.source_tree).map(
    (id) => `group:${id}`,
  );
  const ancestorKeys = ancestors.map((a) => `ancestor:${a.id}`);
  const descendantKeys = flattenTreeGroupIds(descendants).map(
    (id) => `descendant:${id}`,
  );
  const siblingKeys = siblings.map((s) => `competence:${s.id}`);

  return (
    <div
      data-testid="compgen-confirm-context-controls"
      className="space-y-3 rounded-md border bg-muted/30 p-3"
    >
      <div className="flex items-center justify-between">
        <Label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Context sent to the model
        </Label>
      </div>

      {!scopeHasLinkage && relatedSpecs.length > 0 && (
        <ContextSection
          title="Related specializations"
          subtitle="Specializations whose matrix already references competences in this scope."
          items={relatedSpecs.map((s) => ({
            key: `related_specialization:${s.id}`,
            label: s.title,
          }))}
          categoryKey="related_specializations"
          excludes={excludes}
          onToggle={toggle}
          onBulk={(include) =>
            setBulk([...allRelatedKeys, "related_specializations"], include)
          }
          emptyHint="No matrix links found."
        />
      )}

      {scopeHasLinkage ? (
        <LinkedAwareSection
          title="Specializations"
          subtitle="Linked specs are pre-checked. Add others manually to broaden the context."
          categoryKey="specializations"
          items={data.specializations.map((s) => ({
            key: `specialization:${s.id}`,
            id: s.id,
            label: s.title,
            isLinked: s.is_linked === true,
            kind: "specialization",
            linkedTooltip:
              scope === "group"
                ? "Linked via competence(s) in this group"
                : "Linked to this competence",
          }))}
          excludes={excludes}
          onToggle={toggle}
          onBulkSetSelection={(keys, include) =>
            setBulk([...keys, "specializations"], include)
          }
          emptyHint="No specializations in the dictionary yet."
        />
      ) : (
        <ContextSection
          title="Specializations"
          items={data.specializations.map((s) => ({
            key: `specialization:${s.id}`,
            label: s.title,
          }))}
          categoryKey="specializations"
          excludes={excludes}
          onToggle={toggle}
          onBulk={(include) =>
            setBulk([...allSpecKeys, "specializations"], include)
          }
          emptyHint="No specializations in the dictionary yet."
        />
      )}

      {scopeHasLinkage ? (
        <LinkedAwareSection
          title="Divisions"
          subtitle="Divisions reachable via the linked specs' positions. Tick others to add."
          categoryKey="divisions"
          items={data.divisions.map((d) => ({
            key: `division:${d.id}`,
            id: d.id,
            label: d.name,
            isLinked: d.is_linked === true,
            kind: "division",
            linkedTooltip: "Linked via competences and positions",
          }))}
          excludes={excludes}
          onToggle={toggle}
          onBulkSetSelection={(keys, include) =>
            setBulk([...keys, "divisions"], include)
          }
          emptyHint="No divisions configured for this tenant."
        />
      ) : (
        <ContextSection
          title="Divisions"
          items={data.divisions.map((d) => ({
            key: `division:${d.id}`,
            label: d.name,
          }))}
          categoryKey="divisions"
          excludes={excludes}
          onToggle={toggle}
          onBulk={(include) =>
            setBulk([...allDivisionKeys, "divisions"], include)
          }
          emptyHint="No divisions configured for this tenant."
        />
      )}

      <CompanyDescriptionSection
        description={data.company_description}
        excluded={excludes.has("company")}
        onToggle={() => toggle("company")}
      />

      {scope === "whole_base" && !hideExistingSubtree && (
        <SourceTreeSection
          title="Existing library tree"
          tree={data.source_tree}
          categoryKey="source_tree"
          excludes={excludes}
          onToggle={toggle}
          onBulkGroups={(include) =>
            setBulk([...treeGroupKeys, "source_tree"], include)
          }
          emptyHint="Library is empty — no existing groups or competences to share."
          droppedHint={(count) =>
            `Tree dropped — model starts from scratch (${count} groups hidden).`
          }
        />
      )}

      {scope === "group" && ancestors.length > 0 && (
        <ContextSection
          title="Ancestor groups"
          subtitle="Parent groups above the target group (root → leaf)."
          items={ancestors.map((a) => ({
            key: `ancestor:${a.id}`,
            label: a.title,
          }))}
          categoryKey="ancestors"
          excludes={excludes}
          onToggle={toggle}
          onBulk={(include) =>
            setBulk([...ancestorKeys, "ancestors"], include)
          }
          emptyHint="Target is at the root."
        />
      )}

      {scope === "group" && descendants.length > 0 && !hideExistingSubtree && (
        <SourceTreeSection
          title="Descendant subgroups"
          tree={descendants}
          categoryKey="descendants"
          excludes={excludes}
          onToggle={toggle}
          onBulkGroups={(include) =>
            setBulk([...descendantKeys, "descendants"], include)
          }
          emptyHint="No subgroups below the target."
          droppedHint={(count) =>
            `Subtree dropped (${count} groups hidden).`
          }
        />
      )}

      {scope === "competence_indicators" && siblings.length > 0 && (
        <ContextSection
          title="Sibling competences"
          subtitle="Other competences in the same group as the target."
          items={siblings.map((s) => ({
            key: `competence:${s.id}`,
            label: s.title,
          }))}
          categoryKey="sibling_competences"
          excludes={excludes}
          onToggle={toggle}
          onBulk={(include) =>
            setBulk([...siblingKeys, "sibling_competences"], include)
          }
          emptyHint="No siblings — competence stands alone in its group."
        />
      )}

      {scope === "competence_indicators" && (
        <ExistingIndicatorsToggle
          excluded={excludes.has("existing_indicators")}
          onToggle={() => toggle("existing_indicators")}
        />
      )}
    </div>
  );
}

interface ChipItem {
  key: string;
  label: string;
}

interface ContextSectionProps {
  title: string;
  subtitle?: string;
  items: ChipItem[];
  categoryKey: string;
  excludes: Set<string>;
  onToggle: (key: string) => void;
  onBulk: (include: boolean) => void;
  emptyHint: string;
}

function ContextSection({
  title,
  subtitle,
  items,
  categoryKey,
  excludes,
  onToggle,
  onBulk,
  emptyHint,
}: ContextSectionProps) {
  const categoryDropped = excludes.has(categoryKey);
  const active = items.filter((i) => !categoryDropped && !excludes.has(i.key));
  const removed = items.filter(
    (i) => !categoryDropped && excludes.has(i.key),
  );

  return (
    <div
      data-testid={`compgen-context-section-${categoryKey}`}
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
            data-testid={`compgen-context-bulk-${categoryKey}`}
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
                data-testid={`compgen-context-empty-${categoryKey}`}
                className="text-xs text-muted-foreground"
              >
                All items removed.
              </span>
            )}
            {active.map((item) => (
              <button
                key={item.key}
                type="button"
                data-testid={`compgen-context-chip-${item.key}`}
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
                  data-testid={`compgen-context-add-${item.key}`}
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
      data-testid="compgen-context-section-company"
      className="space-y-1.5"
    >
      <Label className="text-xs font-medium text-foreground">
        Company description
      </Label>
      {excluded ? (
        <button
          type="button"
          data-testid="compgen-context-add-company"
          onClick={onToggle}
          className="inline-flex items-center gap-1 rounded-md border border-dashed bg-background px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <Plus className="h-3 w-3" />
          Add company description
        </button>
      ) : (
        <button
          type="button"
          data-testid="compgen-context-chip-company"
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

interface SourceTreeSectionProps {
  title: string;
  tree: ContextSourceTreeNode[];
  categoryKey: string;
  excludes: Set<string>;
  onToggle: (key: string) => void;
  onBulkGroups: (include: boolean) => void;
  emptyHint: string;
  droppedHint: (count: number) => string;
}

function SourceTreeSection({
  title,
  tree,
  categoryKey,
  excludes,
  onToggle,
  onBulkGroups,
  emptyHint,
  droppedHint,
}: SourceTreeSectionProps) {
  const treeDropped = excludes.has(categoryKey);
  const totalNodes = useMemo(() => flattenTreeGroupIds(tree).length, [tree]);
  // HRP-114: descendants/ancestors trees use different key prefixes; the
  // existing source_tree uses `group:`. Pick based on the categoryKey so
  // the per-node chips emit the right key into context_excludes.
  const nodeKeyPrefix = categoryKey === "descendants" ? "descendant" : "group";

  return (
    <div
      data-testid={`compgen-context-section-${categoryKey}`}
      className="space-y-1.5"
    >
      <div className="flex items-center justify-between">
        <Label className="text-xs font-medium text-foreground">{title}</Label>
        {tree.length > 0 && (
          <Button
            data-testid={`compgen-context-bulk-${categoryKey}`}
            type="button"
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-xs"
            onClick={() => onBulkGroups(treeDropped)}
          >
            {treeDropped ? "Add all back" : "Remove all"}
          </Button>
        )}
      </div>
      {tree.length === 0 ? (
        <span className="text-xs text-muted-foreground">{emptyHint}</span>
      ) : treeDropped ? (
        <span className="text-xs text-muted-foreground">
          {droppedHint(totalNodes)}
        </span>
      ) : (
        <ul className="space-y-1">
          {tree.map((g) => (
            <TreeNode
              key={g.id}
              node={g}
              depth={0}
              excludes={excludes}
              onToggle={onToggle}
              groupPrefix={nodeKeyPrefix}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function TreeNode({
  node,
  depth,
  excludes,
  onToggle,
  groupPrefix,
}: {
  node: ContextSourceTreeNode;
  depth: number;
  excludes: Set<string>;
  onToggle: (key: string) => void;
  groupPrefix: string;
}) {
  const [expanded, setExpanded] = useState(depth === 0);
  const groupKey = `${groupPrefix}:${node.id}`;
  const dropped = excludes.has(groupKey);
  const hasChildren = (node.children?.length ?? 0) > 0;
  const competences = node.competences ?? [];

  return (
    <li
      data-testid={`compgen-context-tree-node-${node.id}`}
      style={{ marginLeft: depth * 12 }}
    >
      <div className="flex items-center gap-1">
        {(hasChildren || competences.length > 0) && (
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground"
            onClick={() => setExpanded((v) => !v)}
            aria-label={expanded ? "Collapse" : "Expand"}
          >
            {expanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
          </button>
        )}
        {dropped ? (
          <button
            type="button"
            data-testid={`compgen-context-add-${groupKey}`}
            onClick={() => onToggle(groupKey)}
            className="inline-flex items-center gap-1 rounded-md border border-dashed bg-background px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <Plus className="h-3 w-3" />
            {node.title}
          </button>
        ) : (
          <button
            type="button"
            data-testid={`compgen-context-chip-${groupKey}`}
            onClick={() => onToggle(groupKey)}
            className="inline-flex items-center gap-1 rounded-md border bg-background px-1.5 py-0.5 text-xs text-foreground hover:bg-destructive/10 hover:border-destructive/40"
            title="Remove group from context"
          >
            {node.title}
            <X className="h-3 w-3" />
          </button>
        )}
      </div>
      {expanded && !dropped && (
        <>
          {competences.length > 0 && (
            <ul className="mt-1 space-y-0.5" style={{ marginLeft: 14 }}>
              {competences.map((c) => {
                const ckey = `competence:${c.id}`;
                const cDropped = excludes.has(ckey);
                return (
                  <li key={c.id}>
                    {cDropped ? (
                      <button
                        type="button"
                        data-testid={`compgen-context-add-${ckey}`}
                        onClick={() => onToggle(ckey)}
                        className="inline-flex items-center gap-1 rounded-md border border-dashed bg-background px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
                      >
                        <Plus className="h-3 w-3" />
                        {c.title}
                      </button>
                    ) : (
                      <button
                        type="button"
                        data-testid={`compgen-context-chip-${ckey}`}
                        onClick={() => onToggle(ckey)}
                        className="inline-flex items-center gap-1 rounded-md border bg-background px-1.5 py-0.5 text-[11px] text-foreground hover:bg-destructive/10 hover:border-destructive/40"
                      >
                        {c.title}
                        <X className="h-3 w-3" />
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {hasChildren && (
            <ul className="mt-1 space-y-1">
              {(node.children ?? []).map((child) => (
                <TreeNode
                  key={child.id}
                  node={child}
                  depth={depth + 1}
                  excludes={excludes}
                  onToggle={onToggle}
                  groupPrefix={groupPrefix}
                />
              ))}
            </ul>
          )}
        </>
      )}
    </li>
  );
}

function ExistingIndicatorsToggle({
  excluded,
  onToggle,
}: {
  excluded: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      data-testid="compgen-context-section-existing_indicators"
      className="space-y-1.5"
    >
      <Label className="text-xs font-medium text-foreground">
        Existing indicators of this competence
      </Label>
      {excluded ? (
        <button
          type="button"
          data-testid="compgen-context-add-existing_indicators"
          onClick={onToggle}
          className="inline-flex items-center gap-1 rounded-md border border-dashed bg-background px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <Plus className="h-3 w-3" />
          Include existing indicators
        </button>
      ) : (
        <button
          type="button"
          data-testid="compgen-context-chip-existing_indicators"
          onClick={onToggle}
          className="inline-flex items-center gap-1 rounded-md border bg-background px-2 py-1 text-xs text-foreground hover:bg-destructive/10 hover:border-destructive/40"
          title="Remove existing indicators from context"
        >
          Included — generation avoids duplicates
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}

interface LinkedAwareItem {
  /** `specialization:<uuid>` or `division:<uuid>` — the key written into the
   * shared `excludes` set when the user un-ticks the row. */
  key: string;
  /** Bare uuid, useful for per-item testids. */
  id: string;
  label: string;
  isLinked: boolean;
  kind: "specialization" | "division";
  /** Sentence used inside the tooltip on the linked marker. */
  linkedTooltip: string;
}

interface LinkedAwareSectionProps {
  title: string;
  subtitle: string;
  categoryKey: "specializations" | "divisions";
  items: LinkedAwareItem[];
  excludes: Set<string>;
  onToggle: (key: string) => void;
  /** Bulk toggle helper that also clears the category-level kill switch
   * when the user re-includes anything. */
  onBulkSetSelection: (perItemKeys: string[], include: boolean) => void;
  emptyHint: string;
}

function LinkedAwareSection({
  title,
  subtitle,
  categoryKey,
  items,
  excludes,
  onToggle,
  onBulkSetSelection,
  emptyHint,
}: LinkedAwareSectionProps) {
  const [search, setSearch] = useState("");
  const [showLinkedOnly, setShowLinkedOnly] = useState(false);

  const categoryDropped = excludes.has(categoryKey);
  const selectedCount = items.filter((i) => !excludes.has(i.key)).length;
  const linkedCount = items.filter((i) => i.isLinked).length;

  const showFilterControls = items.length > LINKED_LIST_FILTER_THRESHOLD;
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items.filter((item) => {
      if (showLinkedOnly && !item.isLinked) return false;
      if (q && !item.label.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [items, search, showLinkedOnly]);

  const allKeys = items.map((i) => i.key);

  return (
    <div
      data-testid={`compgen-context-section-${categoryKey}`}
      className="space-y-1.5"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-col">
          <Label className="text-xs font-medium text-foreground">
            {title}{" "}
            <span
              data-testid={`compgen-context-${categoryKey}-counter`}
              className="font-normal text-muted-foreground"
            >
              ({selectedCount} of {items.length} selected
              {linkedCount > 0 ? `, ${linkedCount} linked` : ""})
            </span>
          </Label>
          <span className="text-[11px] text-muted-foreground">{subtitle}</span>
        </div>
        {items.length > 0 && (
          <Button
            data-testid={`compgen-context-bulk-${categoryKey}-all`}
            type="button"
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-xs"
            onClick={() =>
              onBulkSetSelection(allKeys, categoryDropped || selectedCount < items.length)
            }
          >
            {selectedCount === items.length && !categoryDropped
              ? "Clear all"
              : "Select all"}
          </Button>
        )}
      </div>
      {items.length === 0 ? (
        <span className="text-xs text-muted-foreground">{emptyHint}</span>
      ) : (
        <>
          {showFilterControls && (
            <div className="flex flex-wrap items-center gap-2">
              <Input
                data-testid={`compgen-context-${categoryKey}-search`}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={`Search ${title.toLowerCase()}…`}
                className="h-7 flex-1 text-xs"
              />
              <label className="flex items-center gap-1 text-[11px] text-muted-foreground">
                <Checkbox
                  data-testid={`compgen-context-${categoryKey}-filter-linked-only`}
                  checked={showLinkedOnly}
                  onCheckedChange={(v) => setShowLinkedOnly(Boolean(v))}
                  className="h-3.5 w-3.5"
                />
                Show linked only
              </label>
            </div>
          )}
          <div className="flex flex-wrap gap-1.5">
            {filtered.length === 0 && (
              <span className="text-xs text-muted-foreground">
                No items match the current filter.
              </span>
            )}
            <TooltipProvider>
              {filtered.map((item) => {
                const selected = !excludes.has(item.key) && !categoryDropped;
                return (
                  <label
                    key={item.key}
                    data-testid={`compgen-context-chip-${item.key}`}
                    data-linked={item.isLinked || undefined}
                    data-selected={selected || undefined}
                    className={`inline-flex cursor-pointer items-center gap-1.5 rounded-md border bg-background px-2 py-1 text-xs ${
                      selected
                        ? "border-primary/40 text-foreground"
                        : "border-dashed text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    <Checkbox
                      data-testid={`compgen-context-chip-${item.key}-checkbox`}
                      checked={selected}
                      onCheckedChange={() => onToggle(item.key)}
                      className="h-3.5 w-3.5"
                    />
                    <span>{item.label}</span>
                    {item.isLinked && (
                      <Tooltip>
                        <TooltipTrigger>
                          <span
                            data-testid={`compgen-context-chip-${item.key}-linked-marker`}
                            className="inline-flex items-center text-primary"
                          >
                            <Link2 className="h-3 w-3" />
                          </span>
                        </TooltipTrigger>
                        <TooltipContent side="top" className="text-xs">
                          {item.linkedTooltip}
                        </TooltipContent>
                      </Tooltip>
                    )}
                  </label>
                );
              })}
            </TooltipProvider>
          </div>
        </>
      )}
    </div>
  );
}

function flattenTreeGroupIds(tree: ContextSourceTreeNode[]): string[] {
  const out: string[] = [];
  const walk = (node: ContextSourceTreeNode) => {
    out.push(node.id);
    (node.children ?? []).forEach(walk);
  };
  tree.forEach(walk);
  return out;
}
