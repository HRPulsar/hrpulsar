"use client";

import { useCallback, useMemo, useState } from "react";

/**
 * HRP-109: shared expand/collapse state for tree-shaped lists.
 *
 * The hook treats expansion as a tri-state controlled by a `Set<string>`:
 *
 *   - When `defaultExpanded === "all"` (the typical case for the Competence
 *     DB and the company structure list), the Set holds *collapsed* IDs and
 *     missing IDs are considered open. This matches the historical default
 *     of those pages (every group was rendered open on mount).
 *   - When `defaultExpanded === "none"` (the picker dialog), the Set holds
 *     *expanded* IDs and missing IDs are closed.
 *
 * Callers pass in `allIds` — the full collapsible-node list of the tree —
 * so `expandAll` / `collapseAll` can flip the set in one go.
 *
 * The API stays stable so the same hook works in both modes:
 *   - `isExpanded(id)` — whether a node should render its children
 *   - `toggle(id)` — flip a single node
 *   - `expandAll()` / `collapseAll()` — bulk actions for the header buttons
 *   - `allExpanded` / `allCollapsed` — to disable the matching button
 */
export type TreeDefault = "all" | "none";

export interface UseTreeExpansion {
  isExpanded: (id: string) => boolean;
  toggle: (id: string) => void;
  expandAll: () => void;
  collapseAll: () => void;
  allExpanded: boolean;
  allCollapsed: boolean;
}

export function useTreeExpansion(
  allIds: string[],
  defaultExpanded: TreeDefault = "all",
): UseTreeExpansion {
  // The Set's meaning flips with `defaultExpanded` — see the module docstring.
  const [overrides, setOverrides] = useState<Set<string>>(() => new Set());

  const allIdsKey = useMemo(() => allIds.join("|"), [allIds]);
  // Snapshot the array under a content-hash key so bulk actions stay
  // referentially stable across renders where `allIds` is recreated with
  // the same contents. The deps lint is intentionally suppressed — the
  // join-key is the canonical change signal for this snapshot.
  const allIdsSnapshot = useMemo(() => allIds, [allIdsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const isExpanded = useCallback(
    (id: string) => {
      if (defaultExpanded === "all") return !overrides.has(id);
      return overrides.has(id);
    },
    [overrides, defaultExpanded],
  );

  const toggle = useCallback((id: string) => {
    setOverrides((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const expandAll = useCallback(() => {
    if (defaultExpanded === "all") setOverrides(new Set());
    else setOverrides(new Set(allIdsSnapshot));
  }, [defaultExpanded, allIdsSnapshot]);

  const collapseAll = useCallback(() => {
    if (defaultExpanded === "all") setOverrides(new Set(allIdsSnapshot));
    else setOverrides(new Set());
  }, [defaultExpanded, allIdsSnapshot]);

  const { allExpanded, allCollapsed } = useMemo(() => {
    if (allIdsSnapshot.length === 0) {
      return { allExpanded: true, allCollapsed: true };
    }
    const openCount = allIdsSnapshot.reduce(
      (n, id) =>
        (defaultExpanded === "all" ? !overrides.has(id) : overrides.has(id))
          ? n + 1
          : n,
      0,
    );
    return {
      allExpanded: openCount === allIdsSnapshot.length,
      allCollapsed: openCount === 0,
    };
  }, [overrides, allIdsSnapshot, defaultExpanded]);

  return { isExpanded, toggle, expandAll, collapseAll, allExpanded, allCollapsed };
}
