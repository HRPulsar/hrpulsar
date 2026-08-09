// Shape posted to POST /v1/question-sets/{id}/questions.
// Shared by the custom-question dialog and the competency-indicator
// dialog (HRP-485) so both agree with the backend QuestionCreate2.
import type { QuestionGoal, QuestionPriority } from "@/lib/question-enums";

export interface NewQuestionPayload {
  text: string;
  goal: QuestionGoal;
  priority: QuestionPriority;
  // Either a UUID or an AI-profile slug — the backend folds both onto
  // the same stable competence UUID (HRP-503).
  competence_id: string | null;
  expected_answer_indicators: string[];
  follow_ups: string[];
  rationale: string | null;
  source: "manual" | "from_competency_indicator";
  resume_anchor_jsonb?: { quote: string; section: string | null } | null;
}
