// HRP-822 (QA 22.10): the analytics hints follow the scope the backend
// computed the figures over. A response without it (an older backend) keeps
// today's company-wide texts rather than asking for an `..._undefined` key.

import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { hrMetricHintKey, hrScope } from "@/lib/hr-metric-hints";

const MESSAGES = resolve(__dirname, "../../messages");

describe("hr metric hints (HRP-822)", () => {
  it("falls back to the company-wide texts without a known scope", () => {
    for (const raw of [undefined, null, "", "team", 3]) expect(hrScope(raw)).toBe("workspace");
    expect(hrMetricHintKey("at_risk", hrScope(undefined))).toBe("hrMetricWhy_at_risk");
  });

  it("names the scope for the four scoped blocks only", () => {
    expect(hrMetricHintKey("promoted", hrScope("own"))).toBe("hrMetricWhy_promoted_own");
    expect(hrMetricHintKey("engagement", "subtree")).toBe("hrMetricWhy_engagement_subtree");
    expect(hrMetricHintKey("plans_closed", "own")).toBe("hrMetricWhy_plans_closed");
  });

  it("has every key it can ask for in every catalog", () => {
    const codes = ["at_risk", "promoted", "engagement", "time_to_promote", "plans_closed", "turnover", "avg_match"];
    for (const file of readdirSync(MESSAGES).filter((f) => f.endsWith(".json"))) {
      const analytics = JSON.parse(readFileSync(resolve(MESSAGES, file), "utf8")).analytics;
      for (const scope of ["workspace", "subtree", "own"] as const) {
        for (const code of codes) expect(analytics[hrMetricHintKey(code, scope)], `${file} ${code} ${scope}`).toBeTruthy();
      }
    }
  });
});
