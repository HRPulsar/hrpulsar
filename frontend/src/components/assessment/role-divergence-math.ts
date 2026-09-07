// HRP-715: the two pure bits of the self-vs-manager block, kept out of the
// component so they can be tested without mounting anything.

/** Spec order (mirrors `role_order` in the backend's detailed results). */
const ROLE_ORDER = ["self", "manager", "peer", "subordinate"];

export function orderRoles(roles: string[]): string[] {
  return [...roles].sort((a, b) => {
    const ai = ROLE_ORDER.indexOf(a);
    const bi = ROLE_ORDER.indexOf(b);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi) || a.localeCompare(b);
  });
}

/**
 * Self minus the reference side, in percentage points.
 *
 * The manager is the reference the ticket is about; a 360° without a
 * completed manager falls back to the average of whoever else answered.
 * Null when there is nothing to compare (no self, or self alone).
 */
export function selfDelta(percents: Record<string, number>): number | null {
  if (!("self" in percents)) return null;
  const others = Object.keys(percents).filter((role) => role !== "self");
  if (others.length === 0) return null;
  const reference = others.includes("manager")
    ? percents.manager
    : others.reduce((sum, role) => sum + percents[role], 0) / others.length;
  return Math.round(percents.self - reference);
}

/**
 * Whether the headline can be called a manager comparison: every competence
 * that contributed a delta had a manager value. One row on the peer fallback
 * and the number is partly built from peers.
 */
export function comparedToManager(perCompetence: Record<string, number>[]): boolean {
  return perCompetence
    .filter((percents) => selfDelta(percents) !== null)
    .every((percents) => "manager" in percents);
}

/**
 * The headline gap: the mean of the per-competence deltas.
 *
 * Not the delta between the per-role overall averages — those average each
 * role over only the competences it answered, so one side skipping a
 * competence ("Don't know") shifts the headline against competences the two
 * sides actually agree on.
 */
export function overallDelta(perCompetence: Record<string, number>[]): number | null {
  const deltas = perCompetence
    .map(selfDelta)
    .filter((delta): delta is number => delta !== null);
  if (deltas.length === 0) return null;
  return Math.round(deltas.reduce((sum, d) => sum + d, 0) / deltas.length);
}
