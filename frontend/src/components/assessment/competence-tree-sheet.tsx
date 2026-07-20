"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Search } from "lucide-react";

import { useCompetenceTree } from "@/hooks/use-competence-tree";
import { useTreeExpansion } from "@/hooks/use-tree-expansion";
import type { Competence, CompetenceGroupTree } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { TreeExpandControls } from "@/components/ui/tree-expand-controls";

export interface SelectedCompetence {
  id: string;
  title: string;
}

export interface CompetenceTreeSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialIds: string[];
  onSave: (selected: SelectedCompetence[]) => void;
}

interface RenderProps {
  groups: CompetenceGroupTree[];
  parentId: string | null;
  depth: number;
  isExpanded: (id: string) => boolean;
  toggleExpand: (id: string) => void;
  selected: Set<string>;
  toggleNode: (compIds: string[]) => void;
  search: string;
}

function matchesSearch(g: CompetenceGroupTree, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  if (g.title.toLowerCase().includes(q)) return true;
  if ((g.competences || []).some((c) => c.title.toLowerCase().includes(q))) return true;
  return (g.children || []).some((ch) => matchesSearch(ch, q));
}

function renderTree(props: RenderProps): React.ReactNode {
  const { groups, depth, isExpanded, toggleExpand, selected, toggleNode, search } = props;
  const elements: React.ReactNode[] = [];
  for (const g of groups) {
    if (!matchesSearch(g, search)) continue;
    const compIdsAll: string[] = [];
    const collect = (node: CompetenceGroupTree) => {
      for (const c of node.competences || []) compIdsAll.push(c.id);
      for (const ch of node.children || []) collect(ch);
    };
    collect(g);
    const allSelected = compIdsAll.length > 0 && compIdsAll.every((id) => selected.has(id));
    // Search forces every matching branch open so the user sees results.
    const isOpen = isExpanded(g.id) || !!search;
    const childComps = (g.competences || []).filter((c) => !search || c.title.toLowerCase().includes(search.toLowerCase()) || g.title.toLowerCase().includes(search.toLowerCase()));
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
          >
            {isOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
          </button>
          <Checkbox
            checked={allSelected}
            onCheckedChange={() => toggleNode(compIdsAll)}
          />
          <span className="text-sm font-medium">{g.title}</span>
          <span className="text-xs text-muted-foreground">{compIdsAll.length}</span>
        </div>
        {isOpen && (
          <>
            {(g.children || []).length > 0 &&
              renderTree({ ...props, groups: g.children || [], depth: depth + 1 })}
            {childComps.map((c: Competence) => (
              <label
                key={c.id}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted"
                style={{ paddingLeft: `${(depth + 1) * 16 + 8 + 20}px` }}
              >
                <Checkbox
                  checked={selected.has(c.id)}
                  onCheckedChange={() => toggleNode([c.id])}
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

function CompetenceTreeBody({ initialIds, onClose, onSave }: { initialIds: string[]; onClose: () => void; onSave: (selected: SelectedCompetence[]) => void }) {
  const { tree, loading } = useCompetenceTree();
  const [selected, setSelected] = useState<Set<string>>(() => new Set(initialIds));
  const [search, setSearch] = useState("");

  const { titleByCompId, allGroupIds } = useMemo(() => {
    const map = new Map<string, string>();
    const ids: string[] = [];
    const walk = (groups: CompetenceGroupTree[]) => {
      for (const g of groups) {
        ids.push(g.id);
        for (const c of g.competences || []) map.set(c.id, c.title);
        if (g.children?.length) walk(g.children);
      }
    };
    walk(tree);
    return { titleByCompId: map, allGroupIds: ids };
  }, [tree]);

  // HRP-109: picker tree defaults to fully collapsed — the only previously
  // open group on mount was none, so we keep that and let users expand
  // either via the chevron or the new Expand-all button.
  const {
    isExpanded,
    toggle: toggleExpand,
    expandAll,
    collapseAll,
    allExpanded,
    allCollapsed,
  } = useTreeExpansion(allGroupIds, "none");

  const toggleNode = (compIds: string[]) => {
    setSelected((prev) => {
      const next = new Set(prev);
      const allIn = compIds.every((id) => next.has(id));
      if (allIn) compIds.forEach((id) => next.delete(id));
      else compIds.forEach((id) => next.add(id));
      return next;
    });
  };

  const flatCount = useMemo(() => selected.size, [selected]);

  return (
    <SheetContent className="max-w-xl">
      <SheetHeader>
        <SheetTitle>Select competences for assessment</SheetTitle>
        <p className="text-sm text-muted-foreground">Selected competences: {flatCount}</p>
      </SheetHeader>
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Group or competence title"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
          data-testid="competence-tree-search"
        />
      </div>
      {/* HRP-109: bulk expand/collapse — hidden while the user is searching,
        because the tree force-expands every matching branch and the buttons
        would visibly do nothing. */}
      {!search && (
        <div className="flex items-center justify-end pt-1">
          <TreeExpandControls
            expandAll={expandAll}
            collapseAll={collapseAll}
            allExpanded={allExpanded}
            allCollapsed={allCollapsed}
            testIdPrefix="competence-tree"
          />
        </div>
      )}
      <div className="-mx-1 flex-1 overflow-y-auto">
        {loading ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Loading…</p>
        ) : tree.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">No published competences</p>
        ) : (
          renderTree({
            groups: tree,
            parentId: null,
            depth: 0,
            isExpanded,
            toggleExpand,
            selected,
            toggleNode,
            search,
          })
        )}
      </div>
      <SheetFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button
          data-testid="competence-tree-save"
          onClick={() => {
            onSave(
              Array.from(selected).map((id) => ({
                id,
                title: titleByCompId.get(id) ?? "",
              })),
            );
            onClose();
          }}
        >
          Save
        </Button>
      </SheetFooter>
    </SheetContent>
  );
}

export function CompetenceTreeSheet({ open, onOpenChange, initialIds, onSave }: CompetenceTreeSheetProps) {
  // Remount on each open so internal state initializes from initialIds cleanly
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      {open && (
        <CompetenceTreeBody
          initialIds={initialIds}
          onClose={() => onOpenChange(false)}
          onSave={onSave}
        />
      )}
    </Sheet>
  );
}
