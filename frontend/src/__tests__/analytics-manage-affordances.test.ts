// HRP-822: analytics is a translated section, so its two writing calls -
// the XLSX export and the development loop's AI summary - answer to
// `manage` while the charts answer to `view`. The backend makes that split
// by the HTTP method, which means the affordances have to make it too, or
// a caller the tenant left at `view` gets a button that only ever 403s.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const analyticsPage = readFileSync(
  resolve(__dirname, "../app/(dashboard)/analytics/page.tsx"),
  "utf8",
);
const dashboardPage = readFileSync(
  resolve(__dirname, "../app/(dashboard)/dashboard/page.tsx"),
  "utf8",
);

describe("the writing affordances of the analytics section (HRP-822)", () => {
  it("hides the assessment export behind manage", () => {
    expect(analyticsPage).toContain('api.postBlob("/analytics/export/assessments")');
    expect(analyticsPage).toContain('{canManageSection("analytics") && (');
  });

  it("hides the dev-loop AI summary behind manage", () => {
    expect(dashboardPage).toContain('api.post<AiSummary>("/analytics/dev-loop/ai-summary"');
    expect(dashboardPage).toContain(
      '{ai.status !== "done" && canManageSection("analytics") && (',
    );
  });

  it("leaves the personal loop's summary alone - it is outside the matrix", () => {
    // `/analytics/my-loop/ai-summary` is a PERSONAL_PATH on the backend and
    // answers whatever the matrix says, so its button carries no gate. The
    // personal queue is the block after the company one, so what is checked
    // here is that the gate did not land on it.
    const personal = dashboardPage.slice(
      dashboardPage.indexOf('api.post<AiSummary>("/analytics/my-loop/ai-summary"'),
    );
    expect(personal).not.toContain('canManageSection("analytics")');
  });
});
