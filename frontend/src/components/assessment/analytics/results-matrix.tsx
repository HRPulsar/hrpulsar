"use client";

import Link from "next/link";
import { ArrowDown, ArrowUp, SquareArrowOutUpRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { MatchPercentChip } from "@/components/assessment/match-percent-chip";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { MatrixRow, SortDirection } from "@/lib/assessment/group-analytics";
import type { GroupAnalyticsEmployee } from "@/lib/types";

/** Division names longer than this collapse into a tooltip. */
const DIVISION_MAX_CHARS = 15;

/** Column ids whose value is the joint maximum, for the grade highlight. */
function bestCellIds(
  rows: MatrixRow[],
  columnId: string,
  average = false,
): Set<string> {
  const values = rows
    .map((row) => (average ? row.average : row.cells[columnId]))
    .filter((v): v is number => v !== null && v !== undefined);
  if (values.length === 0) return new Set();
  const max = Math.max(...values);
  return new Set(
    rows
      .filter((row) => (average ? row.average : row.cells[columnId]) === max)
      .map((row) => row.id),
  );
}

interface ResultsMatrixProps {
  title: string;
  /** Header of the first column ("Competences" / "Grades"). */
  rowHeaderLabel: string;
  rows: MatrixRow[];
  employees: GroupAnalyticsEmployee[];
  direction: SortDirection;
  onToggleDirection: () => void;
  /**
   * Grade layout: paint the best value of every column with the brand teal
   * instead of the green/yellow/red thresholds.
   */
  highlightBest?: boolean;
  testId: string;
}

export function ResultsMatrix({
  title,
  rowHeaderLabel,
  rows,
  employees,
  direction,
  onToggleDirection,
  highlightBest = false,
  testId,
}: ResultsMatrixProps) {
  const t = useTranslations("assessments");

  const bestByColumn = new Map<string, Set<string>>();
  if (highlightBest) {
    bestByColumn.set("__average__", bestCellIds(rows, "", true));
    for (const employee of employees) {
      bestByColumn.set(
        employee.employee_id,
        bestCellIds(rows, employee.employee_id),
      );
    }
  }

  function tone(columnId: string, rowId: string) {
    if (!highlightBest) return "auto" as const;
    return bestByColumn.get(columnId)?.has(rowId) ? "highlight" : "muted";
  }

  if (rows.length === 0 || employees.length === 0) {
    return (
      <div className="space-y-2" data-testid={testId}>
        <h4 className="text-sm font-medium">{title}</h4>
        <p className="text-sm text-muted-foreground" data-testid={`${testId}-empty`}>
          {t("analyticsNoData")}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2" data-testid={testId}>
      <h4 className="text-sm font-medium">{title}</h4>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b bg-muted/40">
              <th className="sticky left-0 z-10 min-w-56 bg-muted/40 px-3 py-2 text-left font-medium">
                {rowHeaderLabel}
              </th>
              <th className="min-w-28 px-3 py-2 text-left font-medium">
                <button
                  type="button"
                  onClick={onToggleDirection}
                  className="inline-flex items-center gap-1 hover:text-foreground"
                  data-testid={`${testId}-sort`}
                >
                  {t("analyticsAverage")}
                  {direction === "asc" ? (
                    <ArrowUp className="h-3 w-3" />
                  ) : (
                    <ArrowDown className="h-3 w-3" />
                  )}
                </button>
              </th>
              {employees.map((employee) => {
                const division = employee.division_name ?? "";
                const truncated = division.length > DIVISION_MAX_CHARS;
                const shortDivision = truncated
                  ? `${division.slice(0, DIVISION_MAX_CHARS)}…`
                  : division;
                return (
                  <th
                    key={employee.employee_id}
                    className="min-w-40 px-3 py-2 text-left font-normal align-top"
                    data-testid={`${testId}-column-${employee.employee_id}`}
                  >
                    <div className="space-y-1">
                      <div className="truncate text-xs font-medium">
                        {employee.full_name}
                      </div>
                      {division &&
                        (truncated ? (
                          <Tooltip>
                            <TooltipTrigger
                              render={
                                <span className="block truncate text-xs text-muted-foreground" />
                              }
                            >
                              {shortDivision}
                            </TooltipTrigger>
                            <TooltipContent>{division}</TooltipContent>
                          </Tooltip>
                        ) : (
                          <div className="truncate text-xs text-muted-foreground">
                            {division}
                          </div>
                        ))}
                      <div className="flex items-center gap-1">
                        <MatchPercentChip percent={employee.percent} />
                        <Tooltip>
                          <TooltipTrigger
                            render={<span className="inline-flex" tabIndex={-1} />}
                          >
                            <Link
                              href={`/assessments/${employee.assessment_id}#results`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="rounded-md p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                              aria-label={t("analyticsGoToResults")}
                              data-testid={`${testId}-open-${employee.employee_id}`}
                            >
                              <SquareArrowOutUpRight className="h-3.5 w-3.5" />
                            </Link>
                          </TooltipTrigger>
                          <TooltipContent>
                            {t("analyticsGoToResults")}
                          </TooltipContent>
                        </Tooltip>
                      </div>
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.id}
                className="border-b last:border-0"
                data-testid={`${testId}-row-${row.id}`}
              >
                <th
                  scope="row"
                  className="sticky left-0 z-10 bg-background px-3 py-2 text-left font-normal"
                >
                  {row.title}
                </th>
                <td className="px-3 py-2">
                  <MatchPercentChip
                    percent={row.average}
                    tone={tone("__average__", row.id)}
                    data-testid={`${testId}-row-${row.id}-average`}
                  />
                </td>
                {employees.map((employee) => (
                  <td key={employee.employee_id} className="px-3 py-2">
                    <MatchPercentChip
                      percent={row.cells[employee.employee_id] ?? null}
                      tone={tone(employee.employee_id, row.id)}
                      data-testid={`${testId}-cell-${row.id}-${employee.employee_id}`}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
