// HRP-1057 — a manager opening a division outside their subtree saw
// "No employees in this division": without `tenant_wide` the employees
// route keeps a manager's list inside the managed subtree (the people
// pickers rely on that). The division page is a read view like the
// employees page, so it opts in and gets out-of-subtree people as
// directory rows. Pinned by source-grep like the sibling division suites.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { allFullRows } from "@/lib/division-employee-filters";

const SOURCE = readFileSync(
  resolve(__dirname, "../app/(dashboard)/company/divisions/[id]/page.tsx"),
  "utf8",
);

describe("Division page employees list (HRP-1057)", () => {
  it("asks for the division's people tenant-wide", () => {
    expect(SOURCE).toMatch(
      /`\/employees\?division_id=\$\{id\}&include_sub_divisions=true&tenant_wide=true`/,
    );
  });

  it("keeps id-based tiles, filters and HR columns to full rows", () => {
    // Directory rows carry no specialization / position / grade ids: the
    // tiles would read 0 and the filters would match nothing.
    expect(SOURCE).toContain("const hrView = canViewHrData && allFullRows(employees);");
    expect(SOURCE).not.toContain("{canViewHrData && (");
    expect(SOURCE).toContain("hrColumns={hrView}");
  });
});

describe("allFullRows (HRP-1057)", () => {
  const full = { id: "a", hire_date: "2024-01-01", specialization_id: "s" };
  const trimmed = { id: "b", specialization_title: "Backend" };

  it("holds for full rows and for none", () => {
    expect(allFullRows([full, { ...full, id: "c" }])).toBe(true);
    expect(allFullRows([])).toBe(true);
  });

  it("fails on a mixed page - a manager on a parent of their subtree", () => {
    expect(allFullRows([full, trimmed])).toBe(false);
    expect(allFullRows([trimmed])).toBe(false);
  });
});
