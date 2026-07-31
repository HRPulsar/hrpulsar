// HRP-194 REDO #3: after picking a value in the Change status (or
// "Change status (all)") modal the trigger has to show the human label
// (e.g. "On review") instead of the raw code ("on_review"). Base UI's
// <Select.Value/> looks up the rendered text in the Select root's
// `items` map — so we pin that the two modals build the map from
// ASSESSMENT_STATUS_OPTIONS + assessmentStatusLabel and pass it through
// the `items` prop.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(__dirname, "../app/(dashboard)/assessments/page.tsx"),
  "utf8",
);

describe("Change status trigger label (HRP-194 REDO)", () => {
  // HRP-476: the labels come from the `assessments` i18n namespace, so the
  // map is built inside the component (memoised on `t`) instead of at module
  // scope — the derivation itself is unchanged.
  it("derives statusItems from ASSESSMENT_STATUS_OPTIONS + assessmentStatusLabel", () => {
    expect(SOURCE).toMatch(
      /const statusItems = useMemo\(\s*\(\) => ASSESSMENT_STATUS_OPTIONS\.map\(\(value\) => \(\{\s*value,\s*label: assessmentStatusLabel\(t, value\),?\s*\}\)\),\s*\[t\],\s*\);/,
    );
  });

  it("passes statusItems to the single Change status Select root", () => {
    expect(SOURCE).toMatch(
      /<Select value=\{newStatus\} items=\{statusItems\} onValueChange=\{setNewStatus\}>/,
    );
  });

  it("passes statusItems to the bulk Change status (all) Select root", () => {
    expect(SOURCE).toMatch(
      /<Select value=\{bulkNewStatus\} items=\{statusItems\} onValueChange=\{setBulkNewStatus\}>/,
    );
  });
});
