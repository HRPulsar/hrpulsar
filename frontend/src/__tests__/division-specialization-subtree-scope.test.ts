// HRP-571 — the Specializations tiles counted employees across the whole
// subtree but drew their catalogue from the division's own mapping rows,
// so a child department that was mapped and not yet staffed showed
// nothing: its specializations reached the parent only through somebody
// who happened to hold one.
//
// The page now asks for the subtree's mappings and narrows them back with
// the same toggle that narrows the employees. The page cannot be mounted
// under vitest (heavy data deps), so this is pinned by source-grep like
// the sibling structural suites.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(__dirname, "../app/(dashboard)/company/divisions/[id]/page.tsx"),
  "utf8",
);

const FLAT = SOURCE.replace(/\s+/g, " ");

describe("Division specialization tiles scope (HRP-571)", () => {
  it("asks the API for the subtree's mappings", () => {
    // Same query the backend route takes — see
    // backend/tests/unit/test_hrp571_division_specialization_subtree.py.
    expect(FLAT).toContain(
      "`/divisions/${id}/specializations?include_sub_divisions=true`",
    );
  });

  it("narrows them with the same toggle the employees use", () => {
    expect(FLAT).toContain(
      "includeSubDivisions ? specializations : specializations.filter((s) => s.division_id === id)",
    );
  });

  it("feeds the scoped rows to the tiles and to the filter options", () => {
    expect(FLAT).toContain(
      "deriveSpecializationTiles(scopedSpecializations, scopedEmployees)",
    );
    expect(FLAT).toContain(
      "deriveSpecializationOptions(scopedSpecializations, scopedEmployees)",
    );
  });
});
