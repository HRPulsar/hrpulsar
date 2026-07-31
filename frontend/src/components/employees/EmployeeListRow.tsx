"use client";

import * as React from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { employeeStatusLabel } from "@/components/employees/employee-status";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { formatDate } from "@/lib/date-format";
import { cn } from "@/lib/utils";

export type EmployeeAlertCode =
  | "user_inactive"
  | "profile_incomplete"
  | "assessment_overdue"
  | "assessment_pending"
  | "pdp_pending_review";

export interface EmployeeAlert {
  code: EmployeeAlertCode;
  label: string;
}

export interface EmployeeListItem {
  id: string;
  user_name?: string | null;
  user_email?: string | null;
  position_title?: string | null;
  specialization_title?: string | null;
  grade_title?: string | null;
  division_id?: string | null;
  division_name?: string | null;
  hire_date?: string;
  status?: string;
  avatar_url?: string | null;
  alert?: EmployeeAlert | null;
}

const ALERT_CLASS: Record<EmployeeAlertCode, string> = {
  user_inactive:
    "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-300",
  profile_incomplete:
    "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300",
  assessment_overdue:
    "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-300",
  assessment_pending:
    "border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300",
  pdp_pending_review:
    "border-violet-300 bg-violet-50 text-violet-700 dark:border-violet-800 dark:bg-violet-950 dark:text-violet-300",
};

// HRP-175: unified 7-column employee list. Same grid template is used by
// the header row and every body row so cells stay perfectly aligned.
//
// Order: Name | Position | Specialization | Grade | Division | Status | Hire Date
const GRID_TEMPLATE =
  "minmax(180px,1.2fr) minmax(180px,1.4fr) minmax(140px,1fr) 120px minmax(140px,1fr) 100px 120px";

export interface EmployeeListRowProps {
  employee: EmployeeListItem;
  href?: string;
  testIdPrefix?: string;
}

export interface EmployeeListProps {
  employees: EmployeeListItem[];
  testIdPrefix?: string;
  /**
   * Forwarded to the underlying row's `href`. Falls back to
   * `/employees/{id}` when omitted.
   */
  rowHref?: (employee: EmployeeListItem) => string;
  /**
   * Hide column headers — used by the legacy non-table renderings that
   * embed rows inside a sheet without their own visual table.
   */
  hideHeader?: boolean;
  className?: string;
}

/** Status badge style follows HRP-175 spec: green / amber / slate. */
function statusBadgeClass(status: string | undefined): string {
  switch (status) {
    case "active":
      return "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300";
    case "on_leave":
      return "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300";
    case "inactive":
    case "terminated":
      return "bg-slate-100 text-slate-700 dark:bg-slate-900 dark:text-slate-300";
    default:
      return "bg-slate-100 text-slate-700 dark:bg-slate-900 dark:text-slate-300";
  }
}

/**
 * Backend returns date-only ISO (`YYYY-MM-DD`); pass through unchanged
 * so a timezone shift can't roll the day over.
 */
function formatHireDate(value?: string): string | null {
  if (!value) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  return formatDate(value, value);
}

interface CellTextProps {
  value: string | null | undefined;
  className?: string;
  testId?: string;
}

/**
 * Ellipsis-truncated cell with hover tooltip showing the full value when
 * the value is non-empty. Tooltip uses the shared `TooltipProvider`
 * (100 ms delay — same as the competence matrix per HRP-157).
 */
function CellText({ value, className, testId }: CellTextProps) {
  const display = value && value.trim() ? value : "—";
  const hasValue = Boolean(value && value.trim());
  if (!hasValue) {
    return (
      <span
        data-testid={testId}
        className={cn("block truncate text-sm", className)}
      >
        {display}
      </span>
    );
  }
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            data-testid={testId}
            className={cn("block truncate text-sm", className)}
          >
            {display}
          </span>
        }
      />
      <TooltipContent>{display}</TooltipContent>
    </Tooltip>
  );
}

/**
 * Header row for the unified employee list. Sticky inside scroll
 * containers, uses semantic `role="row" / role="columnheader"` so the
 * grid layout still announces correctly to assistive tech.
 */
