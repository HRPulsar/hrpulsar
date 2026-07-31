// HRP-192 REDO: the disabled "In progress" option inside the Change status
// modals has a (i) hint. QA reported that hovering it didn't surface the
// tooltip "Manual transition is not allowed" — the previous attempt used
// the native HTML `title` attribute on a SelectItem whose CSS sets
// pointer-events: none, so the cursor never landed on a hover target.
//
// The fix renders the hint through the project Tooltip primitive with a
// `pointer-events-auto` span that swallows pointer/click so Radix Select
// doesn't treat the icon as a re-select. We can't easily mount the full
// page under vitest (no jsdom), so we pin the rule by source-grep.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(__dirname, "../app/(dashboard)/assessments/page.tsx"),
  "utf8",
);

describe("Change status modal — Manual forbidden hint (HRP-192 REDO)", () => {
  it("imports Tooltip primitives", () => {
    expect(SOURCE).toMatch(/from "@\/components\/ui\/tooltip"/);
    expect(SOURCE).toMatch(/Tooltip,\s*TooltipContent,\s*TooltipTrigger/);
  });

  it("renders a ManualForbiddenHint instead of the bare native title attribute", () => {
    expect(SOURCE).toMatch(/function ManualForbiddenHint\(/);
    expect(SOURCE).toMatch(/<ManualForbiddenHint/);
    // Make sure no stale title="Manual transition is not allowed" sneaks back.
    expect(SOURCE).not.toMatch(/title=\{forbidden\s*\?/);
  });

  it("makes the hint hoverable by overriding pointer-events on the icon", () => {
    expect(SOURCE).toMatch(/pointer-events-auto/);
  });

  it("uses the shared tooltip copy and stops propagation to the SelectItem", () => {
    // HRP-476: the copy is resolved through the `assessments` namespace from
    // the shared key, then rendered in both the aria-label and the tooltip.
    expect(SOURCE).toMatch(
      /const tooltip = t\(ASSESSMENT_MANUAL_FORBIDDEN_TOOLTIP_KEY\);/,
    );
    expect(SOURCE).toMatch(/TooltipContent>\{tooltip\}<\/TooltipContent/);
    expect(SOURCE).toMatch(/onPointerDown=\{\(e\) => e\.stopPropagation\(\)\}/);
    expect(SOURCE).toMatch(/onClick=\{\(e\) => e\.stopPropagation\(\)\}/);
  });
});
