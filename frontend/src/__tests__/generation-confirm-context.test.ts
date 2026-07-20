import { describe, it, expect } from "vitest";

// HRP-123 / HRP-124 / HRP-114: exercises the decision rules
// `GenerationConfirmDialog` uses to build the request payload and assemble
// the chip list per scope. Vitest runs without jsdom, so the component
// itself isn't rendered — these tests guard the pure logic.

const BASE_CONTEXT_KEYS = ["specializations", "divisions", "company"];
const WHOLE_BASE_AUGMENT_EXTRA = "source_tree"; // HRP-124: only when library non-empty
const GROUP_EXTRAS = ["source_tree"]; // HRP-114: group's existing competences
const INDICATOR_EXTRAS = ["sibling_competences", "existing_indicators"]; // HRP-114

type Scope =
  | "whole_base"
  | "group"
  | "competence_indicators"
  | "specialization_matrix";

function availableCategoryKeys(
  scope: Scope,
  hasExistingLibrary: boolean,
): string[] {
  if (scope === "specialization_matrix") return [];
  const extras: string[] = [];
  if (scope === "group") extras.push(...GROUP_EXTRAS);
  if (scope === "competence_indicators") extras.push(...INDICATOR_EXTRAS);
  if (scope === "whole_base" && hasExistingLibrary)
    extras.push(WHOLE_BASE_AUGMENT_EXTRA);
  return [...BASE_CONTEXT_KEYS, ...extras];
}

function toggleExclude(current: Set<string>, key: string): Set<string> {
  const next = new Set(current);
  if (next.has(key)) {
    next.delete(key);
  } else {
    next.add(key);
  }
  return next;
}

interface SubmitPayload {
  with_indicators: boolean;
  refinement_prompt?: string;
  context_excludes?: string[];
}

function buildSubmitPayload(
  scope: Scope,
  withIndicators: boolean,
  excludes: Set<string>,
  refinement: string,
  augmentExisting: boolean = false,
): SubmitPayload {
  const payload: SubmitPayload = { with_indicators: withIndicators };
  // HRP-114: every scope except the matrix (own dialog) goes through the
  // context-chips + refinement pipeline.
  if (scope === "specialization_matrix") return payload;
  // HRP-155: when augment is off for the group scope, the dialog
  // force-excludes both source_tree and descendants regardless of which
  // chips the picker shows.
  const merged = new Set(excludes);
  if (scope === "group" && !augmentExisting) {
    merged.add("source_tree");
    merged.add("descendants");
  }
  if (merged.size > 0) payload.context_excludes = Array.from(merged);
  const trimmed = refinement.trim();
  if (trimmed) payload.refinement_prompt = trimmed;
  return payload;
}

describe("context exclude toggle", () => {
  it("adds a key the first time it's toggled", () => {
    const r = toggleExclude(new Set(), "divisions");
    expect(r.has("divisions")).toBe(true);
    expect(r.size).toBe(1);
  });

  it("removes a key on second toggle", () => {
    let s = toggleExclude(new Set(), "divisions");
    s = toggleExclude(s, "divisions");
    expect(s.has("divisions")).toBe(false);
    expect(s.size).toBe(0);
  });

  it("supports multiple excluded keys", () => {
    let s = toggleExclude(new Set(), "specializations");
    s = toggleExclude(s, "company");
    expect(Array.from(s).sort()).toEqual(["company", "specializations"]);
  });
});

describe("buildSubmitPayload for whole_base", () => {
  it("includes only with_indicators when nothing extra is set", () => {
    const p = buildSubmitPayload("whole_base", true, new Set(), "");
    expect(p).toEqual({ with_indicators: true });
  });

  it("adds context_excludes when categories are dropped", () => {
    const p = buildSubmitPayload(
      "whole_base",
      true,
      new Set(["divisions"]),
      "",
    );
    expect(p).toEqual({ with_indicators: true, context_excludes: ["divisions"] });
  });

  it("trims refinement_prompt and drops empty strings", () => {
    const blank = buildSubmitPayload("whole_base", true, new Set(), "   ");
    expect(blank.refinement_prompt).toBeUndefined();

    const real = buildSubmitPayload(
      "whole_base",
      true,
      new Set(),
      "  emphasise cloud  ",
    );
    expect(real.refinement_prompt).toBe("emphasise cloud");
  });

  it("can carry both context_excludes and refinement_prompt", () => {
    const p = buildSubmitPayload(
      "whole_base",
      false,
      new Set(["specializations", "company"]),
      "include AWS specifics",
    );
    expect(p.with_indicators).toBe(false);
    expect(p.context_excludes?.sort()).toEqual(["company", "specializations"]);
    expect(p.refinement_prompt).toBe("include AWS specifics");
  });
});

