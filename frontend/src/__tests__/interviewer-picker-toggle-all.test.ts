// @vitest-environment jsdom
//
// HRP-386/387 follow-up: the Interviewer(s) picker's select-all acts on the
// rows a search left visible, not on the whole roster — so it must add
// only the visible ones and, when they are all already picked, drop only
// those and keep every selection the filter is hiding.

import { describe, expect, it } from "vitest";

import { toggleAllIds } from "@/components/recruitment/interviewer-picker";

describe("toggleAllIds", () => {
  it("adds the visible rows to what is already selected, without duplicates", () => {
    expect(toggleAllIds(["a", "hidden"], ["a", "b", "c"])).toEqual([
      "a",
      "hidden",
      "b",
      "c",
    ]);
  });

  it("drops only the visible rows once they are all selected", () => {
    expect(toggleAllIds(["a", "b", "hidden"], ["a", "b"])).toEqual(["hidden"]);
  });

  it("treats a partially selected filter as select, not clear", () => {
    expect(toggleAllIds(["a"], ["a", "b"])).toEqual(["a", "b"]);
  });

  it("leaves the selection alone when nothing is visible", () => {
    expect(toggleAllIds(["a"], [])).toEqual(["a"]);
  });
});
