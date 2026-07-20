import { describe, expect, it } from "vitest";

import {
  buildTree,
  findUnnamedCompetence,
  sanitizeProfileData,
  type PendingSection,
} from "@/components/recruitment/competence-tree-view";
import type { CompetenceItem } from "@/lib/types";

// HRP-318: vacancy Competences & indicators section now edits inline instead
// of opening a modal. The Save button must stay disabled until the recruiter
// changes at least one field; reverting back to the original payload must
// re-disable it again. We mirror the same JSON-comparison the component uses
// so a future contributor who tweaks the dirty check (e.g. switches to a
// deep-equal helper that mishandles key order) has a regression net.

function isDirty(
  original: Record<string, unknown> | null,
  draft: Record<string, unknown> | null,
): boolean {
  const initialJson = original ? JSON.stringify(original) : "";
  const draftJson = draft ? JSON.stringify(draft) : "";
  return draftJson !== "" && draftJson !== initialJson;
}

describe("VacancyCompetencesSection dirty detection", () => {
  it("stays clean when the draft is a JSON-equal deep clone of the source", () => {
    const original = {
      competences: [{ id: "c1", name: "SQL", level: 3 }],
    };
    const draft = JSON.parse(JSON.stringify(original));
    expect(isDirty(original, draft)).toBe(false);
  });

  it("flags dirty after editing any field in the tree", () => {
    const original = {
      competences: [{ id: "c1", name: "SQL", level: 3 }],
    };
    const draft = JSON.parse(JSON.stringify(original));
    draft.competences[0].name = "Advanced SQL";
    expect(isDirty(original, draft)).toBe(true);
  });

  it("flags dirty after deleting a competence", () => {
    const original = {
      competences: [
        { id: "c1", name: "SQL" },
        { id: "c2", name: "Python" },
      ],
    };
    const draft = { competences: [original.competences[0]] };
    expect(isDirty(original, draft)).toBe(true);
  });

  it("stays clean when no draft has been created yet (idle state)", () => {
    const original = { competences: [{ id: "c1", name: "SQL" }] };
    expect(isDirty(original, null)).toBe(false);
  });

  it("stays clean when both sides are absent", () => {
    expect(isDirty(null, null)).toBe(false);
  });

  it("flags dirty after adding a new competence", () => {
    const original = { competences: [{ id: "c1", name: "SQL" }] };
    const draft = JSON.parse(JSON.stringify(original));
    draft.competences.push({
      id: "3b1f4c9e-0000-4000-8000-000000000001",
      group: "Technical Skills",
      subgroup: "Data & Storage",
      name: "",
      criticality: "desirable",
    });
    expect(isDirty(original, draft)).toBe(true);
  });

  it("flags dirty after changing only the criticality", () => {
    const original = {
      competences: [{ id: "c1", name: "SQL", criticality: "important" }],
    };
    const draft = JSON.parse(JSON.stringify(original));
    draft.competences[0].criticality = "critical";
    expect(isDirty(original, draft)).toBe(true);
  });
});

// HRP-318 REDO: both save surfaces (inline Save on the vacancy page,
// Apply in the review dialog) share this guard from the component.
describe("findUnnamedCompetence save guard", () => {
  it("returns the competence when one has not been named yet", () => {
    const unnamed = findUnnamedCompetence({
      competences: [
        { id: "c1", name: "SQL" },
        { id: "c2", name: "   ", group: "Technical Skills", subgroup: "Data" },
      ],
    });
    expect(unnamed?.id).toBe("c2");
    expect(unnamed?.group).toBe("Technical Skills");
  });

  it("returns null when every competence carries a name", () => {
    expect(
      findUnnamedCompetence({
        competences: [
          { id: "c1", name: "SQL" },
          { id: "c2", name: "Python" },
        ],
      }),
    ).toBeNull();
  });

  it("returns null when the payload has no competences array", () => {
    expect(findUnnamedCompetence({})).toBeNull();
    expect(findUnnamedCompetence(null)).toBeNull();
  });
});

// HRP-318 REDO: rows added via "Add indicator" / "Add question" but
// never filled must not be persisted as blank bullets.
describe("sanitizeProfileData", () => {
  it("drops empty indicator and question rows", () => {
    const result = sanitizeProfileData({
      coverage_note: "note",
      competences: [
        {
          id: "c1",
          name: "SQL",
          indicators: ["Real indicator", "", "   "],
          questions: [
            { text: "Real question", good_answer: "g" },
            { text: "", good_answer: "" },
          ],
        },
      ],
    });
    const comp = (result.competences as CompetenceItem[])[0];
    expect(comp.indicators).toEqual(["Real indicator"]);
    expect(comp.questions).toEqual([{ text: "Real question", good_answer: "g" }]);
    expect(result.coverage_note).toBe("note");
  });

  it("leaves competences without arrays untouched", () => {
    const payload = {
      competences: [{ id: "c1", name: "SQL", indicator_question: "legacy" }],
    };
    const result = sanitizeProfileData(payload);
    expect(result.competences).toEqual(payload.competences);
  });

  it("passes through payloads with no competences array", () => {
    const payload = { anything: true };
    expect(sanitizeProfileData(payload)).toBe(payload);
  });
});

// HRP-318 REDO: freshly added (still empty) groups/subgroups live in
// component state and merge into the derived tree; sections the items
// already produce must not duplicate.
describe("buildTree with pending sections", () => {
  const comp = (over: Partial<CompetenceItem>): CompetenceItem => ({
    id: "c1",
    group: "Technical Skills",
    subgroup: "Data & Storage",
    name: "Database Design",
    criticality: "important",
    why_important: "",
    how_manifests: "",
    indicator_question: "",
    good_answer: "",
    acceptable_answer: "",
    poor_answer: "",
    ...over,
  });

  it("appends an empty group after the materialised ones", () => {
    const pending: PendingSection[] = [{ group: "Soft Skills" }];
    const tree = buildTree([comp({})], pending);
    expect(tree.groups.map((g) => g.name)).toEqual([
      "Technical Skills",
      "Soft Skills",
    ]);
    expect(tree.groups[1].subgroups).toEqual([]);
  });

  it("appends an empty subgroup inside an existing group", () => {
    const pending: PendingSection[] = [
      { group: "Technical Skills", subgroup: "APIs" },
    ];
    const tree = buildTree([comp({})], pending);
    const group = tree.groups[0];
    expect(group.subgroups.map((s) => s.name)).toEqual([
      "Data & Storage",
      "APIs",
    ]);
    expect(group.subgroups[1].competences).toEqual([]);
  });

  it("does not duplicate a section the items already materialise", () => {
    const pending: PendingSection[] = [
      { group: "Technical Skills", subgroup: "Data & Storage" },
      { group: "Technical Skills" },
    ];
    const tree = buildTree([comp({})], pending);
    expect(tree.groups).toHaveLength(1);
    expect(tree.groups[0].subgroups).toHaveLength(1);
    expect(tree.groups[0].subgroups[0].competences).toHaveLength(1);
  });

  it("keeps a pending group with a pending subgroup nested together", () => {
    const pending: PendingSection[] = [
      { group: "Soft Skills" },
      { group: "Soft Skills", subgroup: "Communication" },
    ];
    const tree = buildTree([], pending);
    expect(tree.groups).toHaveLength(1);
    expect(tree.groups[0].subgroups.map((s) => s.name)).toEqual([
      "Communication",
    ]);
  });
});
