// Single source of truth for the visual identity of skill levels
// (Basic / Intermediate / Advanced / Expert) across the product.
//
// Levels are tenant-defined: a tenant can have any number of them and
// `system_code` / `i18n_key` may be absent. Resolution is:
//   1. `i18n_key` matches a known canonical code → use that bucket.
//   2. Fallback: `sort_index` position (0..n) → progression bucket.
//
// Tints are background-only and muted — HR tooling, not gamification.

export type LevelKey = "basic" | "intermediate" | "advanced" | "expert";

export interface LevelTokens {
  key: LevelKey;
  /** Card background tint when the level is highlighted. */
  bg: string;
  /** Border accent class for the level container. */
  border: string;
  /** Left rail accent (a 2 px column on the left of the level card). */
  rail: string;
  /** Dot indicator color (for inline chips / nav). */
  dot: string;
  /** Text color used on small badges that ride alongside the level. */
  text: string;
  /** Short human label, English; replaced by i18n when present. */
  label: string;
}

export const LEVEL_TOKENS: Record<LevelKey, LevelTokens> = {
  basic: {
    key: "basic",
    bg: "bg-slate-50/60 dark:bg-slate-900/30",
    border: "border-slate-200 dark:border-slate-800",
    rail: "bg-slate-400",
    dot: "bg-slate-400",
    text: "text-slate-700 dark:text-slate-300",
    label: "Basic",
  },
  intermediate: {
    key: "intermediate",
    bg: "bg-amber-50/40 dark:bg-amber-950/20",
    border: "border-amber-200 dark:border-amber-900",
    rail: "bg-amber-400",
    dot: "bg-amber-400",
    text: "text-amber-800 dark:text-amber-200",
    label: "Intermediate",
  },
  advanced: {
    key: "advanced",
    bg: "bg-emerald-50/40 dark:bg-emerald-950/20",
    border: "border-emerald-200 dark:border-emerald-900",
    rail: "bg-emerald-500",
    dot: "bg-emerald-500",
    text: "text-emerald-800 dark:text-emerald-200",
    label: "Advanced",
  },
  expert: {
    key: "expert",
    bg: "bg-indigo-50/40 dark:bg-indigo-950/20",
    border: "border-indigo-200 dark:border-indigo-900",
    rail: "bg-indigo-500",
    dot: "bg-indigo-500",
    text: "text-indigo-800 dark:text-indigo-200",
    label: "Expert",
  },
};

const CANONICAL_FROM_KEY: Record<string, LevelKey> = {
  basic: "basic",
  beginner: "basic",
  novice: "basic",
  intermediate: "intermediate",
  middle: "intermediate",
  advanced: "advanced",
  senior: "advanced",
  proficient: "advanced",
  expert: "expert",
  master: "expert",
  lead: "expert",
};

const PROGRESSION: LevelKey[] = ["basic", "intermediate", "advanced", "expert"];

interface LevelInput {
  i18n_key: string | null;
  sort_index: number;
}

/**
 * Resolve visual tokens for a skill level.
 *
 * `position` is the index of this level within the *ordered* skill level
 * list (0 = lowest). The caller knows the full list, so passing the
 * position lets us assign a sensible progression colour even when the
 * tenant uses 2 or 5 levels — sort_index alone is not enough because
 * tenants can start it from any integer.
 */
export function levelTokens(level: LevelInput, position: number): LevelTokens {
  const key = level.i18n_key?.toLowerCase() ?? null;
  if (key && CANONICAL_FROM_KEY[key]) {
    return LEVEL_TOKENS[CANONICAL_FROM_KEY[key]];
  }
  const bucket =
    PROGRESSION[Math.min(position, PROGRESSION.length - 1)] ?? "basic";
  return LEVEL_TOKENS[bucket];
}