export function EmployeeListHeader({
  testIdPrefix = "employee-list-row",
}: {
  testIdPrefix?: string;
}) {
  const t = useTranslations("employees");
  const cellClass = "text-xs font-medium uppercase tracking-wide text-muted-foreground";
  return (
    <li
      role="row"
      data-testid={`${testIdPrefix}-header`}
      className="sticky top-0 z-10 grid items-center gap-3 border-b bg-muted/30 px-3 py-2 text-left backdrop-blur"
      style={{ gridTemplateColumns: GRID_TEMPLATE }}
    >
      <span
        role="columnheader"
        data-testid={`${testIdPrefix}-column-name`}
        className={cellClass}
      >
        {t("name")}
      </span>
      <span
        role="columnheader"
        data-testid={`${testIdPrefix}-column-position`}
        className={cellClass}
      >
        {t("position")}
      </span>
      <span
        role="columnheader"
        data-testid={`${testIdPrefix}-column-specialization`}
        className={cellClass}
      >
        {t("specialization")}
      </span>
      <span
        role="columnheader"
        data-testid={`${testIdPrefix}-column-grade`}
        className={cellClass}
      >
        {t("grade")}
      </span>
      <span
        role="columnheader"
        data-testid={`${testIdPrefix}-column-division`}
        className={cellClass}
      >
        {t("division")}
      </span>
      <span
        role="columnheader"
        data-testid={`${testIdPrefix}-column-status`}
        className={cellClass}
      >
        {t("status")}
      </span>
      <span
        role="columnheader"
        data-testid={`${testIdPrefix}-column-hire_date`}
        className={cn(cellClass, "text-right")}
      >
        {t("hireDateColumn")}
      </span>
    </li>
  );
}

/**
 * Single employee row in the unified 7-column layout.
 *
 * HRP-175: replaces the previous 5-cell layout that concatenated
 * Specialization and Grade into the Position cell. Each piece of data
 * now has its own column with an explicit header, separator border and
 * tooltip-on-overflow.
 *
 * Both `testIdPrefix` parameter and a stable per-row testid
 * (`employee-list-row-{id}`) are emitted so E2E and unit tests can
 * target rows by either the context-specific prefix or the shared id.
 */
