"use client";

import { forwardRef, useState } from "react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

interface ScoreCellProps {
  value: number | null;
  aiValue?: number | null;
  /** Editable by the current user (false → read-only, e.g. someone else's score). */
  editable?: boolean;
  dirty?: boolean;
  pending?: boolean;
  divergenceThreshold?: number;
  min?: number;
  max?: number;
  step?: number;
  /** Row/col coordinates so CanvasGrid can implement arrow-key cell navigation. */
  dataRow?: number;
  dataCol?: number;
  onCommit: (next: number | null) => void;
  onFocus?: () => void;
  "data-testid"?: string;
  ariaLabel?: string;
}

export const ScoreCell = forwardRef<HTMLDivElement, ScoreCellProps>(
  function ScoreCell(
    {
      value,
      aiValue,
      editable = true,
      dirty,
      pending,
      divergenceThreshold = 1,
      min = 0,
      max = 5,
      step = 0.5,
      dataRow,
      dataCol,
      onCommit,
      onFocus,
      "data-testid": dataTestId,
      ariaLabel,
    },
    ref,
  ) {
    const displayString =
      value === null || value === undefined ? "" : String(value);
    const [draftOverride, setDraftOverride] = useState<string | null>(null);
    const editing = draftOverride !== null;
    const draft = draftOverride ?? displayString;

    function commit() {
      const trimmed = draft.trim();
      if (trimmed === "") {
        onCommit(null);
        setDraftOverride(null);
        return;
      }
      const numeric = Number(trimmed.replace(",", "."));
      if (!Number.isFinite(numeric)) {
        toast.error(`Not a number: "${trimmed}"`);
        return;
      }
      if (numeric < min || numeric > max) {
        toast.error(`Score must be between ${min} and ${max}`);
        return;
      }
      onCommit(numeric);
      setDraftOverride(null);
    }

    const divergence =
      aiValue !== null && aiValue !== undefined && value !== null
        ? Math.abs(aiValue - value) >= divergenceThreshold
        : false;

    const display =
      value === null || value === undefined ? (
        <span className="text-muted-foreground/50">—</span>
      ) : (
        value.toFixed(step < 1 ? 1 : 0)
      );

    return (
      <div
        ref={ref}
        tabIndex={editable ? 0 : -1}
        data-testid={dataTestId}
        data-row={dataRow}
        data-col={dataCol}
        aria-label={ariaLabel}
        role={editable ? "spinbutton" : "presentation"}
        aria-readonly={!editable}
        onFocus={onFocus}
        onKeyDown={(e) => {
          if (!editable) return;
          if (editing) {
            if (e.key === "Enter") {
              e.preventDefault();
              commit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              setDraftOverride(null);
            }
            return;
          }
          if (e.key === "Enter" || e.key === "F2") {
            e.preventDefault();
            setDraftOverride(displayString);
            return;
          }
          if (e.key === "Backspace" || e.key === "Delete") {
            e.preventDefault();
            onCommit(null);
            return;
          }
          if (/^[0-9]$/.test(e.key)) {
            setDraftOverride(e.key);
            e.preventDefault();
          }
        }}
        onDoubleClick={() => editable && setDraftOverride(displayString)}
        className={cn(
          "relative flex h-9 min-w-[3.5rem] cursor-text items-center justify-center border border-border/40 px-2 font-mono text-xs transition-colors",
          editable
            ? "hover:bg-muted/40 focus:bg-accent/10 focus:outline-2 focus:outline-accent"
            : "cursor-default text-muted-foreground",
          dirty && "bg-[color-mix(in_oklch,var(--rec-data-partial)_15%,transparent)]",
          pending && "bg-[color-mix(in_oklch,var(--rec-data-partial)_25%,transparent)] animate-pulse",
        )}
      >
        {editing ? (
          <input
            autoFocus
            type="text"
            inputMode="decimal"
            value={draft}
            onChange={(e) => setDraftOverride(e.target.value)}
            onBlur={commit}
            className="w-full bg-transparent text-center font-mono text-xs outline-none"
            data-testid={dataTestId ? `${dataTestId}-input` : undefined}
          />
        ) : (
          <span>{display}</span>
        )}
        {divergence && (
          <span
            className="absolute right-0.5 top-0.5 size-1.5 rounded-full bg-[var(--rec-divergence)]"
            aria-label="AI/human divergence"
            title="AI/human divergence ≥ threshold"
          />
        )}
      </div>
    );
  },
);
