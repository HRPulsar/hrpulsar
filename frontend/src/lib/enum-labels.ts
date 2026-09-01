/**
 * Labels for frontend-owned enum option sets (HRP-653).
 *
 * These enums live in the frontend: the API persists the raw string and
 * has no vocabulary of its own for them, so the wording is purely a
 * presentation concern — same posture as `competences/material-options`.
 *
 * Two rules hold for every resolver here:
 *
 * - the **value** never changes, only the label. Wire codes, `data-testid`
 *   and stored rows stay on the enum code.
 * - a value outside the offered set (a seeded `position_change`, an
 *   imported history, a plan written before an option was retired) keeps
 *   rendering raw instead of disappearing.
 */

function labelFor(
  keys: Record<string, string>,
  t: (key: string) => string,
  value: string | null | undefined,
): string {
  if (!value) return "";
  const key = keys[value];
  return key ? t(key) : value;
}

// --- Employee profile → Events -------------------------------------------

export const EVENT_TYPE_OPTIONS = [
  "hire",
  "promotion",
  "transfer",
  "leave",
  "return",
  "review",
  "training",
  "other",
] as const;

/** Keys live in the `employees` namespace. */
export const EVENT_TYPE_LABEL_KEYS: Record<string, string> = {
  hire: "eventTypeHire",
  promotion: "eventTypePromotion",
  transfer: "eventTypeTransfer",
  leave: "eventTypeLeave",
  return: "eventTypeReturn",
  review: "eventTypeReview",
  training: "eventTypeTraining",
  other: "eventTypeOther",
};

export function eventTypeLabel(
  t: (key: string) => string,
  value: string | null | undefined,
): string {
  return labelFor(EVENT_TYPE_LABEL_KEYS, t, value);
}

// --- Development plan → Add material → Format -----------------------------

/**
 * The formats the plan's "Add material" dialog offers.
 *
 * One of two pick-lists over the same column: the competence card offers
 * `MATERIAL_FORMATS`, this offers the handful worth adding by hand, and
 * both label through `MATERIAL_FORMAT_LABELS` in
 * `competences/material-options`. That split matters because a plan item
 * pulled from a competence's recommended materials copies
 * `Material.format` verbatim (`pdp_service.py`) and arrives carrying any
 * value of the vocabulary — a shorter label map here rendered those raw.
 */
export const MATERIAL_FORMAT_OPTIONS = [
  "course",
  "book",
  "article",
  "video",
  "practice",
] as const;
