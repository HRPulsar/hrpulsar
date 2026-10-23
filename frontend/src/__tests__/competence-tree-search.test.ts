import { describe, expect, it } from "vitest";

import { matchCompetenceTree } from "@/lib/competence-tree-search";
import type { CompetenceGroupTree } from "@/lib/types";

function group(
  id: string,
  title: string,
  competences: string[] = [],
  children: CompetenceGroupTree[] = [],
): CompetenceGroupTree {
  return {
    id,
    title,
    children,
    competences: competences.map((c) => ({ id: c, title: c })),
  } as unknown as CompetenceGroupTree;
}

// Soft skills > Communication > [Public speaking, Listening]; Tech > [Python]
const tree = [
  group("soft", "Soft skills", [], [
    group("comm", "Communication", ["Public speaking", "Listening"]),
  ]),
  group("tech", "Tech", ["Python"]),
];

describe("matchCompetenceTree (HRP-1082)", () => {
  it("shows the whole tree for an empty query", () => {
    expect(matchCompetenceTree(tree, "  ")).toBeNull();
  });

  it("keeps a matching competence and every group above it", () => {
    const m = matchCompetenceTree(tree, "SPEAK")!;
    expect([...m.groups].sort()).toEqual(["comm", "soft"]);
    expect([...m.competences]).toEqual(["Public speaking"]);
  });

  it("keeps everything under a matching group", () => {
    const m = matchCompetenceTree(tree, "soft")!;
    expect([...m.groups].sort()).toEqual(["comm", "soft"]);
    expect([...m.competences].sort()).toEqual(["Listening", "Public speaking"]);
  });

  it("drops branches without a match", () => {
    const m = matchCompetenceTree(tree, "pyth")!;
    expect([...m.groups]).toEqual(["tech"]);
    expect(matchCompetenceTree(tree, "nothing")!.groups.size).toBe(0);
  });
});
