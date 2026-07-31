// HRP-227 + HRP-233: pins the client-side filter matcher, bucket sort and
// timestamp helper for the Exams list. Mirrors the PDP filter contract.

import { describe, expect, it } from "vitest";
import {
  compareExamForList,
  examListTimestamp,
  hasActiveExamFilters,
  matchesExamFilters,
  sortExamsForList,
} from "@/lib/exam-filters";
import type { MassExam } from "@/lib/types";

function makeExam(overrides: Partial<MassExam> = {}): MassExam {
  return {
    id: "exam-1",
    title: "Onboarding quiz",
    description: null,
    status: "draft",
    created_at: "2026-05-01T00:00:00Z",
    ended_at: null,
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

describe("matchesExamFilters (HRP-227)", () => {
  it("returns true when no filters are active", () => {
    expect(
      matchesExamFilters(makeExam(), { searchQuery: "", filterStatuses: [] }),
    ).toBe(true);
  });

  it("matches title case-insensitively", () => {
    const exam = makeExam({ title: "Onboarding quiz" });
    expect(
      matchesExamFilters(exam, { searchQuery: "onboarding", filterStatuses: [] }),
    ).toBe(true);
    expect(
      matchesExamFilters(exam, { searchQuery: "ONBOARDING", filterStatuses: [] }),
    ).toBe(true);
  });

  it("rejects when the search term does not appear in the title", () => {
    const exam = makeExam({ title: "Onboarding quiz" });
    expect(
      matchesExamFilters(exam, { searchQuery: "security", filterStatuses: [] }),
    ).toBe(false);
  });

  it("matches status when the multi-select includes the exam status", () => {
    const exam = makeExam({ status: "in_progress" });
    expect(
      matchesExamFilters(exam, {
        searchQuery: "",
        filterStatuses: ["draft", "in_progress"],
      }),
    ).toBe(true);
  });

  it("rejects when the multi-select excludes the exam status", () => {
    const exam = makeExam({ status: "in_progress" });
    expect(
      matchesExamFilters(exam, {
        searchQuery: "",
        filterStatuses: ["draft", "done"],
      }),
    ).toBe(false);
  });

  it("combines search and status as AND", () => {
    const exam = makeExam({ title: "Compliance basics", status: "draft" });
    expect(
      matchesExamFilters(exam, {
        searchQuery: "compliance",
        filterStatuses: ["draft"],
      }),
    ).toBe(true);
    expect(
      matchesExamFilters(exam, {
        searchQuery: "compliance",
        filterStatuses: ["done"],
      }),
    ).toBe(false);
  });
});

describe("hasActiveExamFilters (HRP-227)", () => {
  it("returns false when nothing is set", () => {
    expect(hasActiveExamFilters({ searchQuery: "", filterStatuses: [] })).toBe(false);
  });

  it("returns true when the search query is non-empty", () => {
    expect(
      hasActiveExamFilters({ searchQuery: "foo", filterStatuses: [] }),
    ).toBe(true);
  });

  it("returns true when at least one status is selected", () => {
    expect(
      hasActiveExamFilters({ searchQuery: "", filterStatuses: ["draft"] }),
    ).toBe(true);
  });
});

describe("compareExamForList / sortExamsForList (HRP-233)", () => {
  it("groups active first, then done, then cancelled", () => {
    const draft = makeExam({ id: "1", status: "draft", created_at: "2026-05-01T00:00:00Z" });
    const done = makeExam({ id: "2", status: "done", finished_at: "2026-05-05T00:00:00Z" });
    const cancelled = makeExam({ id: "3", status: "cancelled", finished_at: "2026-05-10T00:00:00Z" });
    const sorted = sortExamsForList([cancelled, done, draft]);
    expect(sorted.map((e) => e.id)).toEqual(["1", "2", "3"]);
  });

  it("orders newest-first by created_at inside the active bucket", () => {
    const older = makeExam({ id: "1", status: "draft", created_at: "2026-05-01T00:00:00Z" });
    const newer = makeExam({ id: "2", status: "sent", created_at: "2026-05-05T00:00:00Z" });
    const sorted = sortExamsForList([older, newer]);
    expect(sorted.map((e) => e.id)).toEqual(["2", "1"]);
  });

  it("orders newest-first by finished_at inside done / cancelled", () => {
    const olderDone = makeExam({ id: "1", status: "done", finished_at: "2026-05-01T00:00:00Z" });
    const newerDone = makeExam({ id: "2", status: "done", finished_at: "2026-05-05T00:00:00Z" });
    const olderCancel = makeExam({ id: "3", status: "cancelled", finished_at: "2026-05-02T00:00:00Z" });
    const newerCancel = makeExam({ id: "4", status: "cancelled", finished_at: "2026-05-06T00:00:00Z" });
    const sorted = sortExamsForList([olderDone, olderCancel, newerCancel, newerDone]);
    expect(sorted.map((e) => e.id)).toEqual(["2", "1", "4", "3"]);
  });

  it("is a stable pure function", () => {
    const a = makeExam({ id: "1" });
    const b = makeExam({ id: "2" });
    const original = [a, b];
    compareExamForList(a, b);
    expect(original).toEqual([a, b]);
  });
});

describe("examListTimestamp (HRP-233)", () => {
  it("returns the Created key for active statuses", () => {
    const exam = makeExam({ status: "draft", created_at: "2026-05-01T00:00:00Z" });
    expect(examListTimestamp(exam)).toEqual({
      labelKey: "dateCreated",
      iso: "2026-05-01T00:00:00Z",
    });
  });

  it("returns the Completed key for done exams", () => {
    const exam = makeExam({ status: "done", finished_at: "2026-05-05T00:00:00Z" });
    expect(examListTimestamp(exam)).toEqual({
      labelKey: "dateCompleted",
      iso: "2026-05-05T00:00:00Z",
    });
  });

  it("returns the Cancelled key for cancelled exams", () => {
    const exam = makeExam({ status: "cancelled", finished_at: "2026-05-10T00:00:00Z" });
    expect(examListTimestamp(exam)).toEqual({
      labelKey: "dateCancelled",
      iso: "2026-05-10T00:00:00Z",
    });
  });

  it("returns null when a terminal exam is missing finished_at", () => {
    const exam = makeExam({ status: "done", finished_at: null });
    expect(examListTimestamp(exam)).toBeNull();
  });
});
