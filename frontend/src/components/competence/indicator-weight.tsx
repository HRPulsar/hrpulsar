"use client";

import { useEffect, useRef, useState } from "react";
import { Gauge, Info } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface Props {
  value: number;
  editable: boolean;
  testIdPrefix: string;
  /** Persist a new weight. Caller handles API + toast. */
  onChange?: (next: number) => Promise<void>;
}

const MIN = 0;
const MAX = 5;

const TOOLTIP_TEXT =
  "Weight determines how strongly this indicator contributes to the overall level assessment. 0 = informational only (not counted). 1 = standard weight. 2–5 = emphasized; counts proportionally more.";

const ZERO_HINT =
  "This indicator is informational only and doesn't count toward scoring.";

/**
 * Semantic display + inline editor for indicator weight.
 *
 * The compact label replaces the legacy "w 1" abbreviation, which gave
 * the user no signal as to what the number meant. Click-to-edit keeps
 * weight-tuning fast when configuring dozens of indicators across a
 * competence.
 */
export function IndicatorWeight({ value, editable, testIdPrefix, onChange }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string>(String(value));
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!editing) setDraft(String(value));
  }, [value, editing]);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  const isZero = value === 0;

  async function commit() {
    // Guard against the Enter→onBlur double-fire: pressing Enter calls
    // commit() which flips editing=false; that re-render unmounts the
    // input and the browser fires onBlur on the disappearing node,
    // which would queue commit() a second time. setSaving=true makes
    // the second invocation no-op until the first PUT resolves.
    if (saving) return;
    const next = Number(draft);
    if (!Number.isFinite(next)) {
      setDraft(String(value));
      setEditing(false);
      return;
    }
    const clamped = Math.max(MIN, Math.min(MAX, Math.trunc(next)));
    if (clamped === value) {
      setDraft(String(value));
      setEditing(false);
      return;
    }
    if (!onChange) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onChange(clamped);
    } finally {
      setSaving(false);
      setEditing(false);
    }
  }

  if (editing && editable) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-md border border-input bg-background px-1.5 py-0.5"
        data-testid={`${testIdPrefix}-edit`}
      >
        <Gauge className="size-3.5 text-muted-foreground" aria-hidden />
        <span className="text-xs text-muted-foreground">Weight:</span>
        <input
          ref={inputRef}
          type="number"
          inputMode="numeric"
          min={MIN}
          max={MAX}
          value={draft}
          disabled={saving}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void commit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              setDraft(String(value));
              setEditing(false);
            }
          }}
          className="h-5 w-12 rounded bg-transparent text-xs focus:outline-none"
          data-testid={`${testIdPrefix}-input`}
        />
      </span>
    );
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs",
        isZero ? "text-muted-foreground" : "text-foreground/80",
      )}
      data-testid={testIdPrefix}
    >
      <Gauge
        className={cn("size-3.5", isZero ? "text-muted-foreground/60" : "text-muted-foreground")}
        aria-hidden
      />
      <span className="hidden sm:inline text-muted-foreground">Weight:</span>
      <button
        type="button"
        disabled={!editable}
        onClick={() => editable && setEditing(true)}
        className={cn(
          "tabular-nums",
          editable && "rounded px-0.5 hover:bg-muted/60 focus:bg-muted/60 focus:outline-none",
        )}
        data-testid={`${testIdPrefix}-value`}
        aria-label={`Weight ${value}${editable ? " — click to edit" : ""}`}
      >
        {value}
      </button>
      {isZero && (
        <Badge
          variant="outline"
          className="ml-0.5 h-4 px-1 text-[10px] font-normal text-muted-foreground"
          data-testid={`${testIdPrefix}-informational-badge`}
        >
          informational
        </Badge>
      )}
      <Tooltip>
        <TooltipTrigger
          render={
            <span
              tabIndex={0}
              className="inline-flex cursor-help text-muted-foreground/70 hover:text-muted-foreground"
              data-testid={`${testIdPrefix}-info`}
              aria-label="Weight explanation"
            />
          }
        >
          <Info className="size-3" />
        </TooltipTrigger>
        <TooltipContent
          className="max-w-xs"
          data-testid={`${testIdPrefix}-tooltip`}
        >
          {isZero ? ZERO_HINT : TOOLTIP_TEXT}
        </TooltipContent>
      </Tooltip>
    </span>
  );
}
