import { api } from "@/lib/api";

export type FeedbackRating = "up" | "down";

/** What the demo visitor had just done when the card asked (HRP-1158);
 * "timer" for the card shown to those who only browsed. */
export type FeedbackContext =
  | "pdp_created"
  | "pdp_from_assessment"
  | "assessment_created"
  | "decomposition_applied"
  | "hire_need_created"
  | "timer";

export interface FeedbackPayload {
  rating?: FeedbackRating | null;
  message?: string | null;
  /** Demo popup only — "was everything clear?" (HRP-587). */
  clarity?: "yes" | "no" | null;
  /** Demo popup only — optional address for a follow-up. */
  contact_email?: string | null;
  /** Demo popup only — who to ask for, and a phone where the site offers it. */
  contact_name?: string | null;
  contact_phone?: string | null;
  source?: "platform" | "demo";
  /** Demo popup only (HRP-1158) — the value moment, the object it made,
   * and the one-click answer to the card's question about it. */
  context?: FeedbackContext | null;
  context_title?: string | null;
  answer?: "yes" | "partly" | "no" | null;
}

/** POST /api/feedback — user rating / comment, fanned out to the team's
 * chat channel by the enterprise handler (HRP-586, HRP-587). */
export async function submitFeedback(payload: FeedbackPayload): Promise<void> {
  await api.post<void>("/feedback", payload);
}
