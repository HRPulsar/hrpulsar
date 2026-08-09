"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowDown, ArrowUp, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { AverageMatchGauge } from "@/components/assessment/analytics/average-match-gauge";
import { CompetenceHighlightCard } from "@/components/assessment/analytics/competence-highlight-card";
import { CompetenceResultsTree } from "@/components/assessment/analytics/competence-results-tree";
import { EmployeeHighlightPlate } from "@/components/assessment/analytics/employee-highlight-plate";
import { GradeMatchChart } from "@/components/assessment/analytics/grade-match-chart";
import { ResultsMatrix } from "@/components/assessment/analytics/results-matrix";
import { MatchPercentChip } from "@/components/assessment/match-percent-chip";
import { MultiSelectSearchFilter } from "@/components/multi-select-search-filter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import {
  averageMatchLevel,
  bestGradeIds,
  competenceAverages,
  competenceMatrixRows,
  EMPTY_FILTERS,
  employeesAtRisk,
  filterEmployees,
  gradeAverages,
  gradeMatrixRows,
  sortEmployeesByName,
  sortEmployeesByPercent,
  topPerformers,
  type AnalyticsFilters,
  type SortDirection,
} from "@/lib/assessment/group-analytics";
import { dictionaryItemLabel } from "@/lib/reference-labels";
import type {
  GroupAnalyticsGradeRef,
  GroupAnalyticsResponse,
} from "@/lib/types";

/**
 * HRP-528: the Analytics block on a mass assessment.
 *
 * Renders only once at least one child assessment is Done — the endpoint
 * reports `done_count`, and everything below is built from those children
 * alone. The endpoint carries the same scope guard as the group-detail route,
 * so a caller who cannot see the group gets a 404 and the block silently
 * stays hidden rather than breaking the rest of the page.
 */
