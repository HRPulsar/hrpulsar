"use client";

// W6: a step's yearly hours are hours_per_run x runs_per_year - the model's
// estimate, corrected by the company. One pair of inputs for the Steps tab
// row and the hours editor of the Coverage tab. The draft is text: a
// controlled number would eat the "." while the user types "0.5".

import { Input } from "@/components/ui/input";
import { HOURS_PER_RUN_MAX, RUNS_PER_YEAR_MAX } from "@/lib/api/work";

// The backend's own bounds (`work/models.py`): anything it accepts must
// leave the browser, so these may not be narrower.
export const HOURS_PER_RUN_MIN = 0.01;
export const RUNS_PER_YEAR_MIN = 1;

export interface HoursDraft {
  hours: string;
  runs: string;
}

type Hours = { hours_per_run: number | null; runs_per_year: number | null };

export function draftOf(step: Hours): HoursDraft {
  return {
    hours: step.hours_per_run === null ? "" : String(step.hours_per_run),
    runs: step.runs_per_year === null ? "" : String(step.runs_per_year),
  };
}

/** Empty or unparsable text is "not set". */
export function parseHours(draft: HoursDraft): Hours {
  const hours = Number.parseFloat(draft.hours);
  const runs = Number.parseInt(draft.runs, 10);
  return {
    hours_per_run: Number.isFinite(hours) ? hours : null,
    runs_per_year: Number.isFinite(runs) ? runs : null,
  };
}

/** True when a typed number is outside what the backend accepts, so the
 * caller can keep the PATCH (and its 422 toast on every blur) at home.
 * "Not set" is always allowed. */
export function hoursOutOfRange(draft: HoursDraft): boolean {
  const { hours_per_run, runs_per_year } = parseHours(draft);
  return (
    (hours_per_run !== null &&
      (hours_per_run < HOURS_PER_RUN_MIN || hours_per_run > HOURS_PER_RUN_MAX)) ||
    (runs_per_year !== null &&
      (runs_per_year < RUNS_PER_YEAR_MIN || runs_per_year > RUNS_PER_YEAR_MAX))
  );
}

export function HoursFields({
  value,
  disabled = false,
  testId,
  labels,
  onChange,
  onBlur,
}: {
  value: HoursDraft;
  disabled?: boolean;
  /** Prefix: the inputs are `${testId}-input-hours` and `${testId}-input-runs`. */
  testId: string;
  labels: { hours: string; runs: string };
  onChange: (next: HoursDraft) => void;
  onBlur?: () => void;
}) {
  return (
    <>
      <NumberField
        label={labels.hours}
        value={value.hours}
        min={HOURS_PER_RUN_MIN}
        max={HOURS_PER_RUN_MAX}
        step="any"
        disabled={disabled}
        testId={`${testId}-input-hours`}
        onChange={(hours) => onChange({ ...value, hours })}
        onBlur={onBlur}
      />
      <NumberField
        label={labels.runs}
        value={value.runs}
        min={RUNS_PER_YEAR_MIN}
        max={RUNS_PER_YEAR_MAX}
        step={1}
        disabled={disabled}
        testId={`${testId}-input-runs`}
        onChange={(runs) => onChange({ ...value, runs })}
        onBlur={onBlur}
      />
    </>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step,
  disabled,
  testId,
  onChange,
  onBlur,
}: {
  label: string;
  value: string;
  min: number;
  max: number;
  step: number | "any";
  disabled: boolean;
  testId: string;
  onChange: (raw: string) => void;
  onBlur?: () => void;
}) {
  return (
    <label className="flex min-w-36 flex-col gap-1 text-xs text-muted-foreground">
      <span>{label}</span>
      <Input
        type="number"
        inputMode="decimal"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        className="h-8 w-full text-sm"
        data-testid={testId}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onBlur}
      />
    </label>
  );
}
