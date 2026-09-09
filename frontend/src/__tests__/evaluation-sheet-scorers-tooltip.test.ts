import { describe, expect, it } from "vitest";

// HRP-374 REDO: the Round average icon is always there, and its tooltip
// lists one line per evaluator — internal by the initials their avatar
// shows, external by their full name.
import {
  scorersTooltip,
  type CompetenceAggregate,
} from "@/components/recruitment/evaluation-sheet-form";

const t = (key: string, values?: Record<string, string | number>) =>
  key === "evalSheetScorerEntry"
    ? `${values!.name} = ${values!.score}`
    : `disagree:${values!.entries}`;

const aggregate = (over: Partial<CompetenceAggregate>): CompetenceAggregate => ({
  average: 3,
  diverges: false,
  scorers: [],
  ...over,
});

describe("scorersTooltip", () => {
  it("names an internal evaluator by initials and an external one in full", () => {
    const tooltip = scorersTooltip(
      t,
      aggregate({
        scorers: [
          {
            evaluator: "Anna Lebedeva",
            evaluator_type: "internal",
            initials: "AL",
            score: 4,
          },
          {
            evaluator: "Ivan Petrov",
            evaluator_type: "external",
            initials: null,
            score: 1,
          },
        ],
      }),
    );
    expect(tooltip).toBe("AL = 4\nIvan Petrov = 1");
  });

  it("falls back to the full name when an internal evaluator has no initials", () => {
    const tooltip = scorersTooltip(
      t,
      aggregate({
        scorers: [
          { evaluator: "Anna Lebedeva", evaluator_type: "internal", score: 4 },
        ],
      }),
    );
    expect(tooltip).toBe("Anna Lebedeva = 4");
  });

  it("keeps the disagreement header when the panel diverges", () => {
    const tooltip = scorersTooltip(
      t,
      aggregate({
        diverges: true,
        scorers: [
          {
            evaluator: "Anna Lebedeva",
            evaluator_type: "internal",
            initials: "AL",
            score: 4,
          },
          {
            evaluator: "Vika Koptsova",
            evaluator_type: "internal",
            initials: "VK",
            score: 1,
          },
        ],
      }),
    );
    // The header carries the first evaluator; no dangling colon, no blank
    // first line.
    expect(tooltip).toBe("disagree:AL = 4\nVK = 1");
  });
});
