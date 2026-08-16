import { api } from "@/lib/api";

export type FeedbackRating = "up" | "down";

export interface FeedbackPayload {
  rating?: FeedbackRating | null;
  message?: string | null;
  /** Demo popup only — "was everything clear?" (HRP-587). */
  clarity?: "yes" | "no" | null;
  /** Demo popup only — optional address for a follow-up. */
  contact_email?: string | null;
  source?: "platform" | "demo";
}

/** POST /api/feedback — user rating / comment, fanned out to the team's
 * chat channel by the enterprise handler (HRP-586, HRP-587). */
export async function submitFeedback(payload: FeedbackPayload): Promise<void> {
  await api.post<void>("/feedback", payload);
}