export function EmployeeListRow({
  employee,
  href,
  testIdPrefix = "employee-list-row",
}: EmployeeListRowProps) {
  const t = useTranslations("employees");
  const displayName =
    employee.user_name?.trim() ||
    employee.user_email ||
    employee.id;
  const link = href ?? `/employees/${employee.id}`;
  const hireDate = formatHireDate(employee.hire_date);
  const divisionHref = employee.division_id
    ? `/company/divisions/${employee.division_id}`
    : null;

  return (
    <li
      role="row"
      data-testid={`${testIdPrefix}-${employee.id}`}
      data-employee-id={employee.id}
      // HRP-175: shared stable testid so cross-page assertions can match
      // any rendering of the row regardless of context-specific prefix.
      className="grid items-center gap-3 border-b px-3 py-2 last:border-b-0 hover:bg-muted/20"
      style={{ gridTemplateColumns: GRID_TEMPLATE }}
    >
      {/* Mirror the canonical testid so cross-context selectors can pick
          up the same row regardless of testIdPrefix. */}
      <span
        aria-hidden
        data-testid={`employee-list-row-${employee.id}`}
        className="hidden"
      />
      <div className="flex min-w-0 items-center gap-2" role="cell">
        {employee.alert ? (
          <span
            data-testid={`${testIdPrefix}-${employee.id}-alert`}
            data-alert-code={employee.alert.code}
            title={employee.alert.label}
            className={cn(
              "inline-flex shrink-0 items-center justify-center rounded-full border p-1",
              ALERT_CLASS[employee.alert.code],
            )}
          >
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
            <span className="sr-only">{employee.alert.label}</span>
          </span>
        ) : null}
        <Link
          href={link}
          data-testid={`${testIdPrefix}-${employee.id}-name`}
          data-shared-testid={`employee-list-row-${employee.id}-link`}
          className="block truncate text-sm font-medium hover:underline"
        >
          {/* Mirror the canonical link testid via a hidden sibling so the
              naming convention from HRP-175 ("employee-list-row-{id}-link")
              works without breaking older testIdPrefix-based selectors. */}
          <span
            aria-hidden
            data-testid={`employee-list-row-${employee.id}-link`}
            className="hidden"
          />
          {displayName}
        </Link>
      </div>
      <div className="min-w-0" role="cell">
        <CellText
          value={employee.position_title ?? null}
          testId={`${testIdPrefix}-${employee.id}-position`}
          className="text-muted-foreground"
        />
      </div>
      <div className="min-w-0" role="cell">
        <CellText
          value={employee.specialization_title ?? null}
          testId={`${testIdPrefix}-${employee.id}-specialization`}
          className="text-muted-foreground"
        />
      </div>
      <div className="min-w-0" role="cell">
        {employee.grade_title ? (
          <Badge
            data-testid={`${testIdPrefix}-${employee.id}-grade`}
            variant="outline"
            className="w-fit border-primary/30 bg-primary/5 text-primary"
          >
            {employee.grade_title}
          </Badge>
        ) : (
          <span
            data-testid={`${testIdPrefix}-${employee.id}-grade`}
            className="text-sm text-muted-foreground"
          >
            —
          </span>
        )}
      </div>
      <div className="min-w-0" role="cell">
        {divisionHref ? (
          <Link
            href={divisionHref}
            data-testid={`${testIdPrefix}-${employee.id}-division`}
            className="block truncate text-sm text-muted-foreground hover:text-foreground hover:underline"
            title={employee.division_name ?? undefined}
          >
            {employee.division_name?.trim() || "—"}
          </Link>
        ) : (
          <CellText
            value={employee.division_name ?? null}
            testId={`${testIdPrefix}-${employee.id}-division`}
            className="text-muted-foreground"
          />
        )}
      </div>
      <div role="cell">
        {employee.status ? (
          <Badge
            data-testid={`${testIdPrefix}-${employee.id}-status`}
            variant="secondary"
            className={cn(
              "w-fit shrink-0 capitalize",
              statusBadgeClass(employee.status),
            )}
          >
            {employeeStatusLabel(t, employee.status)}
          </Badge>
        ) : (
          <span
            data-testid={`${testIdPrefix}-${employee.id}-status`}
            className="text-sm text-muted-foreground"
          >
            —
          </span>
        )}
      </div>
      <div className="text-right" role="cell">
        <span
          data-testid={`${testIdPrefix}-${employee.id}-hire-date`}
          className="text-sm text-muted-foreground tabular-nums"
        >
          {hireDate ?? "—"}
        </span>
      </div>
    </li>
  );
}

/**
 * Unified employee list — sticky header row + body rows wrapped in a
 * single `<ul role="table">`. Centralises the layout so callers no
 * longer need to know about the 7-column grid template.
 */
export function EmployeeList({
  employees,
  testIdPrefix = "employee-list-row",
  rowHref,
  hideHeader = false,
  className,
}: EmployeeListProps) {
  return (
    <TooltipProvider>
      <ul
        role="table"
        data-testid={`${testIdPrefix}-list`}
        // HRP-175: horizontal scroll on narrow screens keeps the 7-column
        // grid from collapsing the inner content; the wrapper renders
        // the same grid template at every breakpoint.
        className={cn("min-w-full overflow-x-auto", className)}
      >
        {hideHeader ? null : <EmployeeListHeader testIdPrefix={testIdPrefix} />}
        {employees.map((emp) => (
          <EmployeeListRow
            key={emp.id}
            employee={emp}
            href={rowHref?.(emp)}
            testIdPrefix={testIdPrefix}
          />
        ))}
      </ul>
    </TooltipProvider>
  );
}

/**
 * @deprecated HRP-175: legacy single-string formatter that produced the
 * `Position (Specialization · Grade)` blob. Kept exported for callers
 * that still need a one-line summary outside the table layout — they
 * should migrate to the per-column rendering.
 */
export function formatPositionLabel(emp: EmployeeListItem): string | null {
  const specGrade = [emp.specialization_title, emp.grade_title]
    .filter(Boolean)
    .join(" · ");
  if (emp.position_title && specGrade) {
    return `${emp.position_title} (${specGrade})`;
  }
  return emp.position_title ?? specGrade ?? null;
}
