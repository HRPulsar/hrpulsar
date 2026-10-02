import { describe, expect, it } from "vitest";

// HRP-374 REDO (11.09): the Round average tooltip lists one line per
// evaluator as "{Full name}: {score}" — full names for colleagues and
// external evaluators alike — headed by "Evaluators disagree" only when
// the panel actually diverges.
import {
  scorersTooltip,
  type CompetenceAggregate,
} from "@/components/recruitment/evaluation-sheet-form";

const t = (key: string, values?: Record<string, string | number>) =>
  key === "evalSheetScorerEntry"
    ? `${values!.name}: ${values!.score}`
    : key === "evalSheetDivergenceAria"
      ? "Evaluators disagree"
      : key;

const aggregate = (over: Partial<CompetenceAggregate>): CompetenceAggregate => ({
  average: 3,
  diverges: false,
  scorers: [],
  ...over,
});

describe("scorersTooltip", () => {
  it("names every evaluator in full, colleague and external alike", () => {
    const tooltip = scorersTooltip(
      t,
      aggregate({
        scorers: [
          { evaluator: "Anna Lebedeva", evaluator_type: "internal", score: 4 },
          { evaluator: "Ivan Petrov", evaluator_type: "external", score: 1 },
        ],
      }),
    );
    expect(tooltip).toBe("Anna Lebedeva: 4\nIvan Petrov: 1");
  });

  it("heads the list with the disagreement line when the panel diverges", () => {
    const tooltip = scorersTooltip(
      t,
      aggregate({
        diverges: true,
        scorers: [
          { evaluator: "Anna Lebedeva", evaluator_type: "internal", score: 4 },
          { evaluator: "Vika Koptsova", evaluator_type: "internal", score: 1 },
        ],
      }),
    );
    expect(tooltip).toBe("Evaluators disagree\nAnna Lebedeva: 4\nVika Koptsova: 1");
  });

  it("shows a lone evaluator without any header", () => {
    const tooltip = scorersTooltip(
      t,
      aggregate({
        scorers: [
          { evaluator: "Anna Lebedeva", evaluator_type: "internal", score: 4 },
        ],
      }),
    );
    expect(tooltip).toBe("Anna Lebedeva: 4");
  });
});
