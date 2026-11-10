// HRP-1173: the add-participant dialog on an assessment posts the picked
// role to POST /assessments/{id}/participants, so it offers only roles that
// route takes - `ParticipantAdd.role` in backend/app/modules/assessment/
// schemas.py. "external" is not one: an external reviewer is no employee
// and has a route of its own.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (rel: string) => readFileSync(resolve(__dirname, rel), "utf8");

const page = read("../app/(dashboard)/assessments/[id]/page.tsx");
const schemas = read("../../../backend/app/modules/assessment/schemas.py");

const dialogRoles = [
  ...page.match(/const PARTICIPANT_ROLES = \[([^\]]*)\] as const;/)![1].matchAll(/"([a-z_]+)"/g),
].map((m) => m[1]);
const apiRoles = schemas
  .match(/class ParticipantAdd\(BaseModel\):[\s\S]*?role: str = Field\(pattern="\^\(([^)]*)\)\$"\)/)![1]
  .split("|");

describe("add-participant dialog roles (HRP-1173)", () => {
  it("offers only the roles the API accepts", () => {
    expect(dialogRoles.length).toBeGreaterThan(0);
    for (const role of dialogRoles) expect(apiRoles).toContain(role);
  });

  it("does not offer External", () => {
    expect(dialogRoles).not.toContain("external");
  });
});
