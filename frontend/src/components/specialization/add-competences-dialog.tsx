"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  CheckSquare,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  MinusSquare,
  Plus,
  Search,
  Square,
} from "lucide-react";

import { useTreeExpansion } from "@/hooks/use-tree-expansion";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { TreeExpandControls } from "@/components/ui/tree-expand-controls";
import {
  filterPickerNodes,
  flattenForPicker,
  groupCheckState,
  toggleGroupCompetences,
  visiblePickerNodes,
} from "@/lib/matrix-add-tree";
import type { CompetenceGroupTree } from "@/lib/types";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tree: CompetenceGroupTree[];
  /** Competences already linked to the current spec×grade matrix — they
   *  show up disabled so the operator can see them in context but cannot
   *  re-add them. */
  alreadyInMatrix: Set<string>;
  /** Called when the operator presses Save; receives only the IDs that
   *  were *newly* selected (i.e. not already in the matrix). */
  onConfirm: (newCompetenceIds: string[]) => void;
}

export function AddCompetencesDialog({
  open,
  onOpenChange,
  tree,
  alreadyInMatrix,
  onConfirm,
}: Props) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [query, setQuery] = useState("");

  const allNodes = useMemo(() => flattenForPicker(tree), [tree]);
  const allGroupIds = useMemo(() => allNodes.map((n) => n.groupId), [allNodes]);
  // HRP-100 REDO: per-branch + global expand/collapse. Default-open mirrors
  // the historical picker behaviour. While a search query is active the
  // collapse state is bypassed so matches always render — the same rule
  // CompetenceTreePicker uses.
  const {
    isExpanded,
    toggle: toggleExpand,
    expandAll,
    collapseAll,
    allExpanded,
    allCollapsed,
  } = useTreeExpansion(allGroupIds, "all");
  const hasQuery = query.trim() !== "";
  const visibleNodes = useMemo(() => {
    const filtered = filterPickerNodes(allNodes, query);
    return hasQuery ? filtered : visiblePickerNodes(filtered, isExpanded);
  }, [allNodes, query, hasQuery, isExpanded]);

  // Derive the "actually-new" selection on every render so a parallel tab
  // landing Save (which mutates `alreadyInMatrix`) can't leave stale IDs in
  // the counter or cascade-state calculations. `selected` itself is left
  // untouched — `handleSave` filters again before calling onConfirm.
  const effectiveSelected = useMemo(() => {
    const out = new Set<string>();
    for (const id of selected) if (!alreadyInMatrix.has(id)) out.add(id);
    return out;
  }, [selected, alreadyInMatrix]);

  function reset() {
    setSelected(new Set());
    setQuery("");
  }

  function handleCancel() {
    reset();
    onOpenChange(false);
  }

  function handleSave() {
    onConfirm([...effectiveSelected]);
    reset();
    onOpenChange(false);
  }

  function toggleComp(id: string, next: boolean) {
    setSelected((prev) => {
      const out = new Set(prev);
      if (next) out.add(id);
      else out.delete(id);
      return out;
    });
  }

  function toggleGroup(nodeIndex: number, nextState: "empty" | "full") {
    const node = visibleNodes[nodeIndex];
    if (!node) return;
    setSelected((prev) => toggleGroupCompetences(node, prev, alreadyInMatrix, nextState));
  }

  const newSelectionCount = effectiveSelected.size;

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : handleCancel())}>
      <DialogContent
        data-testid="matrix-add-competences-dialog"
        className="sm:max-w-2xl"
      >
        <DialogHeader>
          <DialogTitle>Add competences to the matrix</DialogTitle>
          <DialogDescription>
            Tick competences or whole groups; saved levels are not affected
            until you press Save in the matrix editor. Use the search to
            narrow the tree.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <label className="flex flex-1 items-center gap-2 rounded-md border bg-background px-2 py-1">
              <Search className="h-4 w-4 text-muted-foreground" aria-hidden />
              <Input
                data-testid="matrix-add-competences-search"
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search groups or competences..."
                className="h-7 border-0 p-0 focus-visible:ring-0"
              />
            </label>
            {!hasQuery && allGroupIds.length > 0 && (
              <TreeExpandControls
                expandAll={expandAll}
                collapseAll={collapseAll}
                allExpanded={allExpanded}
                allCollapsed={allCollapsed}
                testIdPrefix="matrix-add-competences"
                size="xs"
              />
            )}
          </div>

          <div className="max-h-[60vh] overflow-y-auto rounded-md border">
            {visibleNodes.length === 0 ? (
              <p
                data-testid="matrix-add-competences-empty"
                className="px-3 py-6 text-center text-sm text-muted-foreground"
              >
                No competences match this filter.
              </p>
            ) : (
              <ul className="divide-y">
                {visibleNodes.map((node, idx) => {
                  const state = groupCheckState(node, effectiveSelected, alreadyInMatrix);
                  const groupDisabled =
                    node.competences.filter((c) => !alreadyInMatrix.has(c.id)).length === 0;
                  // Three-state button instead of a base-ui Checkbox: the
                  // wrapper doesn't forward `indeterminate`, so "mixed"
                  // would render as plain unchecked. The icon switch keeps
                  // partial-selection visible at a glance.
                  const GroupIcon =
                    state === "full"
                      ? CheckSquare
                      : state === "mixed"
                        ? MinusSquare
                        : Square;
                  const nextState: "empty" | "full" =
                    state === "full" ? "empty" : "full";
                  // HRP-100 REDO: open by default. Search always shows the
                  // matching branch open so the operator sees the hit
                  // without an extra click.
                  const branchOpen = hasQuery || isExpanded(node.groupId);
                  const indentRem = node.ancestorIds.length * 1;
                  return (
                    <li key={node.groupId} className="px-3 py-2">
                      <div
                        className="flex items-center gap-2"
                        style={{ paddingLeft: `${indentRem}rem` }}
                      >
                        <button
                          type="button"
                          onClick={() => toggleExpand(node.groupId)}
                          disabled={hasQuery}
                          data-testid={`matrix-add-group-${node.groupId}-toggle`}
                          aria-label={branchOpen ? `Collapse ${node.groupTitle}` : `Expand ${node.groupTitle}`}
                          aria-expanded={branchOpen}
                          className="flex size-5 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          {branchOpen ? (
                            <ChevronDown className="size-3.5" />
                          ) : (
                            <ChevronRight className="size-3.5" />
                          )}
                        </button>
                        <button
                          type="button"
                          data-testid={`matrix-add-group-${node.groupId}`}
                          data-state={state}
                          aria-checked={
                            state === "full"
                              ? "true"
                              : state === "mixed"
                                ? "mixed"
                                : "false"
                          }
                          role="checkbox"
                          disabled={groupDisabled}
                          onClick={() => toggleGroup(idx, nextState)}
                          aria-label={`Toggle every competence under ${node.groupTitle}`}
                          className={
                            "inline-flex items-center text-primary transition disabled:cursor-not-allowed disabled:opacity-50 " +
                            (state === "empty"
                              ? "text-muted-foreground hover:text-primary"
                              : "")
                          }
                        >
                          <GroupIcon className="h-4 w-4" />
                        </button>
                        <span
                          className="text-sm font-medium"
                          title={node.path.join(" / ")}
                        >
                          {node.path.join(" / ")}
                        </span>
                        {state === "mixed" && (
                          <span
                            data-testid={`matrix-add-group-${node.groupId}-mixed`}
                            className="text-[0.7rem] text-muted-foreground"
                          >
                            partial
                          </span>
                        )}
                      </div>
                      {branchOpen && node.competences.length > 0 && (
                        <ul
                          data-testid={`matrix-add-group-${node.groupId}-comps`}
                          className="mt-1.5 space-y-1 pl-6"
                          style={{ marginLeft: `${indentRem}rem` }}
                        >
                          {node.competences.map((comp) => {
                            const inMatrix = alreadyInMatrix.has(comp.id);
                            const isOn = inMatrix || effectiveSelected.has(comp.id);
                            return (
                              <li
                                key={comp.id}
                                className="flex items-center gap-2"
                              >
                                <Checkbox
                                  data-testid={`matrix-add-comp-${comp.id}`}
                                  checked={isOn}
                                  disabled={inMatrix}
                                  onCheckedChange={(next) =>
                                    toggleComp(comp.id, !!next)
                                  }
                                  aria-label={comp.title}
                                />
                                <span
                                  className={
                                    "flex-1 text-sm " +
                                    (inMatrix ? "text-muted-foreground line-through" : "")
                                  }
                                >
                                  {comp.title}
                                </span>
                                <Link
                                  href={`/competences/${comp.id}`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  data-testid={`matrix-add-comp-${comp.id}-open`}
                                  className="text-muted-foreground hover:text-foreground"
                                  title="Open competence in a new tab"
                                >
                                  <ExternalLink className="h-3.5 w-3.5" />
                                </Link>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="flex items-center justify-between gap-3 text-sm">
            <span
              data-testid="matrix-add-competences-counter"
              className="text-muted-foreground"
            >
              {newSelectionCount} new selected
            </span>
            <Link
              href="/competences"
              target="_blank"
              rel="noopener noreferrer"
              data-testid="matrix-add-competences-create-link"
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              <Plus className="h-3.5 w-3.5" />
              Create new in /competences
              <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={handleCancel}
            data-testid="matrix-add-competences-cancel"
          >
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={newSelectionCount === 0}
            data-testid="matrix-add-competences-save"
          >
            Add {newSelectionCount > 0 ? `(${newSelectionCount})` : ""}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
