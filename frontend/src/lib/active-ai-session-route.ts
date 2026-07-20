import type {
  CompetenceGenerationSession,
  SessionScope,
  SessionStatus,
} from "./api/competence-generation";

/**
 * HRP-33: shape the backend ships on a 409 from
 * `POST /competence-generation/sessions[/specialization-matrix-sessions]`
 * so the UI can route the user to wherever their in-flight session lives,
 * instead of stranding them on a dead "active session already exists"
 * toast with no link to the actual review page.
 */
export interface ActiveSessionRef {
  id: string;
  scope: SessionScope;
  target_id: string | null;
  status: SessionStatus;
  /** Set when the session was launched from a Position page so the matrix
   * folds into a group named after the position; tells the UI to land back
   * on the position rather than the underlying specialization. */
  position_id?: string | null;
}

interface ActiveSessionConflictDetail {
  error_code: "active_session_exists";
  message: string;
  session?: ActiveSessionRef;
}

export function isActiveSessionConflict(
  detail: unknown,
): detail is ActiveSessionConflictDetail {
  if (!detail || typeof detail !== "object") return false;
  const obj = detail as Record<string, unknown>;
  return obj.error_code === "active_session_exists";
}

/**
 * Map a live session to the page that owns its review UI. Used by both
 * the global banner (clickable link) and the AI Generate button's
 * 409-handler (auto-redirect on conflict).
 *
 * Routing matrix:
 * - `specialization_matrix` always lands on the specialization AI-generate
 *   page (`/company/specializations/<spec>/ai-generate?session=<id>`),
 *   because the matrix brief, progress UI and review modal all live there.
 *   When the session was launched from a Position page we add
 *   `&position=<pos>` so the page surfaces a banner and returns the user to
 *   the position after Apply.
 * - `whole_base` / `group` / `competence_indicators` → `/competences`,
 *   which renders the global drawer keyed on `?session=<id>`.
 */
export function activeSessionRoute(
  session:
    | ActiveSessionRef
    | Pick<
        CompetenceGenerationSession,
        "id" | "scope" | "target_id" | "status" | "params"
      >,
): string {
  const positionId =
    "params" in session
      ? (session.params?.position_id ?? null)
      : (session.position_id ?? null);

  if (session.scope === "specialization_matrix" && session.target_id) {
    const base = `/company/specializations/${session.target_id}/ai-generate?session=${session.id}`;
    return positionId ? `${base}&position=${positionId}` : base;
  }
  return `/competences?session=${session.id}`;
}
