// HRP-100: pure tree helpers for the Add-competences dialog so the
// component file only renders, and vitest can pin the cascade / search
// behaviour without a DOM.

import type { Competence, CompetenceGroupTree } from "@/lib/types";

export interface FlatNode {
  groupId: string;
  groupTitle: string;
  /** Path from root to this group (inclusive), useful for breadcrumbs. */
  path: string[];
  competences: Competence[];
  /** Chain of ancestor groupIds (root → direct parent). Empty for a root.
   *  Lets `visiblePickerNodes` hide descendants when an ancestor collapses. */
  ancestorIds: string[];
}

/** Flatten the tree so each group becomes a row with its direct competences,
 *  preserving parent breadcrumbs. Inactive competences are dropped so the
 *  picker matches the live matrix surface.
 */
export function flattenForPicker(tree: CompetenceGroupTree[]): FlatNode[] {
  const out: FlatNode[] = [];
  function visit(
    node: CompetenceGroupTree,
    parentTitles: string[],
    ancestorIds: string[],
  ) {
    const path = [...parentTitles, node.title];
    out.push({
      groupId: node.id,
      groupTitle: node.title,
      path,
      competences: (node.competences ?? []).filter((c) => c.is_active),
      ancestorIds,
    });
    const nextAncestors = [...ancestorIds, node.id];
    for (const child of node.children ?? []) visit(child, path, nextAncestors);
  }
  for (const root of tree) visit(root, [], []);
  return out;
}

/** Hide nodes whose any ancestor is currently collapsed. Roots are always
 *  visible; nested groups only render when every ancestor reports expanded.
 *  Used by the dialog's per-branch collapse — search bypasses this and
 *  shows every match instead.
 */
export function visiblePickerNodes(
  nodes: FlatNode[],
  isExpanded: (groupId: string) => boolean,
): FlatNode[] {
  return nodes.filter((n) => n.ancestorIds.every((id) => isExpanded(id)));
}

/** Lowercase, trimmed substring match against competence title OR any
 *  ancestor group title. An empty query returns every node unchanged so
 *  the caller can branch on `query.trim() === ""` upstream.
 */
export function filterPickerNodes(nodes: FlatNode[], query: string): FlatNode[] {
  const q = query.trim().toLowerCase();
  if (!q) return nodes;
  return nodes
    .map((node) => {
      const groupMatch = node.path.some((t) => t.toLowerCase().includes(q));
      const matchingComps = groupMatch
        ? node.competences
        : node.competences.filter((c) => c.title.toLowerCase().includes(q));
      if (!groupMatch && matchingComps.length === 0) return null;
      return { ...node, competences: matchingComps };
    })
    .filter((n): n is FlatNode => n !== null);
}

/** Group-level checkbox state. `mixed` means some competences in the group
 *  are picked and some aren't — render with an indeterminate visual.
 */
export type GroupCheckState = "empty" | "mixed" | "full";

export function groupCheckState(
  node: FlatNode,
  selected: ReadonlySet<string>,
  alreadyInMatrix: ReadonlySet<string>,
): GroupCheckState {
  const candidates = node.competences.filter((c) => !alreadyInMatrix.has(c.id));
  if (candidates.length === 0) return "empty";
  let on = 0;
  for (const c of candidates) if (selected.has(c.id)) on += 1;
  if (on === 0) return "empty";
  if (on === candidates.length) return "full";
  return "mixed";
}

/** Toggle every competence the group can still contribute (i.e. skip the
 *  ones already attached to the matrix). Returns a fresh Set so the caller
 *  can drop the result straight into `setSelected`.
 */
export function toggleGroupCompetences(
  node: FlatNode,
  selected: ReadonlySet<string>,
  alreadyInMatrix: ReadonlySet<string>,
  nextState: GroupCheckState,
): Set<string> {
  const next = new Set(selected);
  for (const c of node.competences) {
    if (alreadyInMatrix.has(c.id)) continue;
    if (nextState === "full") next.add(c.id);
    else next.delete(c.id);
  }
  return next;
}
