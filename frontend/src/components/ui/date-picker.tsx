"use client";

// HRP-152: custom date picker.
//
// Native `<input type="date">` ignores `lang="en"`: Safari and Chrome
// render the calendar in the browser/OS locale, so a non-English user
// sees a localised mask even though the rest of the app is English.
// This component replaces the native picker with a popover-driven
// calendar that always renders the month/day labels in English and
// always emits `yyyy-mm-dd` strings — matching `formatDate` in
// `lib/date-format.ts`.

import * as React from "react";
import * as Popover from "@radix-ui/react-popover";
import { Calendar as CalendarIcon, ChevronLeft, ChevronRight } from "lucide-react";

import { Input } from "@/components/ui/input";
import { DATE_PLACEHOLDER } from "@/lib/date-format";
import {
  applyDateMask,
  buildMonthGrid,
  isSameDay,
  isWithinBounds,
  parseIso,
  startOfMonth,
  toIso,
} from "@/lib/date-picker-helpers";
import { cn } from "@/lib/utils";

interface DatePickerProps {
  /** ISO `yyyy-mm-dd` value, or "" for empty. */
  value: string;
  onChange: (value: string) => void;
  min?: string;
  max?: string;
  disabled?: boolean;
  /** HRP-335: focus the input on mount (inline pencil editors). */
  autoFocus?: boolean;
  /** HRP-335: Escape hook for inline editors (close without saving). */
  onCancel?: () => void;
  placeholder?: string;
  className?: string;
  /** HRP-335: extra classes for the inner input (inline-edit sizing). */
  inputClassName?: string;
  id?: string;
  ariaLabel?: string;
  "data-testid"?: string;
  /** When true (default), tying `value=""` to a non-empty mask shows the
   * placeholder. Set false if you need the input to render today's date
   * even when the bound value is empty. */
  clearable?: boolean;
}

// HRP-152 REDO: Sunday-first layout per QA review screenshots.
const WEEKDAY_LABELS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
const MONTH_LABELS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];
const MONTH_SHORT = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];
const YEAR_GRID_SIZE = 12;

type ViewMode = "days" | "months" | "years";


