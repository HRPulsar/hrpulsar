// HRP-857: naming a division's head or deputy grants the manager role, so
// below the admin level the pickers offer one's own subtree and oneself -
// the same answer the API gives, which refuses anyone else with 403.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { headCandidates } from "@/lib/division-heads";
import type { Employee } from "@/lib/types";

const emp = (id: string, user_id: string, division_id: string | null) =>
  ({ id, user_id, division_id }) as Employee;

const EMPLOYEES = [
  emp("self", "u-self", "elsewhere"),
  emp("inside", "u-in", "mine"),
  emp("outside", "u-out", "other"),
  emp("nowhere", "u-none", null),
];

describe("headCandidates (HRP-857)", () => {
  it("offers the admin level everyone", () => {
    expect(
      headCandidates(EMPLOYEES, { adminLevel: true, scopeIds: new Set(), userId: "u-self" }),
    ).toHaveLength(4);
  });

  it("offers a manager their subtree and themselves", () => {
    const ids = headCandidates(EMPLOYEES, {
      adminLevel: false,
      scopeIds: new Set(["mine"]),
      userId: "u-self",
    }).map((e) => e.id);
    expect(ids).toEqual(["self", "inside"]);
  });
});

describe("A seat held from elsewhere (HRP-857)", () => {
  it("stays the admin's on both division forms, with the reason under it", () => {
    for (const page of [
      "../app/(dashboard)/company/page.tsx",
      "../app/(dashboard)/company/divisions/[id]/page.tsx",
    ]) {
      const src = readFileSync(resolve(__dirname, page), "utf8").replace(/\s+/g, " ");
      expect(src).toContain(
        "const seatFromElsewhere = (id: string) => !isAdminLevel && Boolean(id) && !heads.some((e) => e.id === id);",
      );
      expect(src).toContain('t("seatFromElsewhere")');
    }
  });
});
