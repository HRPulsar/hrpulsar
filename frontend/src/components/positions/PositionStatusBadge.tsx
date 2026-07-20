"use client";

import { Badge } from "@/components/ui/badge";
import type { PositionLifecycleStatus } from "@/lib/types";

const STATUS_LABEL: Record<PositionLifecycleStatus, string> = {
  active: "Active",
  on_hold: "On hold",
  frozen: "Frozen",
  closed: "Closed",
};

const STATUS_CLASS: Record<PositionLifecycleStatus, string> = {
  active:
    "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  on_hold:
    "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300",
  frozen:
    "border-slate-300 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300",
  closed:
    "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-300",
};

export interface PositionStatusBadgeProps {
  status: PositionLifecycleStatus;
  className?: string;
  testId?: string;
}

export function PositionStatusBadge({
  status,
  className,
  testId,
}: PositionStatusBadgeProps) {
  return (
    <Badge
      variant="outline"
      data-testid={testId}
      data-status={status}
      className={[STATUS_CLASS[status], className].filter(Boolean).join(" ")}
    >
      {STATUS_LABEL[status]}
    </Badge>
  );
}

export const POSITION_LIFECYCLE_LABEL = STATUS_LABEL;

/**
 * HRP-111: single source of truth for "from status X, which transitions
 * does the UI offer". Detail page and list-row status menu both read this
 * map; if the lifecycle changes, both surfaces pick up the new flow
 * without a second-source drift.
 *
 * `closed → ["active"]` encodes the HRP-32 rule that a closed position
 * can only be reopened by flipping it back to active. The other entries
 * list every alternative so park/freeze/close can be offered in any order
 * while a position is alive.
 */
export const POSITION_LIFECYCLE_FLOW: Record<
  PositionLifecycleStatus,
  PositionLifecycleStatus[]
> = {
  active: ["on_hold", "frozen", "closed"],
  on_hold: ["active", "frozen", "closed"],
  frozen: ["active", "on_hold", "closed"],
  closed: ["active"],
};
