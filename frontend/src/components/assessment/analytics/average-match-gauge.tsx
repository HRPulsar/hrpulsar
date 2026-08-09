"use client";

import { matchPercentColor } from "@/components/assessment/match-percent-chip";

const ARC_STROKE = {
  green: "stroke-green-500",
  yellow: "stroke-yellow-500",
  red: "stroke-red-500",
} as const;

/**
 * Half-circle gauge for the average match level.
 *
 * `pathLength={100}` rescales the arc so the dash array can be written
 * directly in percent, independent of the actual radius.
 */
export function AverageMatchGauge({
  percent,
  "data-testid": testId,
}: {
  percent: number | null;
  "data-testid"?: string;
}) {
  const value = percent ?? 0;
  const stroke = percent === null ? "stroke-muted" : ARC_STROKE[matchPercentColor(value)];

  return (
    <div className="flex items-center gap-3" data-testid={testId}>
      <span className="text-2xl font-semibold tabular-nums">
        {percent === null ? "—" : `${percent}%`}
      </span>
      <svg
        viewBox="0 0 100 56"
        className="h-12 w-20"
        role="presentation"
        aria-hidden="true"
      >
        <path
          d="M 8 50 A 42 42 0 0 1 92 50"
          fill="none"
          strokeWidth={10}
          strokeLinecap="round"
          className="stroke-muted"
          pathLength={100}
        />
        {percent !== null && (
          <path
            d="M 8 50 A 42 42 0 0 1 92 50"
            fill="none"
            strokeWidth={10}
            strokeLinecap="round"
            className={stroke}
            pathLength={100}
            strokeDasharray={`${value} 100`}
          />
        )}
      </svg>
    </div>
  );
}
