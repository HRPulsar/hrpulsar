import { describe, expect, it } from "vitest";
import { seedDivisionExcludesForLinkedOnly } from "@/components/competence-generation/MatrixContextPicker";

describe("seedDivisionExcludesForLinkedOnly", () => {
  it("returns an exclude key for every unlinked division", () => {
    const seed = seedDivisionExcludesForLinkedOnly([
      { id: "a", related: true },
      { id: "b", related: false },
      { id: "c", related: false },
    ]);
    expect(seed.sort()).toEqual(["division:b", "division:c"]);
  });

  it("returns an empty list when every division is linked", () => {
    const seed = seedDivisionExcludesForLinkedOnly([
      { id: "a", related: true },
      { id: "b", related: true },
    ]);
    expect(seed).toEqual([]);
  });

  it("returns every key when nothing is linked", () => {
    const seed = seedDivisionExcludesForLinkedOnly([
      { id: "a", related: false },
      { id: "b", related: false },
    ]);
    expect(seed.sort()).toEqual(["division:a", "division:b"]);
  });

  it("returns an empty list on an empty input — no spurious keys", () => {
    expect(seedDivisionExcludesForLinkedOnly([])).toEqual([]);
  });
});
