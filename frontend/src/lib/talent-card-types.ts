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

// HRP-716: the board header used to say "6 cards", which told nobody what
// is on the board. These keys carry the per-type wording (ICU plural).
export const TYPE_COUNT_KEYS: Record<string, string> = {
  vacancy: "countVacancies",
  talent: "countTalents",
  project: "countProjects",
};

/**
 * Non-zero card counts per type, in TALENT_CARD_TYPES order — the header
 * renders one plural phrase per entry ("3 vacancies · 1 talent"). An empty
 * result means nothing to break down, and the caller falls back to the
 * plain card count.
 */
export function countCardsByType(
  cards: ReadonlyArray<{ card_type: string }>,
): Array<{ type: string; count: number }> {
  return TALENT_CARD_TYPES.map((type) => ({
    type,
    count: cards.filter((card) => card.card_type === type).length,
  })).filter((entry) => entry.count > 0);
}

// HRP-734 follow-up: the candidates-table badge reads the live `blocked_by`
// verdict, except where the stored status is the fact — an appointment is
// terminal, and the legacy statuses (nominated / rejected / responded, kept
// for rows the HRP-214 migration has not backfilled) carry a decision the
// matcher never made. `matched`, `not_matched` and `pending` are the
// matcher's own words and stay live. Sourcing only `appointed` from the
// store relabelled every legacy row with nothing blocking it as "Matched".
const STORED_STATUS_WINS = new Set([
  "appointed",
  "nominated",
  "rejected",
  "responded",
]);

/** True when the badge shows the stored status instead of the live verdict.
 *  (A null `blocked_by` — the card states no requirements — defers to the
 *  store as well; the caller checks that first, it is what narrows the
 *  type.) */
export function storedCandidateStatusWins(status: string): boolean {
  return STORED_STATUS_WINS.has(status);
}
