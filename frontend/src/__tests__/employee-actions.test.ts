// HRP-660: the employee card hands an employee to the screens that own the
// create flows, and the Competences tab marks a row below the bar as a gap.
// Both rules are one line each and both are wrong in a way nobody notices
// until a button opens an empty dialog, so they get pinned here.

import { describe, expect, it } from "vitest";

import {
  createAssessmentHref,
  createPdpHref,
  readCreateDeepLink,
} from "@/lib/employee-actions";
import { isCompetenceGap } from "@/lib/employee-issues";

const EMP = "4f2b9c1a-0000-4000-8000-000000000001";

describe("create deep links", () => {
  it("round-trips the employee through the development link", () => {
    const href = createPdpHref(EMP);
    expect(href.startsWith("/development?")).toBe(true);
    expect(readCreateDeepLink(href.split("?")[1])).toBe(EMP);
  });

  it("round-trips the employee through the assessment link", () => {
    const href = createAssessmentHref(EMP);
    expect(href.startsWith("/assessments?")).toBe(true);
    expect(readCreateDeepLink(href.split("?")[1])).toBe(EMP);
  });

  it("ignores a query string that is not a create link", () => {
    expect(readCreateDeepLink("status=draft&flag=overdue")).toBeNull();
    expect(readCreateDeepLink(`employee_id=${EMP}`)).toBeNull();
    expect(readCreateDeepLink("create=1")).toBeNull();
    expect(readCreateDeepLink("create=1&employee_id=")).toBeNull();
  });
});

describe("isCompetenceGap", () => {
  it("is a gap strictly below the bar", () => {
    expect(isCompetenceGap({ percent: 44, passing_score: 75 })).toBe(true);
    expect(isCompetenceGap({ percent: 74, passing_score: 75 })).toBe(true);
  });

  it("is not a gap at or above the bar", () => {
    expect(isCompetenceGap({ percent: 75, passing_score: 75 })).toBe(false);
    expect(isCompetenceGap({ percent: 90, passing_score: 75 })).toBe(false);
  });

  it("honours a tenant bar other than the default", () => {
    expect(isCompetenceGap({ percent: 60, passing_score: 50 })).toBe(false);
    expect(isCompetenceGap({ percent: 40, passing_score: 50 })).toBe(true);
  });

  it("treats a never-assessed row as no verdict", () => {
    expect(isCompetenceGap({ percent: null, passing_score: 75 })).toBe(false);
  });
});
