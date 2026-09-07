// HRP-672 follow-up: the global search vacancy row localises the grade but
// still printed the raw vacancy status wire code next to it. The same
// source-grep style as interview-enum-labels — the component is not
// mounted, the rule is that the label goes through the shared helper.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(__dirname, "../components/global-search.tsx"),
  "utf8",
);

describe("Global search vacancy subtitle (HRP-672 follow-up)", () => {
  it("renders the status through vacancyStatusBadgeLabel", () => {
    expect(SOURCE).toMatch(/vacancyStatusBadgeLabel\(\w+, v\.status\)/);
  });

  it("no longer interpolates the wire code", () => {
    expect(SOURCE).not.toMatch(/— \$\{v\.status\}/);
  });
});
