// HRP-147: Development Plans list reuses the Assessments filter bar
// (title search + multi-select statuses). The match predicate is
// extracted as a pure helper so the page stays declarative and vitest
// can pin the behaviour without rendering React.
//
// The "type" filter from Assessments is intentionally dropped — PDPs do
// not carry a type code.

import type { PDP } from "@/lib/types";

export interface PdpFilters {
  searchQuery: string;
  filterStatuses: readonly string[];
}

export function matchesPdpFilters(pdp: PDP, filters: PdpFilters): boolean {
  const { searchQuery, filterStatuses } = filters;
  if (searchQuery) {
    const needle = searchQuery.toLowerCase();
    if (!(pdp.title || "").toLowerCase().includes(needle)) return false;
  }
  if (filterStatuses.length > 0 && !filterStatuses.includes(pdp.status)) {
    return false;
  }
  return true;
}

export function hasActivePdpFilters(filters: PdpFilters): boolean {
  return filters.searchQuery.length > 0 || filters.filterStatuses.length > 0;
}

// HRP-222: list pages render plans in three buckets — active (anything
// that isn't Done or Cancelled), then Done, then Cancelled. Inside each
// bucket the order is newest-first by the bucket's anchor date: Created
// for actives, ``finished_at`` for Done / Cancelled (both share the
// column).
function _pdpBucketRank(status: string): number {
  if (status === "done") return 1;
  if (status === "cancelled") return 2;
  return 0;
}

function _anchorTime(pdp: PDP): number {
  const iso =
    pdp.status === "done" || pdp.status === "cancelled"
      ? (pdp.finished_at ?? pdp.created_at)
      : pdp.created_at;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : 0;
}

export function comparePdpForList(a: PDP, b: PDP): number {
  const bucketDiff = _pdpBucketRank(a.status) - _pdpBucketRank(b.status);
  if (bucketDiff !== 0) return bucketDiff;
  return _anchorTime(b) - _anchorTime(a);
}

export function sortPdpsForList<T extends PDP>(pdps: readonly T[]): T[] {
  return [...pdps].sort(comparePdpForList);
}
