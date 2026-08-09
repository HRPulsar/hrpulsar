import { Badge } from "@/components/ui/badge";
import { BADGE_COLOR } from "@/lib/badge-tones";
import { cn } from "@/lib/utils";

/**
 * HRP-527: shared rendering rule for a "match percent" value.
 *
 * Thresholds (agreed on the ticket):
 *   >= 75      green
 *   50 .. 74   yellow
 *   < 50       red
 *   null       muted em dash (no result computed / all "Don't know")
 *
 * HRP-528 reuses the same component for the group analytics block, where
 * grade-match chips follow a different rule (highlight the best grade with
 * the brand teal instead of the threshold colours) — hence the `tone` prop.
 */
export type MatchPercentTone = "auto" | "highlight" | "muted";

/** Threshold bucket for a rounded percent. Exported for tests. */
export function matchPercentColor(percent: number): "green" | "yellow" | "red" {
  if (percent >= 75) return "green";
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
  className?: string;
  "data-testid"?: string;
}

export function MatchPercentChip({
  percent,
  tone = "auto",
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
        : BADGE_COLOR[matchPercentColor(value)];

  return (
    <Badge variant="secondary" className={cn(toneClass, className)} data-testid={testId}>
      {value}%
    </Badge>
  );
}
