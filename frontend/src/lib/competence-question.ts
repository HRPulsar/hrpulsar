// HRP-485 task 3: turning a vacancy-profile competence into a question.
//
// The mapping is fixed by the ticket:
//   criticality Critical/Important/Desirable -> Must/Should/Nice to ask
//   first interview question                 -> question text
//   remaining interview questions            -> follow-ups
//   indicators                               -> expected indicators
//   why_important                            -> why this question
//
// Kept free of React so it can be unit-tested directly.
import { CRITICALITY_TO_PRIORITY, type QuestionPriority } from "./question-enums";
import type { CompetenceItem } from "./types";

export interface CompetenceQuestionPayload {
  text: string;
  goal: "verify_skill";
  priority: QuestionPriority;
  competence_id: string | null;
  expected_answer_indicators: string[];
  follow_ups: string[];
  rationale: string | null;
  source: "from_competency_indicator";
}

/** Interview-question texts of a competence, newest matrix first. */
export function competenceQuestionTexts(c: CompetenceItem): string[] {
  const fromMatrix = (c.questions || [])
    .map((q) => (q.text || "").trim())
    .filter(Boolean);
  if (fromMatrix.length) return fromMatrix;
  // Older profiles only carry the legacy single-question mirror.
  const legacy = (c.indicator_question || "").trim();
  return legacy ? [legacy] : [];
}

/** Competences with no question text at all cannot become a question. */
export function isUsableCompetence(c: CompetenceItem): boolean {
  return competenceQuestionTexts(c).length > 0;
}

export function competenceToQuestion(
  c: CompetenceItem,
): CompetenceQuestionPayload {
  const [first, ...rest] = competenceQuestionTexts(c);
  return {
    text: first,
    goal: "verify_skill",
    priority: CRITICALITY_TO_PRIORITY[c.criticality] || "should_ask",
    // HRP-503: may be a slug on AI profiles; the backend normalizes it.
    competence_id: c.id || null,
    expected_answer_indicators: c.indicators || [],
    follow_ups: rest,
    rationale: c.why_important || null,
    source: "from_competency_indicator",
  };
}
