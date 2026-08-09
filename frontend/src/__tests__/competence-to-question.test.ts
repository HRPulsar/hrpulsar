// HRP-485 task 3: the competence -> question mapping table.
import { describe, expect, it } from "vitest";
import {
  competenceQuestionTexts,
  competenceToQuestion,
  isUsableCompetence,
} from "@/lib/competence-question";
import type { CompetenceItem } from "@/lib/types";

function competence(over: Partial<CompetenceItem> = {}): CompetenceItem {
  return {
    id: "senior-python-skills",
    group: "Engineering",
    subgroup: "Backend",
    name: "Senior Python skills",
    criticality: "critical",
    why_important: "Owns the payment service",
    how_manifests: "",
    indicator_question: "Legacy single question",
    good_answer: "",
    acceptable_answer: "",
    poor_answer: "",
    indicators: ["Ships without regressions", "Reviews others' code"],
    questions: [
      { text: "Describe a migration you led." },
      { text: "How do you handle rollbacks?" },
      { text: "What does your test pyramid look like?" },
    ],
    ...over,
  };
}

describe("competenceToQuestion", () => {
  it("uses the first interview question as the question text", () => {
    expect(competenceToQuestion(competence()).text).toBe(
      "Describe a migration you led.",
    );
  });

  it("puts the remaining interview questions into follow-ups", () => {
    expect(competenceToQuestion(competence()).follow_ups).toEqual([
      "How do you handle rollbacks?",
      "What does your test pyramid look like?",
    ]);
  });

  it("maps indicators onto expected indicators", () => {
    expect(competenceToQuestion(competence()).expected_answer_indicators).toEqual(
      ["Ships without regressions", "Reviews others' code"],
    );
  });

  it("maps why_important onto the rationale", () => {
    expect(competenceToQuestion(competence()).rationale).toBe(
      "Owns the payment service",
    );
  });

  it.each([
    ["critical", "must_ask"],
    ["important", "should_ask"],
    ["desirable", "nice_to_ask"],
  ] as const)("maps criticality %s onto priority %s", (crit, priority) => {
    expect(competenceToQuestion(competence({ criticality: crit })).priority).toBe(
      priority,
    );
  });

  it("always produces a verify_skill question from a competency indicator", () => {
    const q = competenceToQuestion(competence());
    expect(q.goal).toBe("verify_skill");
    expect(q.source).toBe("from_competency_indicator");
  });

  it("carries the competence id so the question stays linked", () => {
    expect(competenceToQuestion(competence()).competence_id).toBe(
      "senior-python-skills",
    );
  });

  it("falls back to a sane priority for an unknown criticality", () => {
    const odd = competence({
      criticality: "unknown" as CompetenceItem["criticality"],
    });
    expect(competenceToQuestion(odd).priority).toBe("should_ask");
  });
});

describe("competenceQuestionTexts", () => {
  it("prefers the question matrix", () => {
    expect(competenceQuestionTexts(competence())).toHaveLength(3);
  });

  it("falls back to the legacy single question", () => {
    expect(competenceQuestionTexts(competence({ questions: [] }))).toEqual([
      "Legacy single question",
    ]);
  });

  it("ignores blank question texts", () => {
    const c = competence({ questions: [{ text: "  " }, { text: "Real one" }] });
    expect(competenceQuestionTexts(c)).toEqual(["Real one"]);
  });

  it("treats a competence with no question at all as unusable", () => {
    const c = competence({ questions: [], indicator_question: "" });
    expect(competenceQuestionTexts(c)).toEqual([]);
    expect(isUsableCompetence(c)).toBe(false);
  });
});