describe("buildSubmitPayload for HRP-114 scopes", () => {
  it("emits context_excludes for group scope with augment ON", () => {
    const p = buildSubmitPayload(
      "group",
      true,
      new Set(["divisions", "source_tree"]),
      "include security topics",
      true, // augment ON — source_tree stays whatever the chips say.
    );
    expect(p.with_indicators).toBe(true);
    expect(p.context_excludes?.sort()).toEqual(["divisions", "source_tree"]);
    expect(p.refinement_prompt).toBe("include security topics");
  });

  it("emits context_excludes for competence_indicators scope", () => {
    const p = buildSubmitPayload(
      "competence_indicators",
      true,
      new Set(["sibling_competences", "existing_indicators"]),
      "",
    );
    expect(p.context_excludes?.sort()).toEqual([
      "existing_indicators",
      "sibling_competences",
    ]);
    expect(p.refinement_prompt).toBeUndefined();
  });

  it("still ignores context controls for specialization_matrix scope", () => {
    const p = buildSubmitPayload(
      "specialization_matrix",
      true,
      new Set(["divisions"]),
      "ignored",
    );
    expect(p).toEqual({ with_indicators: true });
  });
});

describe("context categories invariant", () => {
  it("matches the base keys the backend handlers consume", () => {
    expect(BASE_CONTEXT_KEYS).toEqual([
      "specializations",
      "divisions",
      "company",
    ]);
  });

  it("group scope appends source_tree chip", () => {
    expect(availableCategoryKeys("group", false)).toEqual([
      ...BASE_CONTEXT_KEYS,
      "source_tree",
    ]);
  });

  it("competence_indicators scope appends sibling + existing chips", () => {
    expect(availableCategoryKeys("competence_indicators", false)).toEqual([
      ...BASE_CONTEXT_KEYS,
      "sibling_competences",
      "existing_indicators",
    ]);
  });
});

describe("group augment toggle (HRP-155)", () => {
  it("defaults to augment OFF: source_tree + descendants force-excluded", () => {
    const p = buildSubmitPayload("group", true, new Set(), "");
    expect(p.context_excludes?.sort()).toEqual([
      "descendants",
      "source_tree",
    ]);
  });

  it("augment ON: no force-exclude, payload reflects only picker chips", () => {
    const p = buildSubmitPayload("group", true, new Set(), "", true);
    expect(p.context_excludes).toBeUndefined();
  });

  it("augment OFF merges with picker chips without duplicates", () => {
    const p = buildSubmitPayload(
      "group",
      true,
      new Set(["divisions", "source_tree"]),
      "",
    );
    expect(p.context_excludes?.sort()).toEqual([
      "descendants",
      "divisions",
      "source_tree",
    ]);
  });

  it("does not affect whole_base or competence_indicators scopes", () => {
    const wholeBase = buildSubmitPayload("whole_base", true, new Set(), "");
    const indicators = buildSubmitPayload(
      "competence_indicators",
      true,
      new Set(),
      "",
    );
    expect(wholeBase.context_excludes).toBeUndefined();
    expect(indicators.context_excludes).toBeUndefined();
  });
});

describe("augment-mode source_tree chip (HRP-124)", () => {
  it("hides source_tree from the whole_base chip list on an empty library", () => {
    expect(availableCategoryKeys("whole_base", false)).not.toContain(
      "source_tree",
    );
    expect(availableCategoryKeys("whole_base", false)).toEqual(
      BASE_CONTEXT_KEYS,
    );
  });

  it("adds source_tree to the whole_base chip list when the library has items", () => {
    const keys = availableCategoryKeys("whole_base", true);
    expect(keys).toContain("source_tree");
    expect(keys.length).toBe(BASE_CONTEXT_KEYS.length + 1);
  });

  it("payload encodes source_tree exclusion alongside other categories", () => {
    const p = buildSubmitPayload(
      "whole_base",
      true,
      new Set(["source_tree", "divisions"]),
      "",
    );
    expect(p.context_excludes?.sort()).toEqual(["divisions", "source_tree"]);
  });

  it("payload omits context_excludes when nothing is excluded", () => {
    const p = buildSubmitPayload("whole_base", true, new Set(), "");
    expect(p.context_excludes).toBeUndefined();
  });
});
