import { describe, it, expect } from "vitest";

// HRP-109: pure-logic test of the rules that `useTreeExpansion` implements
// (vitest is configured without jsdom, so we can't render hooks directly).
// The functions below mirror the branches in
// `src/hooks/use-tree-expansion.ts` — keep them in sync.

type Mode = "all" | "none";

function isExpanded(overrides: Set<string>, mode: Mode, id: string): boolean {
  if (mode === "all") return !overrides.has(id);
  return overrides.has(id);
}

function bulkSet(mode: Mode, ids: string[], op: "expand" | "collapse"): Set<string> {
  if (mode === "all") {
    return op === "expand" ? new Set() : new Set(ids);
  }
  return op === "expand" ? new Set(ids) : new Set();
}

function summary(
  overrides: Set<string>,
  mode: Mode,
  ids: string[],
): { allExpanded: boolean; allCollapsed: boolean } {
  if (ids.length === 0) return { allExpanded: true, allCollapsed: true };
  const open = ids.filter((id) => isExpanded(overrides, mode, id)).length;
  return { allExpanded: open === ids.length, allCollapsed: open === 0 };
}

describe("useTreeExpansion rules (mode=all, default-open)", () => {
  const mode: Mode = "all";
  const ids = ["g1", "g2", "g3"];

  it("ids are open when missing from the override set", () => {
    const s = new Set<string>();
    expect(isExpanded(s, mode, "g1")).toBe(true);
    expect(summary(s, mode, ids)).toEqual({
      allExpanded: true,
      allCollapsed: false,
    });
  });

  it("an id in the override set is collapsed", () => {
    const s = new Set(["g2"]);
    expect(isExpanded(s, mode, "g2")).toBe(false);
    expect(isExpanded(s, mode, "g1")).toBe(true);
    expect(summary(s, mode, ids)).toEqual({
      allExpanded: false,
      allCollapsed: false,
    });
  });

  it("collapseAll() pins every known id into the override set", () => {
    const collapsed = bulkSet(mode, ids, "collapse");
    expect(collapsed).toEqual(new Set(ids));
    expect(summary(collapsed, mode, ids)).toEqual({
      allExpanded: false,
      allCollapsed: true,
    });
  });

  it("expandAll() empties the override set", () => {
    const expanded = bulkSet(mode, ids, "expand");
    expect(expanded.size).toBe(0);
    expect(summary(expanded, mode, ids)).toEqual({
      allExpanded: true,
      allCollapsed: false,
    });
  });
});

describe("useTreeExpansion rules (mode=none, default-closed)", () => {
  const mode: Mode = "none";
  const ids = ["g1", "g2", "g3"];

  it("ids are closed when missing from the override set", () => {
    const s = new Set<string>();
    expect(isExpanded(s, mode, "g1")).toBe(false);
    expect(summary(s, mode, ids)).toEqual({
      allExpanded: false,
      allCollapsed: true,
    });
  });

  it("an id in the override set is expanded", () => {
    const s = new Set(["g2"]);
    expect(isExpanded(s, mode, "g2")).toBe(true);
    expect(summary(s, mode, ids)).toEqual({
      allExpanded: false,
      allCollapsed: false,
    });
  });

  it("expandAll() loads every known id into the override set", () => {
    const expanded = bulkSet(mode, ids, "expand");
    expect(expanded).toEqual(new Set(ids));
    expect(summary(expanded, mode, ids)).toEqual({
      allExpanded: true,
      allCollapsed: false,
    });
  });

  it("collapseAll() empties the override set", () => {
    const collapsed = bulkSet(mode, ids, "collapse");
    expect(collapsed.size).toBe(0);
    expect(summary(collapsed, mode, ids)).toEqual({
      allExpanded: false,
      allCollapsed: true,
    });
  });
});

describe("useTreeExpansion edge: empty tree", () => {
  it("both modes report allExpanded && allCollapsed when there are no ids", () => {
    const empty: string[] = [];
    expect(summary(new Set(), "all", empty)).toEqual({
      allExpanded: true,
      allCollapsed: true,
    });
    expect(summary(new Set(), "none", empty)).toEqual({
      allExpanded: true,
      allCollapsed: true,
    });
  });
});
