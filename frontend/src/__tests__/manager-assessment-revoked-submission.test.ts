// HRP-577: revoking an invitation that was already submitted drops the
// sheet out of the aggregates (HRP-383) but must not hide it — the
// recruiter still needs to read what the evaluator wrote, marked as no
// longer counted. The component can't be mounted under vitest (heavy
// data deps), so the rule is pinned by source-grep, like the other
// gating tests in this folder.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(__dirname, "../components/recruitment/manager-assessment-section.tsx"),
  "utf8",
);

const EN = JSON.parse(
  readFileSync(resolve(__dirname, "../../messages/en.json"), "utf8"),
);
const DE = JSON.parse(
  readFileSync(resolve(__dirname, "../../messages/de.json"), "utf8"),
);

describe("Manager assessment — revoked submission stays readable (HRP-577)", () => {
  it("does not gate View submission on the current status alone", () => {
    expect(SOURCE).toMatch(
      /const canView =\s*invite\.status === "submitted" \|\| Boolean\(invite\.submitted_at\);/,
    );
  });

  it("carries submitted_at and revoked_at on the invite DTO", () => {
    expect(SOURCE).toMatch(/submitted_at: string \| null;/);
    expect(SOURCE).toMatch(/revoked_at: string \| null;/);
  });

  it("marks a revoked submission as not counted in the drawer", () => {
    expect(SOURCE).toMatch(/invite\.revoked_at && \(/);
    expect(SOURCE).toMatch(
      /data-testid="assessment-invite-submission-not-counted"/,
    );
    expect(SOURCE).toMatch(/t\("managerAssessmentInviteSubmissionNotCounted"\)/);
  });

  it("has the note in both catalogs", () => {
    expect(
      EN.recruitment.managerAssessmentInviteSubmissionNotCounted,
    ).toBeTruthy();
    expect(
      DE.recruitment.managerAssessmentInviteSubmissionNotCounted,
    ).toBeTruthy();
  });
});
