// HRP-372: pure ordering/numbering helpers for the Manager assessments
// round tabs. They live outside the section component so the contract can
// be pinned by a plain unit test without mounting React.

export type ManagerRoundType = "pre_interview" | "interview" | "final";

export interface SortableRound {
  type: ManagerRoundType;
  round_number: number | null;
}

/** Position of a round type in the tab strip. */
const TYPE_RANK: Record<ManagerRoundType, number> = {
  pre_interview: 0,
  interview: 1,
  final: 2,
};

/**
 * Order rounds as `[Pre-interview] [Interview 1..N] [Final]`.
 *
 * The API returns rows in insertion order, which is only accidentally the
 * hiring order: a `Pre-interview` added after `Interview 2`, or a `Final`
 * created before the last interview, used to leave the tabs in a sequence
 * that reads as random to the recruiter. Sorting is total — type rank,
 * then the interview number, then the id — so the same set of rounds
 * always renders in the same order regardless of how it was assembled.
 */
export function sortRounds<T extends SortableRound & { id?: string }>(
  rounds: readonly T[],
): T[] {
  return [...rounds].sort((a, b) => {
    const rank = (TYPE_RANK[a.type] ?? 99) - (TYPE_RANK[b.type] ?? 99);
    if (rank !== 0) return rank;
    // Only `interview` carries a number; the other types are unique per
    // candidate-vacancy so their nulls never have to be tie-broken here.
    const numDiff = (a.round_number ?? 0) - (b.round_number ?? 0);
    if (numDiff !== 0) return numDiff;
    return (a.id ?? "").localeCompare(b.id ?? "");
  });
}

/**
 * Number the next `+ New round` would create.
 *
 * Aligned with the highest existing interview `round_number` — never
 * `rounds.length`, because `pre_interview` and `final` must not count.
 */
export function nextInterviewNumber(rounds: readonly SortableRound[]): number {
  const highest = rounds
    .filter((r) => r.type === "interview" && r.round_number !== null)
    .reduce((acc, r) => Math.max(acc, r.round_number ?? 0), 0);
  return highest + 1;
}

/** One cell of the tab strip: an existing round, or the slot where a
 * missing `pre_interview` / `final` would sit. */
export type RoundSlot<T> =
  | { kind: "round"; round: T }
  | { kind: "placeholder"; type: "pre_interview" | "final" };

/**
 * Build the tab strip: `[Pre-interview | + Pre-interview] [Interview 1..N]
 * [Final | + Final]`.
 *
 * HRP-372 REDO: the two "create this round" buttons used to hang after
 * `+ New round`, so the strip changed shape depending on which rounds
 * existed. Their slot is now fixed — a missing Pre-interview always reads
 * first, a missing Final always last — and the strip a recruiter learns on
 * one candidate is the strip they get on the next.
 *
 * A placeholder shows whenever its round is missing — including on an
 * empty section, so the strip has one shape everywhere.
 */
export function roundStrip<T extends SortableRound & { id?: string }>(
  rounds: readonly T[],
): RoundSlot<T>[] {
  const sorted = sortRounds(rounds);
  const slots: RoundSlot<T>[] = [];
  const pre = sorted.filter((r) => r.type === "pre_interview");
  const interviews = sorted.filter((r) => r.type === "interview");
  const final = sorted.filter((r) => r.type === "final");

  if (pre.length > 0) {
    for (const r of pre) slots.push({ kind: "round", round: r });
  } else {
    slots.push({ kind: "placeholder", type: "pre_interview" });
  }
  for (const r of interviews) slots.push({ kind: "round", round: r });
  if (final.length > 0) {
    for (const r of final) slots.push({ kind: "round", round: r });
  } else {
    slots.push({ kind: "placeholder", type: "final" });
  }
  return slots;
}

/** HRP-727: the round's tab label, shared with the Manager score tooltips
 * on the candidate page and the vacancy candidates table — the tooltip has
 * to name the round exactly as the tab strip does. */
export function labelForRound(
  t: (key: string, values?: Record<string, string | number>) => string,
  round: SortableRound,
): string {
  if (round.type === "pre_interview")
    return t("managerAssessmentRoundPreInterview");
  if (round.type === "final") return t("managerAssessmentRoundFinal");
  return t("managerAssessmentRoundInterview", {
    number: round.round_number ?? "?",
  });
}
