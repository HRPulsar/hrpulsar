import { Badge } from "@/components/ui/badge";
import { BADGE_COLOR } from "@/lib/badge-tones";
import { DEFAULT_PASSING_SCORE, isGap } from "@/lib/employee-issues";
import { cn } from "@/lib/utils";

/**
 * HRP-527: shared rendering rule for a "match percent" value.
 *
 * Thresholds (HRP-731 moved the top one onto the shared gap rule):
 *   above the bar   green
 *   50 .. bar       yellow
 *   < 50            red
 *   null            muted em dash (no result computed / all "Don't know")
 *
 * HRP-528 reuses the same component for the group analytics block, where
 * grade-match chips follow a different rule (highlight the best grade with
 * the brand teal instead of the threshold colours) — hence the `tone` prop.
 */
export type MatchPercentTone = "auto" | "highlight" | "muted";

/** Threshold bucket for a rounded percent. Exported for tests. */
export function matchPercentColor(
  percent: number,
  bar: number = DEFAULT_PASSING_SCORE,
): "green" | "yellow" | "red" {
  // HRP-731: green means "not a gap", so the colour cannot contradict the
  // verdict next to it. The bar itself is a gap, hence 75 is yellow and 76
  // is the first green — every caller here renders a competence percent
  // judged against that same rule.
  if (!isGap(percent, bar)) return "green";
  if (percent >= 50) return "yellow";
  return "red";
}

/** Math-rounded percent (half away from zero), or null when there is no value. */
export function roundPercent(percent: number | null | undefined): number | null {
  if (percent === null || percent === undefined || Number.isNaN(percent)) {
    return null;
  }
  return Math.round(percent);
}

export interface MatchPercentChipProps {
  percent: number | null | undefined;
  /**
   * `auto` (default) picks green/yellow/red by threshold.
   * `highlight` paints the brand teal — used for the best grade match.
   * `muted` is the neutral chip used for non-best grade matches.
   */
  tone?: MatchPercentTone;
  /** The passing score the value is judged against; the tenant default
   *  when the caller has no assessment-specific bar. */
  bar?: number;
  className?: string;
  "data-testid"?: string;
}

export function MatchPercentChip({
  percent,
  tone = "auto",
  bar = DEFAULT_PASSING_SCORE,
  className,
  "data-testid": testId,
}: MatchPercentChipProps) {
  const value = roundPercent(percent);

  if (value === null) {
    return (
      <span
        className={cn("text-sm text-muted-foreground", className)}
        data-testid={testId}
      >
        —
      </span>
    );
  }

  const toneClass =
    tone === "highlight"
      ? "bg-[#0989A5] text-white dark:bg-[#0989A5] dark:text-white"
      : tone === "muted"
        ? BADGE_COLOR.neutral
        : BADGE_COLOR[matchPercentColor(value, bar)];

  return (
    <Badge variant="secondary" className={cn(toneClass, className)} data-testid={testId}>
      {value}%
    </Badge>
  );
}
