// HRP-122 REDO #3: REST polling is the source of truth for AI-generation
// session status. WebSocket pushes (compgen.session.updated) remain a
// fast-path but cannot be relied on for delivery — Redis pub/sub on the
// backend is at-most-once, and the client's wsState lags behind silent
// disconnects. Polling runs whenever the session is in an active state,
// regardless of wsState.

export type GenerationSessionStatus =
  | "pending"
  | "running"
  | "ready"
  | "applied"
  | "cancelled"
  | "error";

const ACTIVE_STATUSES: ReadonlySet<GenerationSessionStatus> = new Set([
  "pending",
  "running",
  "ready",
]);

export function shouldPollGenerationSession(
  sessionStatus: GenerationSessionStatus | null,
): boolean {
  if (sessionStatus === null) return false;
  return ACTIVE_STATUSES.has(sessionStatus);
}