export function DatePicker({
  value,
  onChange,
  min,
  max,
  disabled,
  autoFocus,
  onCancel,
  placeholder = DATE_PLACEHOLDER,
  className,
  inputClassName,
  id,
  ariaLabel,
  "data-testid": testId,
  clearable = true,
}: DatePickerProps) {
  const [open, setOpen] = React.useState(false);
  const selected = React.useMemo(() => parseIso(value), [value]);
  const [viewMonth, setViewMonth] = React.useState<Date>(
    () => startOfMonth(selected ?? new Date()),
  );
  const [viewMode, setViewMode] = React.useState<ViewMode>("days");
  const [draft, setDraft] = React.useState<string>(value);

  // Keep the visible input in sync when the bound value changes from outside.
  React.useEffect(() => {
    setDraft(value);
  }, [value]);

  // Reset view to the selected month every time the popover opens.
  React.useEffect(() => {
    if (open) {
      setViewMonth(startOfMonth(selected ?? new Date()));
      setViewMode("days");
    }
  }, [open, selected]);

  function commitDraft(next: string) {
    if (next === "") {
      if (clearable) onChange("");
      return;
    }
    const parsed = parseIso(next);
    if (!parsed) {
      // Revert the visible mask to the last bound value.
      setDraft(value);
      return;
    }
    const iso = toIso(parsed);
    if (!isWithinBounds(iso, min, max)) {
      setDraft(value);
      return;
    }
    onChange(iso);
  }

  function selectDay(day: Date) {
    const iso = toIso(day);
    if (!isWithinBounds(iso, min, max)) return;
    onChange(iso);
    setDraft(iso);
    setOpen(false);
  }

  function shiftMonth(delta: number) {
    setViewMonth((prev) => {
      const next = new Date(prev);
      next.setMonth(prev.getMonth() + delta);
      return next;
    });
  }

  function shiftYear(delta: number) {
    setViewMonth((prev) => {
      const next = new Date(prev);
      next.setFullYear(prev.getFullYear() + delta);
      return next;
    });
  }

  function pickMonth(monthIndex: number) {
    setViewMonth((prev) => new Date(prev.getFullYear(), monthIndex, 1));
    setViewMode("days");
  }

  function pickYear(year: number) {
    setViewMonth((prev) => new Date(year, prev.getMonth(), 1));
    setViewMode("months");
  }

  const days = React.useMemo(() => buildMonthGrid(viewMonth), [viewMonth]);
  const monthLabel = MONTH_LABELS[viewMonth.getMonth()];
  const yearLabel = String(viewMonth.getFullYear());
  // HRP-152 REDO: 12-year grid anchored on a multiple of 12 so the
  // current year always lands in a stable slot — same convention every
  // modern calendar uses.
  const yearGridStart =
    Math.floor(viewMonth.getFullYear() / YEAR_GRID_SIZE) * YEAR_GRID_SIZE;

  return (
    <Popover.Root open={open} onOpenChange={(next) => !disabled && setOpen(next)}>
      <div className={cn("relative w-full", className)}>
        <Input
          id={id}
          value={draft}
          // HRP-152 REDO: digit-only mask. Each keystroke is filtered to
          // ``\d`` and the dashes are re-inserted automatically (see
          // applyDateMask) so the recruiter never has to hit ``-`` and
          // never sees a stray letter sneak in. inputMode="numeric" keeps
          // the mobile keypad numeric.
          onChange={(e) => setDraft(applyDateMask(e.target.value))}
          onBlur={() => commitDraft(draft)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commitDraft(draft);
              setOpen(false);
            } else if (e.key === "Escape" && onCancel) {
              e.preventDefault();
              onCancel();
            }
          }}
          placeholder={placeholder}
          disabled={disabled}
          autoFocus={autoFocus}
          aria-label={ariaLabel}
          data-testid={testId}
          autoComplete="off"
          inputMode="numeric"
          pattern="\d{4}-\d{2}-\d{2}"
          maxLength={10}
          className={cn("pr-9", inputClassName)}
        />
        <Popover.Trigger asChild>
          <button
            type="button"
            tabIndex={-1}
            disabled={disabled}
            aria-label="Open calendar"
            data-testid={testId ? `${testId}-trigger` : undefined}
            className={cn(
              "absolute inset-y-0 right-0 flex items-center px-2 text-muted-foreground transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50",
            )}
          >
            <CalendarIcon className="h-4 w-4" />
          </button>
        </Popover.Trigger>
      </div>

      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={6}
          className="z-50 rounded-lg border bg-popover p-3 shadow-md outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0"
        >
          {/* HRP-152 REDO: header carries two clickable labels that flip
              the calendar to month/year pickers. Arrows pre-shift by one
              unit of the active grid (month/year/decade). */}
          <div className="flex items-center justify-between gap-2 pb-2">
            <button
              type="button"
              onClick={() => {
                if (viewMode === "days") shiftMonth(-1);
                else if (viewMode === "months") shiftYear(-1);
                else shiftYear(-YEAR_GRID_SIZE);
              }}
              className="rounded p-1 hover:bg-accent"
              aria-label="Previous"
              data-testid={testId ? `${testId}-prev` : undefined}
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <div className="flex items-center gap-1 text-sm font-medium">
              {viewMode === "days" && (
                <>
                  <button
                    type="button"
                    onClick={() => setViewMode("months")}
                    className="rounded px-1.5 py-0.5 hover:bg-accent"
                    data-testid={testId ? `${testId}-month-trigger` : undefined}
                  >
                    {monthLabel}
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewMode("years")}
                    className="rounded px-1.5 py-0.5 hover:bg-accent"
                    data-testid={testId ? `${testId}-year-trigger` : undefined}
                  >
                    {yearLabel}
                  </button>
                </>
              )}
              {viewMode === "months" && (
                <button
                  type="button"
                  onClick={() => setViewMode("years")}
                  className="rounded px-1.5 py-0.5 hover:bg-accent"
                  data-testid={testId ? `${testId}-year-trigger` : undefined}
                >
                  {yearLabel}
                </button>
              )}
              {viewMode === "years" && (
                <span className="px-1.5 py-0.5">
                  {yearGridStart}–{yearGridStart + YEAR_GRID_SIZE - 1}
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={() => {
                if (viewMode === "days") shiftMonth(1);
                else if (viewMode === "months") shiftYear(1);
                else shiftYear(YEAR_GRID_SIZE);
              }}
              className="rounded p-1 hover:bg-accent"
              aria-label="Next"
              data-testid={testId ? `${testId}-next` : undefined}
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
          {viewMode === "days" && (
            <>
              <div className="grid grid-cols-7 gap-1 text-center text-[11px] uppercase tracking-wide text-muted-foreground">
                {WEEKDAY_LABELS.map((label) => (
                  <div key={label} className="py-1">
                    {label}
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-7 gap-1">
                {days.map((day) => {
                  const iso = toIso(day);
                  const inMonth = day.getMonth() === viewMonth.getMonth();
                  const isSelected = selected != null && isSameDay(day, selected);
                  const isToday = isSameDay(day, new Date());
                  const bounded = isWithinBounds(iso, min, max);
                  return (
                    <button
                      type="button"
                      key={iso}
                      onClick={() => selectDay(day)}
                      disabled={!bounded}
                      data-testid={
                        testId ? `${testId}-day-${iso}` : undefined
                      }
                      aria-pressed={isSelected}
                      aria-label={iso}
                      className={cn(
                        "h-8 w-8 rounded text-sm transition-colors",
                        !inMonth && "text-muted-foreground/40",
                        inMonth && !isSelected && "hover:bg-accent hover:text-accent-foreground",
                        isSelected && "bg-primary text-primary-foreground",
                        isToday && !isSelected && "ring-1 ring-inset ring-ring/40",
                        !bounded && "cursor-not-allowed opacity-30 hover:bg-transparent",
                      )}
                    >
                      {day.getDate()}
                    </button>
                  );
                })}
              </div>
            </>
          )}
          {viewMode === "months" && (
            <div className="grid grid-cols-3 gap-2">
              {MONTH_SHORT.map((label, idx) => {
                const isSelected =
                  selected != null &&
                  selected.getFullYear() === viewMonth.getFullYear() &&
                  selected.getMonth() === idx;
                return (
                  <button
                    type="button"
                    key={label}
                    onClick={() => pickMonth(idx)}
                    data-testid={
                      testId ? `${testId}-month-${idx + 1}` : undefined
                    }
                    aria-pressed={isSelected}
                    className={cn(
                      "h-9 rounded text-sm transition-colors hover:bg-accent hover:text-accent-foreground",
                      isSelected && "bg-primary text-primary-foreground hover:bg-primary",
                    )}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          )}
          {viewMode === "years" && (
            <div className="grid grid-cols-3 gap-2">
              {Array.from({ length: YEAR_GRID_SIZE }, (_, i) => yearGridStart + i).map(
                (year) => {
                  const isSelected =
                    selected != null && selected.getFullYear() === year;
                  return (
                    <button
                      type="button"
                      key={year}
                      onClick={() => pickYear(year)}
                      data-testid={testId ? `${testId}-year-${year}` : undefined}
                      aria-pressed={isSelected}
                      className={cn(
                        "h-9 rounded text-sm transition-colors hover:bg-accent hover:text-accent-foreground",
                        isSelected && "bg-primary text-primary-foreground hover:bg-primary",
                      )}
                    >
                      {year}
                    </button>
                  );
                },
              )}
            </div>
          )}
          {clearable && value && (
            <div className="mt-2 flex justify-end">
              <button
                type="button"
                onClick={() => {
                  onChange("");
                  setDraft("");
                  setOpen(false);
                }}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                Clear
              </button>
            </div>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
