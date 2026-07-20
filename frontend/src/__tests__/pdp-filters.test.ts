// HRP-147: pins the client-side filter matcher for the Development
// Plans list. Mirrors the Assessments filter bar (title search +
// multi-select status) minus the type filter — PDPs do not have a type.

import { describe, expect, it } from "vitest";
import {
  hasActivePdpFilters,
  matchesPdpFilters,
} from "@/lib/pdp-filters";
import type { PDP } from "@/lib/types";

function makePdp(overrides: Partial<PDP> = {}): PDP {
  return {
    id: "pdp-1",
    title: "Senior Backend growth plan",
    employee_id: "emp-1",
    employee_name: "Alice",
    specialization_id: null,
    specialization_title: null,
    grade_id: null,
    grade_title: null,
    status: "in_progress",
    total_progress: 25,
    deadline: null,
    started_at: null,
    finished_at: null,
    created_at: "2026-05-01T00:00:00Z",
    ...overrides,
  };
}

describe("matchesPdpFilters (HRP-147)", () => {
  it("returns true when no filters are active", () => {
    expect(
      matchesPdpFilters(makePdp(), { searchQuery: "", filterStatuses: [] }),
    ).toBe(true);
  });

  it("matches title case-insensitively", () => {
    const pdp = makePdp({ title: "Senior Backend growth plan" });
    expect(
      matchesPdpFilters(pdp, { searchQuery: "backend", filterStatuses: [] }),
    ).toBe(true);
    expect(
      matchesPdpFilters(pdp, { searchQuery: "BACKEND", filterStatuses: [] }),
    ).toBe(true);
  });

  it("rejects when the search term does not appear in the title", () => {
    const pdp = makePdp({ title: "Senior Backend growth plan" });
    expect(
      matchesPdpFilters(pdp, { searchQuery: "frontend", filterStatuses: [] }),
    ).toBe(false);
  });

  it("matches status when the multi-select includes the plan status", () => {
    const pdp = makePdp({ status: "in_progress" });
    expect(
      matchesPdpFilters(pdp, {
        searchQuery: "",
        filterStatuses: ["draft", "in_progress"],
      }),
    ).toBe(true);
  });

  it("rejects when the multi-select excludes the plan status", () => {
    const pdp = makePdp({ status: "in_progress" });
    expect(
      matchesPdpFilters(pdp, {
        searchQuery: "",
        filterStatuses: ["draft", "done"],
      }),
    ).toBe(false);
  });

  it("combines search and status as AND", () => {
    const pdp = makePdp({ title: "Backend", status: "draft" });
    expect(
      matchesPdpFilters(pdp, {
        searchQuery: "backend",
        filterStatuses: ["draft"],
      }),
    ).toBe(true);
    expect(
      matchesPdpFilters(pdp, {
        searchQuery: "backend",
        filterStatuses: ["done"],
      }),
    ).toBe(false);
  });

  it("treats an empty status list as 'match all statuses'", () => {
    const pdp = makePdp({ status: "cancelled" });
    expect(
      matchesPdpFilters(pdp, { searchQuery: "", filterStatuses: [] }),
    ).toBe(true);
  });

  it("treats a null/empty title as not matching any non-empty search", () => {
    const pdp = makePdp({ title: "" });
    expect(
      matchesPdpFilters(pdp, { searchQuery: "anything", filterStatuses: [] }),
    ).toBe(false);
  });
});

describe("hasActivePdpFilters (HRP-147)", () => {
  it("returns false when nothing is set", () => {
    expect(hasActivePdpFilters({ searchQuery: "", filterStatuses: [] })).toBe(false);
  });

  it("returns true when the search query is non-empty", () => {
    expect(
      hasActivePdpFilters({ searchQuery: "foo", filterStatuses: [] }),
    ).toBe(true);
  });

  it("returns true when at least one status is selected", () => {
    expect(
      hasActivePdpFilters({ searchQuery: "", filterStatuses: ["draft"] }),
    ).toBe(true);
  });
});
