// HRP-664: the three Talent Market card types differ by intent only. The
// backend stores `card_type` as a plain label and treats all three
// identically — the matcher, the statuses and the appoint flow never read
// it, and the only code that branches on it is the list filter in
// `card_service.search_cards`. Nothing in the UI said what the words mean,
// so the wording lives here once and is surfaced where a person meets the
// type: choosing it in the create dialog, and reading it off a card.
export const TALENT_CARD_TYPES = ["vacancy", "talent", "project"] as const;

// HRP-476: the wording lives in the `talentMarket` i18n namespace — these
// maps only own the code → key relation (same shape as
// `components/employees/employee-status.ts`).
export const TYPE_KEYS: Record<string, string> = {
  vacancy: "typeVacancy",
  talent: "typeTalent",
  project: "typeProject",
};

export const TYPE_HINT_KEYS: Record<string, string> = {
  vacancy: "typeVacancyHint",
  talent: "typeTalentHint",
  project: "typeProjectHint",
};
