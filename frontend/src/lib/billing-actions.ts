import type { SessionScope } from "@/lib/api/competence-generation";

/**
 * Billing action keys for AI generation sessions.
 *
 * Mirror of `backend/app/modules/ai_competence_generation/billing_actions.py`
 * — the keys the backend prechecks and consumes. The UI must quote the
 * price of the action it is about to trigger; before HRP-509 the confirm
 * dialog quoted the legacy `ai.generate_*` API prices instead, so starting
 * a whole-base generation advertised 75 credits and charged 200.
 *
 * `backend/tests/unit/test_hrp509_billing_action_parity.py` pins these
 * maps against the Python functions.
 */
export const START_ACTION_BY_SCOPE: Record<SessionScope, string> = {
  whole_base: "ai_competence_generation.start_whole_base",
  group: "ai_competence_generation.start_group",
  competence_indicators: "ai_competence_generation.start_competence_indicators",
  specialization_matrix: "ai_specialization_matrix.start",
};

export const REFINE_ACTION_BY_SCOPE: Record<SessionScope, string> = {
  whole_base: "ai_competence_generation.refine",
  group: "ai_competence_generation.refine",
  competence_indicators: "ai_competence_generation.refine",
  specialization_matrix: "ai_specialization_matrix.refine",
};

export function startActionForScope(scope: SessionScope): string {
  return START_ACTION_BY_SCOPE[scope];
}

export function refineActionForScope(scope: SessionScope): string {
  return REFINE_ACTION_BY_SCOPE[scope];
}

/** Minimal shape needed to price a re-run — the session read model satisfies it. */
export interface PricedSession {
  scope: SessionScope;
  params?: { billing_action?: string | null } | null;
}

/**
 * The action a re-run of `session` will be charged.
 *
 * Mirrors `regenerate_session` in the router: the parent's pinned
 * `billing_action`, falling back to the start action for its scope. A
 * session produced by Refine is pinned to the refine action, so quoting
 * the start price there overstated the charge several-fold (review #5).
 */
export function regenerateActionForSession(
  session: PricedSession | null | undefined,
): string | null {
  if (!session) return null;
  return session.params?.billing_action || startActionForScope(session.scope);
}
