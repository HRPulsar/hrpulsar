// HRP-640: below the admin level a mass assessment is its author's - the
// API answers 403 `not_the_author` on its rename, criteria, scale and bulk
// status for anyone else, so neither the group page nor the list's row menu
// offers them. Pinned by source-grep: both pages need the API to render.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (p: string) =>
  readFileSync(resolve(__dirname, p), "utf8").replace(/\s+/g, " ");

describe("Mass assessment actions are the author's (HRP-640)", () => {
  it("the group page gates every action on the author or the admin level", () => {
    const page = read("../app/(dashboard)/assessment-groups/[id]/page.tsx");
    expect(page).toContain(
      "const runsGroup = canManage && (isAdminLevel || group.initiator_id === user?.id);",
    );
    expect(page).not.toMatch(/\{canManage && (isGroupDraft|\()/);
  });

  it("the list offers Change status for all only on one's own run", () => {
    const page = read("../app/(dashboard)/assessments/page.tsx");
    expect(page).toContain("{canManage && (isAdminLevel || g.initiator_id === user?.id) && (");
  });
});
