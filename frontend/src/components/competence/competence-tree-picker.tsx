"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Search } from "lucide-react";

import { useTreeExpansion } from "@/hooks/use-tree-expansion";
import type { Competence, CompetenceGroupTree } from "@/lib/types";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { TreeExpandControls } from "@/components/ui/tree-expand-controls";

export interface CompetenceTreePickerProps {
  tree: CompetenceGroupTree[];
  selectedIds: Set<string>;
  onChange: (next: Set<string>) => void;
  testIdPrefix?: string;
}

interface RenderProps {
  groups: CompetenceGroupTree[];
  depth: number;
  isExpanded: (id: string) => boolean;
  toggleExpand: (id: string) => void;
  selected: Set<string>;
  toggleNode: (compIds: string[]) => void;
  search: string;
  testIdPrefix: string;
}

function matchesSearch(g: CompetenceGroupTree, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  if (g.title.toLowerCase().includes(q)) return true;
  if ((g.competences || []).some((c) => c.title.toLowerCase().includes(q)))
    return true;
  return (g.children || []).some((ch) => matchesSearch(ch, q));
}

function renderTree(props: RenderProps): React.ReactNode {
  const {
    groups,
    depth,
    isExpanded,
    toggleExpand,
    selected,
    toggleNode,
    search,
    testIdPrefix,
  } = props;
  const elements: React.ReactNode[] = [];
  for (const g of groups) {
    if (!matchesSearch(g, search)) continue;
    const compIdsAll: string[] = [];
    const collect = (node: CompetenceGroupTree) => {
      for (const c of node.competences || []) compIdsAll.push(c.id);
      for (const ch of node.children || []) collect(ch);
    };
    collect(g);
    const allSelected =
      compIdsAll.length > 0 && compIdsAll.every((id) => selected.has(id));
    // Partial-selection rendering: when only some of the group's competences
    // are picked, the checkbox shows the indeterminate state — same UX as
    // the "Select competences for assessment" sheet. Base UI exposes
    // indeterminate as a separate boolean prop alongside `checked`.
    const someSelected =
      !allSelected && compIdsAll.some((id) => selected.has(id));
    const isOpen = isExpanded(g.id) || !!search;
    const childComps = (g.competences || []).filter(
      (c) =>
        !search ||
        c.title.toLowerCase().includes(search.toLowerCase()) ||
        g.title.toLowerCase().includes(search.toLowerCase()),
    );
    elements.push(
      <div key={g.id}>
        <div
          className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted"
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
        >
          <button
            type="button"
            onClick={() => toggleExpand(g.id)}
            className="flex size-5 items-center justify-center rounded hover:bg-accent"
            aria-label={isOpen ? "Collapse" : "Expand"}
            data-testid={`${testIdPrefix}-group-toggle-${g.id}`}
          >
            {isOpen ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronRight className="size-3.5" />
            )}
          </button>
          <Checkbox
            checked={allSelected}
            indeterminate={someSelected}
            onCheckedChange={() => toggleNode(compIdsAll)}
            data-testid={`${testIdPrefix}-group-${g.id}`}
          />
          <span className="text-sm font-medium">{g.title}</span>
          <span className="text-xs text-muted-foreground">
            {compIdsAll.length}
          </span>
        </div>
        {isOpen && (
          <>
            {(g.children || []).length > 0 &&
              renderTree({
                ...props,
                groups: g.children || [],
                depth: depth + 1,
              })}
            {childComps.map((c: Competence) => (
              <label
                key={c.id}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted"
                style={{ paddingLeft: `${(depth + 1) * 16 + 8 + 20}px` }}
              >
                <Checkbox
                  checked={selected.has(c.id)}
                  onCheckedChange={() => toggleNode([c.id])}
                  data-testid={`${testIdPrefix}-${c.id}`}
                />
                <span className="text-sm">{c.title}</span>
              </label>
            ))}
          </>
        )}
      </div>,
    );
  }
  return elements;
}

/**
 * Standalone tree picker for competence groups + competences. Unlike
 * `CompetenceTreeSheet`, this component renders only the search input,
 * expand controls, and tree — the caller wraps it in whatever container
 * (Dialog, Sheet, inline panel) it needs.
 *
 * Selection is controlled: pass a `Set` of competence ids and an
 * `onChange` callback receiving the next set.
 */
export function CompetenceTreePicker({
  tree,
  selectedIds,
  onChange,
  testIdPrefix = "competence-tree-picker",
}: CompetenceTreePickerProps) {
  const [search, setSearch] = useState("");

  const allGroupIds = useMemo(() => {
    const ids: string[] = [];
    const walk = (groups: CompetenceGroupTree[]) => {
      for (const g of groups) {
        ids.push(g.id);
        if (g.children?.length) walk(g.children);
      }
    };
    walk(tree);
    return ids;
  }, [tree]);

  const {
    isExpanded,
    toggle: toggleExpand,
    expandAll,
    collapseAll,
    allExpanded,
    allCollapsed,
  } = useTreeExpansion(allGroupIds, "none");

  const toggleNode = (compIds: string[]) => {
    const next = new Set(selectedIds);
    const allIn = compIds.every((id) => next.has(id));
    if (allIn) compIds.forEach((id) => next.delete(id));
    else compIds.forEach((id) => next.add(id));
    onChange(next);
  };

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Group or competence title"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
          data-testid={`${testIdPrefix}-search`}
        />
      </div>
      {!search && (
        <div className="flex items-center justify-end">
          <TreeExpandControls
            expandAll={expandAll}
            collapseAll={collapseAll}
            allExpanded={allExpanded}
            allCollapsed={allCollapsed}
            testIdPrefix={testIdPrefix}
          />
        </div>
      )}
      <div className="max-h-[50vh] -mx-1 overflow-y-auto rounded-md border">
        {tree.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No published competences
          </p>
        ) : (
          renderTree({
            groups: tree,
            depth: 0,
            isExpanded,
            toggleExpand,
            selected: selectedIds,
            toggleNode,
            search,
            testIdPrefix,
          })
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        {selectedIds.size} selected
      </p>
    </div>
  );
}
