// HRP-822 (QA 22.10): whose figures the analytics hints describe - the scope
// the backend computed them over (`scope` on /analytics/hr-metrics), so a
// hint never promises a wider picture than the numbers under it.

export type HrScope = "workspace" | "subtree" | "own";

const SCOPES: readonly string[] = ["workspace", "subtree", "own"];
const SCOPED_HINTS = new Set(["at_risk", "promoted", "engagement", "time_to_promote"]);

/** The scope a response named; anything else (an older backend, a missing
 *  field) keeps today's company-wide texts. */
export function hrScope(raw: unknown): HrScope {
  return typeof raw === "string" && SCOPES.includes(raw) ? (raw as HrScope) : "workspace";
}

/** Key under `analytics` for a metric's hint at that scope. */
export function hrMetricHintKey(code: string, scope: HrScope): string {
  return scope !== "workspace" && SCOPED_HINTS.has(code)
    ? `hrMetricWhy_${code}_${scope}`
    : `hrMetricWhy_${code}`;
}
