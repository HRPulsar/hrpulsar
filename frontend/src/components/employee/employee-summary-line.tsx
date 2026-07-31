"use client";

// HRP-182: shared employee summary used everywhere an employee is
// referenced outside the dedicated list (`/employees`) and profile
// (`/employees/[id]`) pages — e.g. Assessment lists, PDP cards, Talent
// Market matches.
//
// Renders the name on the top line, the current position grayed-out and
// slightly smaller underneath, plus an inline status chip when the
// employee is not `active`. The chip styling mirrors the badge variants
// used on the employees list so the same "status colour" reads the same
// across the product.

import * as React from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { employeeStatusLabel } from "@/components/employees/employee-status";
import { cn } from "@/lib/utils";
import { BADGE_COLOR } from "@/lib/badge-tones";

export interface EmployeeSummaryShape {
  user_name?: string | null;
  user_email?: string | null;
  position_title?: string | null;
  status?: string | null;
}

interface EmployeeSummaryLineProps {
  employee: EmployeeSummaryShape;
  /**
   * When the parent already renders the name itself (e.g. a link), set
   * `hideName` and only the position + status chip will render. The
   * caller stays responsible for layout.
   */
  hideName?: boolean;
  className?: string;
  nameClassName?: string;
  positionClassName?: string;
  "data-testid"?: string;
}

/** Mirror of the status colour scale used by `EmployeeListRow`. */
export function statusBadgeClass(status: string): string {
  switch (status) {
    case "on_leave":
      return BADGE_COLOR.amber;
    case "inactive":
    case "terminated":
      return BADGE_COLOR.neutral;
    default:
      return BADGE_COLOR.neutral;
  }
}

export function deriveEmployeeSummary(emp: EmployeeSummaryShape): {
  name: string;
  position: string;
  status: string;
  showStatus: boolean;
} {
  const name = emp.user_name?.trim() || emp.user_email?.trim() || "";
  const position = emp.position_title?.trim() || "";
  const status = emp.status || "active";
  return { name, position, status, showStatus: status !== "active" };
}

export function EmployeeSummaryLine({
  employee,
  hideName,
  className,
  nameClassName,
  positionClassName,
  "data-testid": testId,
}: EmployeeSummaryLineProps) {
  const t = useTranslations("employees");
  const { name, position, status, showStatus } = deriveEmployeeSummary(employee);
  const statusText = employeeStatusLabel(t, status);

  // HRP-333: with the name hidden and nothing to show (no position, active
  // status) render nothing — avoids a dead flex-gap under names of e.g.
  // external reviewers who have no employee row.
  if (hideName && !position && !showStatus) {
    return null;
  }

  return (
    <div
      data-testid={testId}
      className={cn("flex min-w-0 flex-col gap-0.5", className)}
    >
      {!hideName && (
        <div className="flex items-center gap-2">
          <span
            data-testid={testId ? `${testId}-name` : undefined}
            className={cn("truncate text-sm font-medium", nameClassName)}
          >
            {name || "—"}
          </span>
          {showStatus && (
            <Badge
              data-testid={testId ? `${testId}-status` : undefined}
              variant="secondary"
              className={cn(
                "shrink-0 capitalize",
                statusBadgeClass(status),
              )}
            >
              {statusText}
            </Badge>
          )}
        </div>
      )}
      {position && (
        <span
          data-testid={testId ? `${testId}-position` : undefined}
          className={cn(
            "truncate text-xs text-muted-foreground",
            positionClassName,
          )}
        >
          {position}
        </span>
      )}
      {hideName && showStatus && (
        <Badge
          data-testid={testId ? `${testId}-status` : undefined}
          variant="secondary"
          className={cn("w-fit shrink-0 capitalize", statusBadgeClass(status))}
        >
          {statusText}
        </Badge>
      )}
    </div>
  );
}
