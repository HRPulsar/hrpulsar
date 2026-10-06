import { isGap } from "@/lib/employee-issues";

/**
 * HRP-731: an assessment's growth zones and strengths.
 *
 * A row answered entirely with the neutral option has no percent and no
 * verdict, so it lands in neither list (the full table still shows it).
 * Growth zones read worst first, strengths best first (QA 30.09).
 */
export function splitHighlights<T extends { percent: number | null }>(
  rows: T[],
  bar: number,
): { growthZones: T[]; strengths: T[] } {
  const measured = rows.filter((r) => r.percent !== null) as (T & {
    percent: number;
  })[];
  return {
    growthZones: measured
      .filter((r) => isGap(r.percent, bar))
      .sort((a, b) => a.percent - b.percent),
    strengths: measured
      .filter((r) => !isGap(r.percent, bar))
      .sort((a, b) => b.percent - a.percent),
  };
}
