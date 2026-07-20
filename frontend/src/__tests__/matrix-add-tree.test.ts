// HRP-100: pins the four helpers behind the Add-competences dialog —
// flatten, search filter, group check state, and group cascade toggle.

import { describe, expect, it } from "vitest";
import type { Competence, CompetenceGroupTree } from "@/lib/types";
import {
  filterPickerNodes,
  flattenForPicker,
  groupCheckState,
  toggleGroupCompetences,
  visiblePickerNodes,
} from "@/lib/matrix-add-tree";

function comp(
  id: string,
  title: string,
  isActive = true,
): Competence {
  return {
    id,
    title,
    description: null,
    group_id: "g",
    competence_type_id: null,
    tenant_id: null,
    is_active: isActive,
    is_published: true,
    is_origin: false,
    is_used: false,
    levels_completion: null,
    created_at: "2026-01-01T00:00:00Z",
  };
}

function group(
  id: string,
  title: string,
  competences: Competence[],
  children: CompetenceGroupTree[] = [],
): CompetenceGroupTree {
  return {
    id,
    title,
    parent_id: null,
    description: null,
    tenant_id: null,
    sort_index: 0,
    is_active: true,
    is_root_origin: false,
    can_deactivate: true,
    created_at: "2026-01-01T00:00:00Z",
    children,
    competences,
    competences_count: competences.length,
    is_used: false,
  };
}

const TREE: CompetenceGroupTree[] = [
  group(
    "g1",
    "Tech",
    [comp("c1", "Python"), comp("c2", "SQL"), comp("c3", "Old", false)],
    [
      group("g1a", "Cloud", [
        comp("c4", "AWS"),
        comp("c5", "Kubernetes"),
      ]),
    ],
  ),
  group("g2", "Soft skills", [comp("c6", "Communication")]),
];

describe("flattenForPicker", () => {
  it("emits one row per group with breadcrumb path", () => {
    const flat = flattenForPicker(TREE);
    expect(flat.map((n) => n.path.join(" / "))).toEqual([
      "Tech",
      "Tech / Cloud",
      "Soft skills",
    ]);
  });

  it("drops inactive competences so the picker mirrors the live matrix", () => {
    const flat = flattenForPicker(TREE);
    const tech = flat.find((n) => n.groupId === "g1")!;
    expect(tech.competences.map((c) => c.id)).toEqual(["c1", "c2"]);
  });

  it("records the chain of ancestor groupIds so the picker can hide collapsed branches (HRP-100 REDO)", () => {
    const flat = flattenForPicker(TREE);
    const byId = Object.fromEntries(flat.map((n) => [n.groupId, n.ancestorIds]));
    expect(byId.g1).toEqual([]);
    expect(byId.g1a).toEqual(["g1"]);
    expect(byId.g2).toEqual([]);
  });
});

describe("visiblePickerNodes", () => {
  const flat = flattenForPicker(TREE);

  it("returns every node when no group is collapsed", () => {
    const out = visiblePickerNodes(flat, () => true);
    expect(out.map((n) => n.groupId)).toEqual(["g1", "g1a", "g2"]);
  });

  it("hides descendants when an ancestor collapses", () => {
    // Collapse g1 → g1a (its child branch) must disappear; g2 stays.
    const out = visiblePickerNodes(flat, (id) => id !== "g1");
    expect(out.map((n) => n.groupId)).toEqual(["g1", "g2"]);
  });

  it("keeps a collapsed group itself visible — only its branches hide", () => {
    // The g1 row still renders; the operator needs the chevron to re-expand.
    const out = visiblePickerNodes(flat, (id) => id !== "g1");
    expect(out[0].groupId).toBe("g1");
  });
});

describe("filterPickerNodes", () => {
  const flat = flattenForPicker(TREE);

  it("returns the input unchanged for an empty query", () => {
    expect(filterPickerNodes(flat, "   ")).toEqual(flat);
  });

  it("matches competence titles case-insensitively", () => {
    const out = filterPickerNodes(flat, "PyT");
    expect(out).toHaveLength(1);
    expect(out[0].groupId).toBe("g1");
    expect(out[0].competences.map((c) => c.id)).toEqual(["c1"]);
  });

  it("matches group/breadcrumb titles and keeps every competence under the match", () => {
    const out = filterPickerNodes(flat, "cloud");
    expect(out).toHaveLength(1);
    expect(out[0].groupId).toBe("g1a");
    expect(out[0].competences.map((c) => c.id)).toEqual(["c4", "c5"]);
  });

  it("matches a top-level group via breadcrumb and pulls every descendant group along", () => {
    // "tech" only appears on the root group's title — every descendant
    // (including the Cloud sub-group rendered with breadcrumb "Tech / Cloud")
    // must come through with all its competences intact.
    const out = filterPickerNodes(flat, "tech");
    expect(out.map((n) => n.groupId)).toEqual(["g1", "g1a"]);
    expect(out[0].competences.map((c) => c.id)).toEqual(["c1", "c2"]);
    expect(out[1].competences.map((c) => c.id)).toEqual(["c4", "c5"]);
  });

  it("filters out groups with no match and no matching competences", () => {
    const out = filterPickerNodes(flat, "communic");
    expect(out.map((n) => n.groupId)).toEqual(["g2"]);
  });
});

describe("groupCheckState", () => {
  const flat = flattenForPicker(TREE);
  const tech = flat[0];

  it("returns empty when no descendant competence is selected", () => {
    expect(groupCheckState(tech, new Set(), new Set())).toBe("empty");
  });

  it("returns full when every selectable competence is selected", () => {
    expect(groupCheckState(tech, new Set(["c1", "c2"]), new Set())).toBe("full");
  });

  it("returns mixed when some — but not all — selectable competences are selected", () => {
    expect(groupCheckState(tech, new Set(["c1"]), new Set())).toBe("mixed");
  });

  it("ignores competences already in the matrix when judging the cascade state", () => {
    // c1 is in the matrix so only c2 counts. Selecting c2 → full.
    expect(groupCheckState(tech, new Set(["c2"]), new Set(["c1"]))).toBe("full");
  });

  it("returns empty when every competence is already in the matrix (nothing left to cascade)", () => {
    expect(groupCheckState(tech, new Set(), new Set(["c1", "c2"]))).toBe("empty");
  });
});

describe("toggleGroupCompetences", () => {
  const flat = flattenForPicker(TREE);
  const tech = flat[0];

  it("selects every non-matrix competence when cascade is set to full", () => {
    const next = toggleGroupCompetences(tech, new Set(), new Set(), "full");
    expect([...next].sort()).toEqual(["c1", "c2"]);
  });

  it("does not re-add competences already in the matrix", () => {
    const next = toggleGroupCompetences(tech, new Set(), new Set(["c1"]), "full");
    expect([...next]).toEqual(["c2"]);
  });

  it("removes every cascade-controlled competence when set to empty", () => {
    const next = toggleGroupCompetences(
      tech,
      new Set(["c1", "c2", "c4"]),
      new Set(),
      "empty",
    );
    // c4 lives under a different group so the toggle must leave it alone.
    expect([...next]).toEqual(["c4"]);
  });
});
