"use client";

import { useTranslations } from "next-intl";
import { Bar, BarChart, Cell, ResponsiveContainer, XAxis, YAxis } from "recharts";

import type { GradeAverage } from "@/lib/assessment/group-analytics";

/** Brand teal used for the best-matching grade (HRP-528 spec). */
const BEST_FILL = "#0989A5";
const OTHER_FILL = "#9CD3E0";

interface GradeMatchChartProps {
  averages: GradeAverage[];
  bestGradeIds: string[];
}

/** Average match per grade — "Target position: All grades" only. */
export function GradeMatchChart({
  averages,
  bestGradeIds,
}: GradeMatchChartProps) {
  const t = useTranslations("assessments");
  const data = averages.filter((a) => a.percent !== null);

  if (data.length === 0) {
    return (
      <p
        className="text-sm text-muted-foreground"
        data-testid="group-analytics-grade-chart-empty"
      >
        {t("analyticsNoData")}
      </p>
    );
  }

  return (
    <div className="h-56" data-testid="group-analytics-grade-chart">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <XAxis dataKey="title" tick={{ fontSize: 12 }} />
          <YAxis
            domain={[0, 100]}
            tickFormatter={(v: number) => `${v}%`}
            tick={{ fontSize: 12 }}
          />
          <Bar dataKey="percent" radius={[4, 4, 0, 0]} maxBarSize={72}>
            {data.map((entry) => (
              <Cell
                key={entry.grade_id}
                fill={
                  bestGradeIds.includes(entry.grade_id) ? BEST_FILL : OTHER_FILL
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
