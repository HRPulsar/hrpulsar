type Translate = (key: string, values?: Record<string, string | number>) => string;

// HRP-1117: a question set's name is stored as the backend wrote it - the
// round it prepares (`_round_label` in recruitment/question_service.py) or a
// default (`_default_set_name`, the sample's "Sample set"). Those are labels,
// not content, so they read in the interface language by their stored value;
// the round wording is the Manager assessments tabs'. A name the backend did
// not write shows as stored.
const FIXED: Record<string, string> = {
  "Pre-interview": "managerAssessmentRoundPreInterview",
  Final: "managerAssessmentRoundFinal",
  "Next round": "questionSetNameNextRound",
  "Regenerated set": "questionSetNameRegenerated",
  "Final round": "questionSetNameFinalRound",
  "Pre-interview set": "questionSetNamePreInterview",
  "Sample set": "questionSetNameSample",
};

export function questionSetName(t: Translate, name: string): string {
  const key = FIXED[name];
  if (key) return t(key);
  const round = /^Interview (\d+)$/.exec(name);
  return round
    ? t("managerAssessmentRoundInterview", { number: Number(round[1]) })
    : name;
}
