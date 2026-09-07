// HRP-672: `positions.source` carries three values — `manual`, `ai_draft`
// and `ai_approved` (backend/app/modules/position/models.py; the draft is
// written by app/modules/ai/service.py on generation, and approving it
// rewrites the row to `ai_approved`).
//
// The catalogue table splits drafts into their own section, so it only ever
// renders the other two and could get away with spelling the relation out
// inline. The detail page has no such filter, and did: the two screens then
// disagreed on `ai_draft` — one calling it Manual, the other AI. Only the
// relation lives here; the wording is in the `company` namespace. A code
// outside the three is shown as it is rather than dressed up as AI.
export function positionSourceLabel(
  t: (key: string) => string,
  source: string,
): string {
  switch (source) {
    case "manual":
      return t("sourceManual");
    case "ai_draft":
    case "ai_approved":
      return t("sourceAi");
    default:
      return source;
  }
}
