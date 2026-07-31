// HRP-287: pins the Competence Type picker filter.
// Hide inactive types from the dropdown, but keep the currently
// selected one so edit mode does not silently lose the previously
// saved value when its type was deactivated after the fact.

import { describe, expect, it } from "vitest";
import { visibleCompetenceTypes } from "@/lib/competence-type-filter";
import type { DictionaryItem } from "@/lib/types";

function ct(
  id: string,
  title: string,
  is_active: boolean,
): DictionaryItem {
  return {
    id,
    type: "competence_type",
    title,
    description: null,
    i18n_key: null,
    is_active,
    sort_index: 0,
    tenant_id: null,
    metadata: null,
    created_at: "2026-01-01T00:00:00Z",
  };
}

describe("visibleCompetenceTypes", () => {
  const active1 = ct("a1", "Hard", true);
  const active2 = ct("a2", "Soft", true);
  const inactive1 = ct("i1", "Legacy", false);

  it("returns only active types when nothing is selected", () => {
    const out = visibleCompetenceTypes([active1, active2, inactive1], "");
    expect(out.map((c) => c.id)).toEqual(["a1", "a2"]);
  });

  it("returns only active types when selected id is empty", () => {
    expect(
      visibleCompetenceTypes([active1, inactive1], null).map((c) => c.id),
    ).toEqual(["a1"]);
  });

  it("keeps active list as-is when the selected id is itself active", () => {
    const out = visibleCompetenceTypes([active1, active2, inactive1], "a1");
    expect(out.map((c) => c.id)).toEqual(["a1", "a2"]);
  });

  it("appends the selected inactive type so edit mode never drops the saved value", () => {
    const out = visibleCompetenceTypes([active1, active2, inactive1], "i1");
    expect(out.map((c) => c.id)).toEqual(["a1", "a2", "i1"]);
  });

  it("ignores an unknown selected id (already deleted)", () => {
    const out = visibleCompetenceTypes([active1, active2, inactive1], "ghost");
    expect(out.map((c) => c.id)).toEqual(["a1", "a2"]);
  });
});
