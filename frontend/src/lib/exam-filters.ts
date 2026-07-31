// HRP-227 + HRP-233: Exams list filter bar (title search + multi-status)
// mirrors the Development plans page (HRP-147). The match predicate and the
// list ordering are extracted as pure helpers so the page stays declarative
// and vitest can pin the behaviour without rendering React.

import type { MassExam } from "@/lib/types";

export interface ExamFilters {
  searchQuery: string;
  filterStatuses: readonly string[];
}

export function matchesExamFilters(exam: MassExam, filters: ExamFilters): boolean {
  const { searchQuery, filterStatuses } = filters;
  if (searchQuery) {
    const needle = searchQuery.toLowerCase();
    if (!(exam.title || "").toLowerCase().includes(needle)) return false;
  }
  if (filterStatuses.length > 0 && !filterStatuses.includes(exam.status)) {
    return false;
  }
  return true;
}

export function hasActiveExamFilters(filters: ExamFilters): boolean {
  return filters.searchQuery.length > 0 || filters.filterStatuses.length > 0;
}

// HRP-233: list pages render exams in three buckets — active (anything that
// isn't done or cancelled), then done, then cancelled. Inside each bucket
// newest-first by the bucket's anchor date: ``created_at`` for actives,
// ``finished_at`` for done / cancelled (both share the timestamp column).
function _bucketRank(status: string): number {
  if (status === "done") return 1;
  if (status === "cancelled") return 2;
  return 0;
}

function _anchorTime(exam: MassExam): number {
  const iso =
    exam.status === "done" || exam.status === "cancelled"
      ? (exam.finished_at ?? exam.created_at)
      : exam.created_at;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : 0;
}

export function compareExamForList(a: MassExam, b: MassExam): number {
  const bucketDiff = _bucketRank(a.status) - _bucketRank(b.status);
  if (bucketDiff !== 0) return bucketDiff;
  return _anchorTime(b) - _anchorTime(a);
}

export function sortExamsForList<T extends MassExam>(exams: readonly T[]): T[] {
  return [...exams].sort(compareExamForList);
}

// HRP-233: the rightmost timestamp column shows the date matching the row's
// bucket — ``Created`` for active exams, ``Completed`` for ``done``,
// ``Cancelled`` for ``cancelled``. Returns null when the underlying date is
// missing (terminal status with no ``finished_at`` should not happen in
// practice but we degrade gracefully).
//
// HRP-476: ``labelKey`` points at the `exams` i18n namespace — callers
// render it through their translator.
export function examListTimestamp(exam: MassExam): {
  labelKey: "dateCreated" | "dateCompleted" | "dateCancelled";
  iso: string;
} | null {
  if (exam.status === "done") {
    return exam.finished_at
      ? { labelKey: "dateCompleted", iso: exam.finished_at }
      : null;
  }
  if (exam.status === "cancelled") {
    return exam.finished_at
      ? { labelKey: "dateCancelled", iso: exam.finished_at }
      : null;
  }
  return { labelKey: "dateCreated", iso: exam.created_at };
}
