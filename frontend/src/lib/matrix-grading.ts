// Pure helpers backing the matrix UI: skill-level tint and the
// coverage-gap message. Vitest pins both without rendering the editor tree.

import type { Competence, SkillLevel } from "@/lib/types";

const LEVEL_TINTS = [
  "bg-primary/5",
  "bg-primary/10",
  "bg-primary/15",
  "bg-primary/20",
] as const;

// HRP-157 REDO: distinct hue per level for the single-grade list view.
// Basic / Intermediate / Advanced / Expert (any level beyond expert
// wraps back to the last hue). The palette is muted on purpose —
// HRPulsar is a daily HR tool, not a dashboard, so saturated badge
// colours would fight with the rest of the UI. Order tracks the
// SkillLevel.sort_index, not the title, so non-English titles still
// land on the right hue.
const LEVEL_HUES = [
  "bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700",
  "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900",
  "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-900",
  "bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-950/40 dark:text-violet-300 dark:border-violet-900",
] as const;

export function levelTint(
  levelId: string | null,
  skillLevels: SkillLevel[],
): string | null {
  if (!levelId) return null;
  const sorted = [...skillLevels].sort((a, b) => a.sort_index - b.sort_index);
  const idx = sorted.findIndex((lvl) => lvl.id === levelId);
  if (idx < 0) return null;
  // Cap at /20 so the select text inside the cell stays readable on both
  // light navy primary and the dark-mode flip — darker tints rendered
  // foreground-on-foreground.
  return LEVEL_TINTS[Math.min(idx, LEVEL_TINTS.length - 1)];
}

/**
 * Returns Tailwind classes for a colored level badge — used by the
 * single-grade list view to make Basic / Intermediate / Advanced /
 * Expert visually distinct from a metre away (HRP-157 REDO).
 *
 * Falls back to a neutral chip when the level is unknown or unset; the
 * caller decides whether to render the wrapper at all.
 */
export function levelHueClass(
  levelId: string | null,
  skillLevels: SkillLevel[],
): string {
  if (!levelId) return "bg-muted/30 text-muted-foreground border-border";
  const sorted = [...skillLevels].sort((a, b) => a.sort_index - b.sort_index);
  const idx = sorted.findIndex((lvl) => lvl.id === levelId);
  if (idx < 0) return "bg-muted/30 text-muted-foreground border-border";
  return LEVEL_HUES[Math.min(idx, LEVEL_HUES.length - 1)];
}

// HRP-476: one key per gap combination in the `company` i18n namespace.
// The sentence is not assembled from fragments here — languages order the
// "indicators and development materials" enumeration differently, so each
// variant is a whole translatable string.
const COVERAGE_GAP_KEYS = {
  indicators: "coverageGapIndicators",
  materials: "coverageGapMaterials",
  both: "coverageGapBoth",
} as const;

/** Key in the `company` namespace for a competence row's coverage gap, or
 *  null when everything is in place. Backend rolls indicator / material
 *  coverage into two booleans per competence — we surface the union, not
 *  the per-level breakdown.
 */
function coverageGapKey(
  competence: Pick<Competence, "levels_completion">,
): string | null {
  const c = competence.levels_completion;
  // Backend omits the field on origin competences that have never had a
  // matrix link — treat absence as "no signal yet", not as a gap.
  if (!c) return null;
  if (c.has_uncovered_indicators && c.has_uncovered_materials) {
    return COVERAGE_GAP_KEYS.both;
  }
  if (c.has_uncovered_indicators) return COVERAGE_GAP_KEYS.indicators;
  if (c.has_uncovered_materials) return COVERAGE_GAP_KEYS.materials;
  return null;
}

/** Translated coverage-gap message, or null when the row has no gap.
 *  ``t`` must be bound to the `company` namespace.
 */
export function coverageGapMessage(
  t: (key: string) => string,
  competence: Pick<Competence, "levels_completion">,
): string | null {
  const key = coverageGapKey(competence);
  return key ? t(key) : null;
}
