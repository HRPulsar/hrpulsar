import type { LucideIcon } from "lucide-react";
import { BookOpen, Hammer, MessageSquare } from "lucide-react";

// HRP-476: the option sets are owned by the frontend (the backend persists the
// raw `value`), so the wording is a presentation concern. Each option carries
// a `labelKey` into the `competences` i18n namespace; anything the API sends
// outside the set falls back to the raw value — the pre-i18n rendering.

export type MaterialFormatOption = {
  value: string;
  labelKey: string;
};

export type MaterialTypeOption = {
  value: string;
  labelKey: string;
  icon: LucideIcon;
};

/**
 * Every value the shared `format` column can carry, with its label.
 *
 * The vocabulary and the pick-lists are separate concerns (HRP-653): the
 * competence card and the development plan offer different subsets of the
 * same column, and `PDPItemMaterial.format` is copied verbatim from
 * `Material.format`, so both screens have to be able to label a value
 * neither of them offers.
 */
export const MATERIAL_FORMAT_LABELS: MaterialFormatOption[] = [
  { value: "documentation", labelKey: "materialFormatDocumentation" },
  { value: "video", labelKey: "materialFormatVideo" },
  { value: "article", labelKey: "materialFormatArticle" },
  { value: "webinar", labelKey: "materialFormatWebinar" },
  { value: "book", labelKey: "materialFormatBook" },
  { value: "course", labelKey: "materialFormatCourse" },
  { value: "task", labelKey: "materialFormatTask" },
  { value: "project", labelKey: "materialFormatProject" },
  { value: "masterclass", labelKey: "materialFormatMasterclass" },
  { value: "trainer", labelKey: "materialFormatTrainer" },
  { value: "conversation", labelKey: "materialFormatConversation" },
  { value: "interview", labelKey: "materialFormatInterview" },
  { value: "mentorship", labelKey: "materialFormatMentorship" },
  { value: "training", labelKey: "materialFormatTraining" },
  { value: "exercise", labelKey: "materialFormatExercise" },
  // Offered by the development plan's dialog, not by the competence
  // card — labelled here, kept out of MATERIAL_FORMATS below.
  { value: "practice", labelKey: "materialFormatPractice" },
  { value: "simulator", labelKey: "materialFormatSimulator" },
  { value: "other", labelKey: "materialFormatOther" },
];

/**
 * The formats the competence card offers. Unchanged set — the plan's own
 * shorter list lives in `lib/enum-labels`.
 */
export const MATERIAL_FORMATS: MaterialFormatOption[] =
  MATERIAL_FORMAT_LABELS.filter((f) => f.value !== "practice");

export const MATERIAL_TYPES: MaterialTypeOption[] = [
  { value: "theoretical", labelKey: "materialTypeTheoretical", icon: BookOpen },
  { value: "practical", labelKey: "materialTypePractical", icon: Hammer },
  { value: "feedback", labelKey: "materialTypeFeedback", icon: MessageSquare },
];

export const DEFAULT_MATERIAL_TYPE = "theoretical";

/** i18n key for a known format value, or `null` for anything unexpected. */
export function materialFormatKey(
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  return (
    MATERIAL_FORMAT_LABELS.find((f) => f.value === value)?.labelKey ?? null
  );
}

/** Translated format label with a raw-value fallback for unknown formats. */
export function materialFormatLabel(
  t: (key: string) => string,
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  const key = materialFormatKey(value);
  return key ? t(key) : value;
}

export function materialTypeOption(
  value: string | null | undefined,
): MaterialTypeOption | null {
  if (!value) return null;
  return MATERIAL_TYPES.find((t) => t.value === value) ?? null;
}
