// HRP-271 — loose coupling between AI Insights and the parsed-resume
// editor. AI Insights dispatches ``RESUME_EXCERPT_FOCUS_EVENT`` on
// click; the parsed-resume editor listens on ``window`` and reacts
// (expand section + scroll + highlight). A window event keeps the two
// cards on the candidate page independent of each other's mount state
// and avoids threading a callback through the page-level component.
//
// ``candidate_id`` is carried in the detail so a future side-by-side
// candidate comparison view (multiple ParsedResumeEditor instances at
// once) can filter events by candidate without changing the contract.

import type { ResumeExcerpt } from "./recruitment-types";

export const RESUME_EXCERPT_FOCUS_EVENT = "hrp:resume-excerpt-focus";

export interface ResumeExcerptFocusDetail extends ResumeExcerpt {
  candidate_id: string;
}

export function dispatchResumeExcerptFocus(detail: ResumeExcerptFocusDetail): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<ResumeExcerptFocusDetail>(RESUME_EXCERPT_FOCUS_EVENT, {
      detail,
    }),
  );
}
