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
