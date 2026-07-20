// HRP-243: the assessment detail page renders the Results card only when
// the viewer is privileged (admin / manager / platform_admin) or the
// viewer is the assessee on a Done assessment. We can't mount the full
// page under vitest (no jsdom + heavy data deps), so we pin the rule by
// source-grep on the gating expression.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(__dirname, "../app/(dashboard)/assessments/[id]/page.tsx"),
  "utf8",
);

describe("Assessment detail — Results visibility (HRP-243)", () => {
  it("computes isSelfParticipant from a participant whose role is self", () => {
    expect(SOURCE).toMatch(
      /isSelfParticipant = !!currentUser\?\.id && assessment\.participants\.some\(/,
    );
    expect(SOURCE).toMatch(/p\.role === "self" && p\.user_id === currentUser\.id/);
  });

  it("uses isPrivileged for admin/manager/platform_admin", () => {
    expect(SOURCE).toMatch(
      /const isPrivileged = canManage \|\| roles\.includes\("platform_admin"\);/,
    );
  });

  it("requires Done status for the self participant case", () => {
    expect(SOURCE).toMatch(
      /isPrivileged \|\| \(isSelfParticipant && assessment\.status_code === "done"\)/,
    );
  });

  it("gates the Results card render on canViewResults", () => {
    expect(SOURCE).toMatch(
      /\{canViewResults && assessment\.results\.length > 0 && \(/,
    );
  });
});
