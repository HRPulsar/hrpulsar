// HRP-1049: the default assessment type of the create dialog asks the same
// line-manager question as the server's manager participant - the head of
// one's division, else the nearest assigned head above, never oneself.
import { describe, expect, it } from "vitest";

import { hasLineManager, type DivisionChain } from "@/lib/line-manager";

const chain = (rows: [string, string | null, string | null][]): DivisionChain =>
  new Map(rows.map(([id, managerId, parentId]) => [id, { managerId, parentId }]));

// Root (boss) > Child (head) > Leaf (Not assigned)
const org = chain([
  ["root", "boss", null],
  ["child", "head", "root"],
  ["leaf", null, "child"],
]);

describe("hasLineManager", () => {
  it("a head under a managed parent has one (default 180)", () => {
    expect(hasLineManager("head", "child", org)).toBe(true);
  });

  it("an empty seat passes the question up", () => {
    expect(hasLineManager("worker", "leaf", org)).toBe(true);
  });

  it("nobody up to the root, or no division, means none (default self)", () => {
    expect(hasLineManager("boss", "root", org)).toBe(false);
    expect(hasLineManager("loner", null, org)).toBe(false);
  });

  it("a cyclic hierarchy ends", () => {
    const loop = chain([
      ["a", "me", "b"],
      ["b", null, "a"],
    ]);
    expect(hasLineManager("me", "a", loop)).toBe(false);
  });
});