export function GroupAnalytics({ groupId }: { groupId: string }) {
  const t = useTranslations("assessments");
  const tRef = useTranslations("reference");

  const [data, setData] = useState<GroupAnalyticsResponse | null>(null);
  const [filters, setFilters] = useState<AnalyticsFilters>(EMPTY_FILTERS);
  const [matrixDirection, setMatrixDirection] = useState<SortDirection>("asc");
  const [tableDirection, setTableDirection] = useState<SortDirection>("asc");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const payload = await api.get<GroupAnalyticsResponse>(
          `/assessment-groups/${groupId}/analytics`,
        );
        if (!cancelled) setData(payload);
      } catch {
        // Forbidden for employees, and a transient failure must not break
        // the rest of the group page — the block just stays hidden.
        if (!cancelled) setData(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [groupId]);

  const gradeTitle = useCallback(
    (grade: GroupAnalyticsGradeRef) =>
      grade.grade_title
        ? dictionaryItemLabel(tRef, {
            type: "grade",
            title: grade.grade_title,
            i18n_key: grade.grade_i18n_key,
          })
        : "—",
    [tRef],
  );

  const employees = useMemo(() => data?.employees ?? [], [data]);
  const filtered = useMemo(
    () => filterEmployees(employees, filters),
    [employees, filters],
  );
  const columns = useMemo(() => sortEmployeesByName(filtered), [filtered]);

  const atRisk = useMemo(() => employeesAtRisk(employees), [employees]);
  const performers = useMemo(() => topPerformers(employees), [employees]);

  const isAllGrades = data?.is_all_grades ?? false;
  const isCurrentPositions = data?.criteria_type === "current_positions";

  const gradeRows = useMemo(
    () =>
      data
        ? gradeAverages(filtered, data.grades, gradeTitle)
        : [],
    [data, filtered, gradeTitle],
  );
  const bestGrades = useMemo(() => bestGradeIds(gradeRows), [gradeRows]);

  const summaryGradeRows = useMemo(
    () => (data ? gradeAverages(employees, data.grades, gradeTitle) : []),
    [data, employees, gradeTitle],
  );
  const summaryBestGrades = useMemo(
    () => bestGradeIds(summaryGradeRows),
    [summaryGradeRows],
  );

  const competenceRows = useMemo(
    () =>
      data
        ? competenceMatrixRows(
            columns,
            data.competences,
            filters.competences,
            matrixDirection,
          )
        : [],
    [columns, data, filters.competences, matrixDirection],
  );

  const gradeMatrix = useMemo(
    () =>
      data
        ? gradeMatrixRows(columns, data.grades, gradeTitle, matrixDirection)
        : [],
    [columns, data, gradeTitle, matrixDirection],
  );

  const treeAverages = useMemo(
    () => competenceAverages(employees),
    [employees],
  );

  const tableRows = useMemo(
    () => sortEmployeesByPercent(filtered, tableDirection),
    [filtered, tableDirection],
  );

  if (!data || data.done_count === 0) return null;

  const average = averageMatchLevel(filtered, filters.competences);

  return (
    <Card data-testid="group-analytics-card">
      <CardHeader>
        <CardTitle className="text-base">{t("analytics")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {(data.growth_zones.length > 0 || data.top_competences.length > 0) && (
          <div className="grid gap-4 md:grid-cols-2">
            {data.growth_zones.length > 0 && (
              <CompetenceHighlightCard
                variant="growth"
                items={data.growth_zones}
              />
            )}
            {data.top_competences.length > 0 && (
              <CompetenceHighlightCard
                variant="top"
                items={data.top_competences}
              />
            )}
          </div>
        )}

        {/* "All grades" has no single overall result per employee, so the
            at-risk / top-performer split does not apply there. */}
        {!isAllGrades && (
          <div className="grid gap-4 md:grid-cols-2">
            <EmployeeHighlightPlate variant="atRisk" employees={atRisk} />
            <EmployeeHighlightPlate
              variant="topPerformers"
              employees={performers}
            />
          </div>
        )}

        <section className="space-y-4" data-testid="group-analytics-detailed">
          <h3 className="text-sm font-semibold">
            {t("analyticsDetailedResults")}
          </h3>

          <div className="flex flex-wrap gap-2">
            <MultiSelectSearchFilter
              options={data.divisions.map((d) => ({
                value: d.division_id,
                label: d.division_name,
              }))}
              value={filters.divisions}
              onChange={(next) =>
                setFilters((prev) => ({ ...prev, divisions: next }))
              }
              placeholder={t("analyticsFilterDivisions")}
              searchPlaceholder={t("analyticsFilterSearch")}
              className="w-52"
              data-testid="group-analytics-filter-divisions"
            />
            {isCurrentPositions && (
              <MultiSelectSearchFilter
                options={data.specializations.map((s) => ({
                  value: s.specialization_id,
                  label: s.specialization_title
                    ? dictionaryItemLabel(tRef, {
                        type: "specialization",
                        title: s.specialization_title,
                        i18n_key: s.specialization_i18n_key,
                      })
                    : "—",
                }))}
                value={filters.specializations}
                onChange={(next) =>
                  setFilters((prev) => ({ ...prev, specializations: next }))
                }
                placeholder={t("analyticsFilterSpecializations")}
                searchPlaceholder={t("analyticsFilterSearch")}
                className="w-52"
                data-testid="group-analytics-filter-specializations"
              />
            )}
            {!isCurrentPositions && (
              <MultiSelectSearchFilter
                options={data.competences.map((c) => ({
                  value: c.competence_id,
                  label: c.competence_title,
                }))}
                value={filters.competences}
                onChange={(next) =>
                  setFilters((prev) => ({ ...prev, competences: next }))
                }
                placeholder={t("analyticsFilterCompetences")}
                searchPlaceholder={t("analyticsFilterSearch")}
                className="w-52"
                data-testid="group-analytics-filter-competences"
              />
            )}
            <MultiSelectSearchFilter
              options={employees.map((e) => ({
                value: e.employee_id,
                label: e.full_name ?? "—",
              }))}
              value={filters.employees}
              onChange={(next) =>
                setFilters((prev) => ({ ...prev, employees: next }))
              }
              placeholder={t("analyticsFilterEmployees")}
              searchPlaceholder={t("analyticsFilterSearch")}
              className="w-52"
              data-testid="group-analytics-filter-employees"
            />
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3">
            <div>
              <div className="text-sm font-medium">
                {t("analyticsAverageMatchLevel")}
              </div>
              <div className="text-xs text-muted-foreground">
                {t("analyticsAverageMatchLevelHint")}
              </div>
            </div>
            {isAllGrades ? (
              <div
                className="flex flex-wrap items-center gap-2"
                data-testid="group-analytics-average-grades"
              >
                {gradeRows.map((grade) => (
                  <span
                    key={grade.grade_id}
                    className="flex items-center gap-1.5 text-sm"
                  >
                    <span className="text-muted-foreground">{grade.title}</span>
                    <MatchPercentChip
                      percent={grade.percent}
                      tone={
                        bestGrades.includes(grade.grade_id)
                          ? "highlight"
                          : "muted"
                      }
                      data-testid={`group-analytics-average-grade-${grade.grade_id}`}
                    />
                  </span>
                ))}
              </div>
            ) : (
              <AverageMatchGauge
                percent={average}
                data-testid="group-analytics-average-gauge"
              />
            )}
          </div>

          {isCurrentPositions ? (
            <div
              className="overflow-x-auto rounded-lg border"
              data-testid="group-analytics-employees-table"
            >
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b bg-muted/40">
                    <th className="px-3 py-2 text-left font-medium">
                      {t("analyticsColEmployee")}
                    </th>
                    <th className="px-3 py-2 text-left font-medium">
                      {t("analyticsColDivision")}
                    </th>
                    <th className="px-3 py-2 text-left font-medium">
                      <button
                        type="button"
                        onClick={() =>
                          setTableDirection((prev) =>
                            prev === "asc" ? "desc" : "asc",
                          )
                        }
                        className="inline-flex items-center gap-1 hover:text-foreground"
                        data-testid="group-analytics-employees-sort"
                      >
                        {t("analyticsColResult")}
                        {tableDirection === "asc" ? (
                          <ArrowUp className="h-3 w-3" />
                        ) : (
                          <ArrowDown className="h-3 w-3" />
                        )}
                      </button>
                    </th>
                    <th className="w-10 px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map((employee) => (
                    <tr
                      key={employee.employee_id}
                      className="border-b last:border-0"
                      data-testid={`group-analytics-employees-row-${employee.employee_id}`}
                    >
                      <td className="px-3 py-2">
                        <div className="font-medium">{employee.full_name}</div>
                        {employee.position_title && (
                          <div className="text-xs text-muted-foreground">
                            {employee.position_title}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {employee.division_name ?? "—"}
                      </td>
                      <td className="px-3 py-2">
                        <MatchPercentChip percent={employee.percent} />
                      </td>
                      <td className="px-3 py-2">
                        <Tooltip>
                          <TooltipTrigger
                            render={<span className="inline-flex" tabIndex={-1} />}
                          >
                            <Link
                              href={`/assessments/${employee.assessment_id}`}
                              className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                              aria-label={t("analyticsGoToAssessment")}
                              data-testid={`group-analytics-employees-link-${employee.employee_id}`}
                            >
                              <ChevronRight className="h-4 w-4" />
                            </Link>
                          </TooltipTrigger>
                          <TooltipContent>
                            {t("analyticsGoToAssessment")}
                          </TooltipContent>
                        </Tooltip>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <ResultsMatrix
              title={t("analyticsCompetenceMatrix")}
              rowHeaderLabel={t("analyticsColCompetences")}
              rows={competenceRows}
              employees={columns}
              direction={matrixDirection}
              onToggleDirection={() =>
                setMatrixDirection((prev) => (prev === "asc" ? "desc" : "asc"))
              }
              testId="group-analytics-competence-matrix"
            />
          )}

          {isAllGrades && (
            <ResultsMatrix
              title={t("analyticsGradeMatrix")}
              rowHeaderLabel={t("analyticsColGrades")}
              rows={gradeMatrix}
              employees={columns}
              direction={matrixDirection}
              onToggleDirection={() =>
                setMatrixDirection((prev) => (prev === "asc" ? "desc" : "asc"))
              }
              highlightBest
              testId="group-analytics-grade-matrix"
            />
          )}
        </section>

        {!isCurrentPositions && (
          <section className="space-y-4" data-testid="group-analytics-summary">
            <h3 className="text-sm font-semibold">{t("analyticsSummary")}</h3>
            {isAllGrades && (
              <div className="space-y-2">
                <h4 className="text-sm font-medium">
                  {t("analyticsGradeMatchChart")}
                </h4>
                <GradeMatchChart
                  averages={summaryGradeRows}
                  bestGradeIds={summaryBestGrades}
                />
              </div>
            )}
            <div className="space-y-2">
              <h4 className="text-sm font-medium">
                {t("analyticsCompetenceTree")}
              </h4>
              <CompetenceResultsTree averages={treeAverages} />
            </div>
          </section>
        )}
      </CardContent>
    </Card>
  );
}
