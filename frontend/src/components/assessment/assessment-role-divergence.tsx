"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { api } from "@/lib/api";
import type { DetailedResultsResponse } from "@/lib/types";
import { roleLabel } from "@/components/assessment/assessment-detailed-results";
import {
  comparedToManager,
  orderRoles,
  overallDelta as meanOfRowDeltas,
  selfDelta,
} from "@/components/assessment/role-divergence-math";

/** A gap this wide is the thing the reviewer is meant to look at. */
const AMBER_THRESHOLD = 15;

const amberClass = "font-medium text-amber-600 dark:text-amber-500";

export interface AssessmentRoleDivergenceProps {
  assessmentId: string;
  /** Same gate as the Results card: privileged viewer, results present. */
  visible: boolean;
  /** Bumped by the parent after a calibration save / cancel — calibrated
   *  indicators change the role averages, so the block has to refetch. */
  refreshKey: number;
}

/**
 * HRP-715: self vs manager, per competence, above the results table — so
 * the gap is on screen while the assessment sits in On review and the
 * reviewer still has to decide. The per-indicator Detailed results card
 * below stays as it was; this is the competence-level summary of the same
 * numbers, and it reads them from the same endpoint.
 */
export function AssessmentRoleDivergence({
  assessmentId,
  visible,
  refreshKey,
}: AssessmentRoleDivergenceProps) {
  const t = useTranslations("assessments");
  const [data, setData] = useState<DetailedResultsResponse | null>(null);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    api
      .get<DetailedResultsResponse>(`/assessments/${assessmentId}/detailed-results`)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      // Losing this costs the reviewer a summary, not the page — the
      // Detailed results card below reports load errors already.
      .catch(() => {
        if (!cancelled) setData(null);
      });
    return () => {
      cancelled = true;
    };
  }, [assessmentId, visible, refreshKey]);

  const overall = data?.role_percents_overall ?? {};
  const roles = orderRoles(Object.keys(overall));
  const competences = data?.competences ?? [];
  // Rows first: each one needs both sides, so averaging their deltas keeps
  // a competence only one side answered out of the headline.
  const rows = competences
    .map((c) => ({ competence: c, delta: selfDelta(c.role_percents ?? {}) }))
    .filter(
      (row): row is { competence: (typeof competences)[number]; delta: number } =>
        row.delta !== null,
    );
  const rowPercents = rows.map((row) => row.competence.role_percents ?? {});
  const overallDelta = meanOfRowDeltas(rowPercents);
  // A single role means a self-assessment (or only one side finished):
  // nothing to diverge from.
  if (!visible || roles.length < 2 || overallDelta === null) return null;

  const points = Math.abs(overallDelta);
  // Wording follows the rows the headline was built from: a competence the
  // manager skipped fell back to the other raters, so "vs manager" would
  // describe a number the manager only partly produced.
  const vsManager = comparedToManager(rowPercents);
  const overallText = vsManager
    ? overallDelta === 0
      ? t("divergenceOverallEqualManager")
      : overallDelta > 0
        ? t("divergenceOverallHigherManager", { points })
        : t("divergenceOverallLowerManager", { points })
    : overallDelta === 0
      ? t("divergenceOverallEqualOthers")
      : overallDelta > 0
        ? t("divergenceOverallHigherOthers", { points })
        : t("divergenceOverallLowerOthers", { points });

  return (
    <div
      className="mb-4 rounded-lg border p-3"
      data-testid="assessment-role-divergence"
    >
      <p className="mb-2 text-sm font-medium">{t("divergenceTitle")}</p>
      <div className="flex items-baseline gap-3 border-b pb-1 text-xs text-muted-foreground">
        <span className="flex-1" />
        {roles.map((role) => (
          <span key={role} className="w-20 shrink-0 text-right">
            {roleLabel(t, role)}
          </span>
        ))}
        <span className="w-16 shrink-0 text-right">{t("divergenceDelta")}</span>
      </div>
      <div className="divide-y">
        {rows.map(({ competence: c, delta: rowDelta }) => {
          const percents = c.role_percents ?? {};
          return (
            <div
              key={c.competence_id}
              className="flex items-baseline gap-3 py-1 text-sm"
              data-testid={`assessment-role-divergence-row-${c.competence_id}`}
            >
              <span className="flex-1 truncate">{c.competence_title}</span>
              {roles.map((role) => (
                <span
                  key={role}
                  className="w-20 shrink-0 text-right tabular-nums"
                >
                  {role in percents ? `${percents[role]}%` : "—"}
                </span>
              ))}
              <span
                className={`w-16 shrink-0 text-right tabular-nums ${
                  Math.abs(rowDelta) >= AMBER_THRESHOLD
                    ? amberClass
                    : "text-muted-foreground"
                }`}
              >
                {rowDelta > 0 ? `+${rowDelta}` : rowDelta}
              </span>
            </div>
          );
        })}
      </div>
      <p
        className={`mt-2 text-sm ${
          points >= AMBER_THRESHOLD ? amberClass : "text-muted-foreground"
        }`}
        data-testid="assessment-role-divergence-overall"
      >
        {overallText}
      </p>
    </div>
  );
}
