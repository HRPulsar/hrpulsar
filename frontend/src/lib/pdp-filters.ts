// HRP-147: Development Plans list reuses the Assessments filter bar
// (title search + multi-select statuses). The match predicate is
// extracted as a pure helper so the page stays declarative and vitest
// can pin the behaviour without rendering React.
//
// The "type" filter from Assessments is intentionally dropped — PDPs do
// not carry a type code.

import { isPastDeadline } from "@/lib/deadline";
import type { PDP } from "@/lib/types";

// HRP-638: the dashboard's plan findings are not statuses — "overdue" and
// "stuck in review" are derived from the deadline and how long the plan has
// sat still. They arrive as ``?flag=`` so a finding can link to exactly the
// rows it counted.
export const PDP_FLAGS = ["overdue", "stuck_review"] as const;

export type PdpFlag = (typeof PDP_FLAGS)[number];

// Mirrors DEV_LOOP_STUCK_REVIEW_DAYS in backend/app/modules/employee/issues.py.
const STUCK_REVIEW_DAYS = 14;

// HRP-941: in review only — a returned plan waits on its author.
const STUCK_STATUSES = ["review"];

export interface PdpFilters {
  searchQuery: string;
  filterStatuses: readonly string[];
  filterFlags?: readonly string[];
  // HRP-724: the dashboard's period tiles link here with the window they
  // counted (``?finished_days=90``), so "3 plans in 90 days" opens exactly
  // those three rows rather than every plan ever finished.
  finishedDays?: number;
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** The ``finished_days`` URL value: a positive whole number of days, else nothing. */
export function parseFinishedDays(raw: string | null): number | undefined {
  const days = Number(raw);
  return Number.isInteger(days) && days > 0 ? days : undefined;
}

function isOverdue(pdp: PDP): boolean {
  // A finished plan past its deadline is history, not a thing to chase —
  // same rule the backend cohort uses.
  if (isTerminalStatus(pdp.status)) return false;
  return !!pdp.deadline && isPastDeadline(pdp.deadline);
}

function isTerminalStatus(status: string): boolean {
  return status === "done" || status === "cancelled";
}

function isStuckInReview(pdp: PDP, now: number): boolean {
  if (!STUCK_STATUSES.includes(pdp.status)) return false;
  const touched = Date.parse(pdp.updated_at ?? pdp.created_at);
  if (!Number.isFinite(touched)) return false;
  return now - touched > STUCK_REVIEW_DAYS * DAY_MS;
}

export function matchesPdpFilters(
  pdp: PDP,
  filters: PdpFilters,
  now: number = Date.now(),
): boolean {
  const { searchQuery, filterStatuses, filterFlags = [] } = filters;
  if (searchQuery) {
    const needle = searchQuery.toLowerCase();
    if (!(pdp.title || "").toLowerCase().includes(needle)) return false;
  }
  if (filterStatuses.length > 0 && !filterStatuses.includes(pdp.status)) {
    return false;
  }
  // Flags OR together, like the status multi-select above them.
  if (filterFlags.length > 0) {
    const hit = filterFlags.some((flag) =>
      flag === "overdue"
        ? isOverdue(pdp)
        : flag === "stuck_review"
          ? isStuckInReview(pdp, now)
          : false,
    );
    if (!hit) return false;
  }
  if (filters.finishedDays !== undefined) {
    if (!pdp.finished_at) return false;
    const finished = Date.parse(pdp.finished_at);
    if (!Number.isFinite(finished)) return false;
    if (now - finished > filters.finishedDays * DAY_MS) return false;
  }
  return true;
}

export function hasActivePdpFilters(filters: PdpFilters): boolean {
  return (
    filters.searchQuery.length > 0 ||
    filters.filterStatuses.length > 0 ||
    (filters.filterFlags?.length ?? 0) > 0 ||
    filters.finishedDays !== undefined
  );
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

function comparePdpForList(a: PDP, b: PDP): number {
  const bucketDiff = _pdpBucketRank(a.status) - _pdpBucketRank(b.status);
  if (bucketDiff !== 0) return bucketDiff;
  return _anchorTime(b) - _anchorTime(a);
}

export function sortPdpsForList<T extends PDP>(pdps: readonly T[]): T[] {
  return [...pdps].sort(comparePdpForList);
}
