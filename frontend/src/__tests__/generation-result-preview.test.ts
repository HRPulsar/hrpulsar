import { describe, expect, it } from "vitest";

import type {
  ContextOptions,
  ExistingTreeGroup,
  GeneratedTreePayload,
} from "@/lib/api/competence-generation";

// HRP-114 re-spec: pure-logic guards for the result preview + linked-aware
// context picker. Vitest runs without jsdom, so the components themselves
// are not rendered — we re-implement the same selection / counter rules
// the components rely on and pin them here.

function countExisting(tree: ExistingTreeGroup[]): number {
  let total = 0;
  const walk = (g: ExistingTreeGroup) => {
    total += 1;
    for (const c of g.competences ?? []) {
      total += 1;
      total += (c.indicators ?? []).length;
    }
    for (const child of g.descendants ?? g.children ?? []) walk(child);
  };
  tree.forEach(walk);
  return total;
}

function countNewSuggestions(payload: GeneratedTreePayload): number {
  let total = 0;
  type Group = NonNullable<GeneratedTreePayload["groups"]>[number];
  const walk = (g: Group) => {
    if (!g.snapshot_id) total += 1;
    for (const c of g.competences ?? []) {
      if (!c.snapshot_id) total += 1;
      for (const ind of c.indicators ?? []) {
        if (!ind.snapshot_id) total += 1;
      }
    }
    for (const child of g.children ?? []) walk(child);
  };
  (payload.groups ?? []).forEach(walk);
  for (const ind of payload.indicators ?? []) {
    if (!ind.snapshot_id) total += 1;
  }
  return total;
}

function seedExcludesFromLinkedFlags(
  options: Pick<ContextOptions, "specializations" | "divisions">,
  initial: Set<string> = new Set(),
): Set<string> {
  const next = new Set(initial);
  for (const s of options.specializations) {
    if (s.is_linked === false) next.add(`specialization:${s.id}`);
  }
  for (const d of options.divisions) {
    if (d.is_linked === false) next.add(`division:${d.id}`);
  }
  return next;
}

describe("countExisting / countNewSuggestions", () => {
  it("walks a snapshot of groups + competences + indicators", () => {
    const tree: ExistingTreeGroup[] = [
      {
        id: "g1",
        title: "Backend",
        competences: [
          {
            id: "c1",
            title: "Python",
            indicators: [
              { id: "i1", title: "async / await" },
              { id: "i2", title: "type hints" },
            ],
          },
        ],
        descendants: [
          {
            id: "g2",
            title: "Databases",
            competences: [{ id: "c2", title: "Postgres" }],
          },
        ],
      },
    ];
    // 2 groups + 2 competences + 2 indicators = 6.
    expect(countExisting(tree)).toBe(6);
  });

  it("treats nodes with snapshot_id as existing (not new)", () => {
    const payload: GeneratedTreePayload = {
      groups: [
        {
          temp_id: "tg1",
          title: "Already there",
          snapshot_id: "g1",
          competences: [
            { temp_id: "tc1", title: "Already there competence", snapshot_id: "c1" },
            { temp_id: "tc2", title: "Brand new" },
          ],
        },
      ],
    };
    // Only the "Brand new" competence counts as new.
    expect(countNewSuggestions(payload)).toBe(1);
  });

  it("flags only-duplicates when nothing fresh comes out of the LLM", () => {
    const payload: GeneratedTreePayload = {
      groups: [
        {
          temp_id: "tg1",
          title: "Already there",
          snapshot_id: "g1",
        },
      ],
    };
    const existing: ExistingTreeGroup[] = [{ id: "g1", title: "Already there" }];
    const newCount = countNewSuggestions(payload);
    const existingCount = countExisting(existing);
    const onlyDuplicates = newCount === 0 && existingCount > 0;
    expect(onlyDuplicates).toBe(true);
  });
});

describe("seedExcludesFromLinkedFlags", () => {
  it("excludes every unlinked spec / division and leaves linked ones in", () => {
    const seeded = seedExcludesFromLinkedFlags({
      specializations: [
        { id: "s1", title: "Backend", is_linked: true },
        { id: "s2", title: "Frontend", is_linked: false },
      ],
      divisions: [
        { id: "d1", name: "Payments", is_linked: true },
        { id: "d2", name: "Marketing", is_linked: false },
      ],
    });
    expect(Array.from(seeded).sort()).toEqual([
      "division:d2",
      "specialization:s2",
    ]);
  });

  it("is a no-op for whole_base scope (no is_linked flag set)", () => {
    const seeded = seedExcludesFromLinkedFlags({
      specializations: [
        { id: "s1", title: "Backend" },
        { id: "s2", title: "Frontend" },
      ],
      divisions: [{ id: "d1", name: "Engineering" }],
    });
    expect(seeded.size).toBe(0);
  });

  it("preserves manually-added excludes when seeding", () => {
    const initial = new Set<string>(["company"]);
    const seeded = seedExcludesFromLinkedFlags(
      {
        specializations: [{ id: "s2", title: "Other", is_linked: false }],
        divisions: [],
      },
      initial,
    );
    expect(seeded.has("company")).toBe(true);
    expect(seeded.has("specialization:s2")).toBe(true);
  });
});
