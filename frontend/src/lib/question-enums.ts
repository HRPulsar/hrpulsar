// HRP-486: single source of truth for interview-question vocabularies.
//
// The codes mirror the backend literals in
// ``app/modules/recruitment/schemas.py`` (QuestionGoal / QuestionPriority
// / QuestionSource). They are wire values and are never translated —
// every surface renders them through the label maps below, so a user
// never sees a raw code like ``clarify_experience``.
//
// ``question-enums.test.ts`` pins each label key to both message
// catalogs; ``test_question_enum_alignment.py`` pins the codes to the
// backend.

export const QUESTION_GOALS = [
  "verify_skill",
  "clarify_experience",
  "probe_risk",
  "explore_motivation",
  "assess_fit",
] as const;
export type QuestionGoal = (typeof QUESTION_GOALS)[number];

export const QUESTION_PRIORITIES = [
  "must_ask",
  "should_ask",
  "nice_to_ask",
] as const;
export type QuestionPriority = (typeof QUESTION_PRIORITIES)[number];

export const QUESTION_SOURCES = [
  "ai_generated",
  "manual",
  "from_competency_indicator",
  "from_blind_spot",
] as const;
export type QuestionSource = (typeof QUESTION_SOURCES)[number];

// Keys resolve inside the ``recruitment`` namespace.
export const GOAL_LABEL_KEYS: Record<QuestionGoal, string> = {
  verify_skill: "questionSetsGoalVerifySkill",
  clarify_experience: "questionSetsGoalClarifyExperience",
  probe_risk: "questionSetsGoalProbeRisk",
  explore_motivation: "questionSetsGoalExploreMotivation",
  assess_fit: "questionSetsGoalAssessFit",
};

export const PRIORITY_LABEL_KEYS: Record<QuestionPriority, string> = {
  must_ask: "questionSetsPriorityMustAsk",
  should_ask: "questionSetsPriorityShouldAsk",
  nice_to_ask: "questionSetsPriorityNiceToAsk",
};

export const SOURCE_LABEL_KEYS: Record<QuestionSource, string> = {
  ai_generated: "questionSetsSourceAi",
  manual: "questionSetsSourceManual",
  from_competency_indicator: "questionSetsSourceIndicator",
  from_blind_spot: "questionSetsSourceBlindSpot",
};

/**
 * HRP-485: vacancy-profile criticality maps onto question priority when
 * a question is created from a competency indicator.
 */
export const CRITICALITY_TO_PRIORITY: Record<string, QuestionPriority> = {
  critical: "must_ask",
  important: "should_ask",
  desirable: "nice_to_ask",
};
