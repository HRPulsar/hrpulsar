// HRP-425: the Analytics tiles are labelled with the vacancy funnel's own
// terminal stage names (comma-separated when a funnel has several), and
// only fall back to the generic "Hired" / "Rejected" strings when the
// funnel declares no terminal stage of that kind.

import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(__dirname, "../components/recruitment/vacancy-analytics-tab.tsx"),
  "utf8",
);
const FLAT = SOURCE.replace(/\s+/g, " ");

const TYPES = readFileSync(resolve(__dirname, "../lib/types.ts"), "utf8");

// Catalogs are discovered rather than hardcoded: ru.json is enterprise-only
// and absent from the public repo (same approach as vacancy-salary.test.ts).
const MESSAGES_DIR = resolve(__dirname, "../../messages");
const CATALOGS: [string, { recruitment: Record<string, string> }][] =
  readdirSync(MESSAGES_DIR)
    .filter((file) => file.endsWith(".json"))
    .sort()
    .map((file) => [
      basename(file, ".json"),
      JSON.parse(readFileSync(resolve(MESSAGES_DIR, file), "utf8")),
    ]);

describe("Vacancy analytics tiles (HRP-425)", () => {
  it("labels the terminal tiles from the funnel, falling back to the defaults", () => {
    expect(FLAT).toContain(
      "const hiredLabel = data.positive_stage_names.length > 0 ? data.positive_stage_names.join(\", \") : t(\"analyticsTabHired\");",
    );
    expect(FLAT).toContain(
      "const rejectedLabel = data.negative_stage_names.length > 0 ? data.negative_stage_names.join(\", \") : t(\"analyticsTabRejected\");",
    );
    expect(FLAT).toContain(
      "const withdrewLabel = data.neutral_stage_names.length > 0 ? data.neutral_stage_names.join(\", \") : t(\"analyticsTabWithdrew\");",
    );
    expect(FLAT).toContain("{hiredLabel}");
    expect(FLAT).toContain("{rejectedLabel}");
    expect(FLAT).toContain("{withdrewLabel}");
  });

  it("keeps reading the counters the backend derives from stage types", () => {
    expect(FLAT).toContain("{data.win_loss.hired}");
    expect(FLAT).toContain("{data.win_loss.rejected}");
    expect(FLAT).toContain("{data.win_loss.withdrew}");
    expect(FLAT).toContain("{data.win_loss.in_progress}");
    expect(FLAT).toContain("{data.total_candidates}");
  });

  it("exposes each tile for the e2e suite", () => {
    for (const id of [
      "recruitment-vacancy-analytics-total",
      "recruitment-vacancy-analytics-hired",
      "recruitment-vacancy-analytics-rejected",
      "recruitment-vacancy-analytics-withdrew",
      "recruitment-vacancy-analytics-in-progress",
    ]) {
      expect(FLAT).toContain(`data-testid="${id}"`);
    }
  });

  it("orders the tiles Total → Hired → Rejected → Withdrew → In progress", () => {
    const order = [
      "recruitment-vacancy-analytics-total",
      "recruitment-vacancy-analytics-hired",
      "recruitment-vacancy-analytics-rejected",
      "recruitment-vacancy-analytics-withdrew",
      "recruitment-vacancy-analytics-in-progress",
    ].map((id) => FLAT.indexOf(`data-testid="${id}"`));
    expect(order).toEqual([...order].sort((a, b) => a - b));
  });

  it("types the three label lists on the analytics payload", () => {
    expect(TYPES).toContain("positive_stage_names: string[];");
    expect(TYPES).toContain("negative_stage_names: string[];");
    expect(TYPES).toContain("neutral_stage_names: string[];");
  });

  it("ships the fallback caption in every shipped catalog", () => {
    for (const [locale, catalog] of CATALOGS) {
      expect(
        catalog.recruitment.analyticsTabWithdrew,
        `${locale}.analyticsTabWithdrew`,
      ).toBeTruthy();
    }
  });
});
