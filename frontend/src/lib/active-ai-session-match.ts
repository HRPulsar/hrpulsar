import type { ActiveAiSession } from "@/hooks/use-active-ai-sessions";

/**
 * HRP-33: pick the first matrix session whose `target_id` matches the given
 * specialization id. Used by both `/company/specializations` (highlight the
 * spec row) and `/company/positions` (highlight every position attached to
 * that specialization). Returns `null` when no matching session is in the
 * active list — callers fall back to the plain row.
 *
 * "Own" sessions win over "other" ones so the badge tooltip can name the
 * caller's own work first; among same-kind matches we keep the first one
 * we encountered (the hook already merges own then others).
 */
export function findMatrixSessionForSpec(
  sessions: ActiveAiSession[],
  specializationId: string | null | undefined,
): ActiveAiSession | null {
  if (!specializationId) return null;
  let firstOther: ActiveAiSession | null = null;
  for (const s of sessions) {
    if (s.scope !== "specialization_matrix") continue;
    if (s.target_id !== specializationId) continue;
    if (s.kind === "own") return s;
    if (firstOther === null) firstOther = s;
  }
  return firstOther;
}
