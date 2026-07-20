"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import type { RefinementInput } from "@/lib/api/competence-generation";

export interface RefinementPanelProps {
  onSubmit: (input: RefinementInput) => Promise<void> | void;
  onCancel: () => void;
  /** HRP-97: prefill form from the last submitted refinement so the user
   * sees their input after drawer reopen / page refresh / Try again. */
  initialValues?: {
    general?: string | null;
    add?: string | null;
    change?: string | null;
    exclude?: string | null;
  } | null;
}

const TOOLTIPS = {
  add: "What to add — specific competences, indicators or groups missing from the current version.",
  change:
    "What to change — rewording, descriptions, indicator formatting.",
  exclude:
    "What to exclude — remove unsuitable groups, competences or indicators.",
};

const MAX_GENERAL = 4000;
const MAX_FIELD = 2000;

// Exported so the vitest suite can pin the rule without rendering the
// component (HRP-96): when re-opening a refinement that already had
// granular input, the detailed form starts expanded so the user lands on
// the same view they last submitted.
export function shouldStartExpanded(
  initialValues?: {
    general?: string | null;
    add?: string | null;
    change?: string | null;
    exclude?: string | null;
  } | null,
): boolean {
  return !!(
    initialValues?.add ||
    initialValues?.change ||
    initialValues?.exclude
  );
}

export function RefinementPanel({
  onSubmit,
  onCancel,
  initialValues,
}: RefinementPanelProps) {
  const [general, setGeneral] = useState(() => initialValues?.general ?? "");
  // Auto-expand the detailed form when any of the granular fields had
  // saved data, so the user lands on the same view they left.
  const [expanded, setExpanded] = useState(() => shouldStartExpanded(initialValues));
  const [add, setAdd] = useState(() => initialValues?.add ?? "");
  const [change, setChange] = useState(() => initialValues?.change ?? "");
  const [exclude, setExclude] = useState(() => initialValues?.exclude ?? "");
  const [submitting, setSubmitting] = useState(false);

  const hasInput = !!(
    general.trim() ||
    add.trim() ||
    change.trim() ||
    exclude.trim()
  );

  async function handleSubmit() {
    if (!hasInput) return;
    setSubmitting(true);
    try {
      await onSubmit({
        general: general.trim() || undefined,
        add: add.trim() || undefined,
        change: change.trim() || undefined,
        exclude: exclude.trim() || undefined,
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Label>General request</Label>
        <Textarea
          data-testid="compgen-refine-textarea-main"
          placeholder="Describe what needs to change in the generated result…"
          value={general}
          onChange={(e) => setGeneral(e.target.value.slice(0, MAX_GENERAL))}
          rows={4}
        />
        <p className="text-right text-xs text-muted-foreground">
          {general.length}/{MAX_GENERAL}
        </p>
      </div>

      <button
        type="button"
        data-testid={
          expanded ? "compgen-refine-btn-collapse" : "compgen-refine-btn-expand"
        }
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1 text-sm text-primary hover:underline"
      >
        {expanded ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
        {expanded ? "Collapse to single field" : "Expand to detailed form"}
      </button>

      {expanded && (
        <div className="space-y-3 rounded-md border p-3">
          <RefineField
            label="Add"
            tooltip={TOOLTIPS.add}
            value={add}
            onChange={setAdd}
            testId="compgen-refine-textarea-add"
          />
          <RefineField
            label="Change"
            tooltip={TOOLTIPS.change}
            value={change}
            onChange={setChange}
            testId="compgen-refine-textarea-change"
          />
          <RefineField
            label="Exclude"
            tooltip={TOOLTIPS.exclude}
            value={exclude}
            onChange={setExclude}
            testId="compgen-refine-textarea-exclude"
          />
        </div>
      )}

      <div className="flex justify-end gap-2 pt-1">
        <Button variant="outline" onClick={onCancel} disabled={submitting}>
          Cancel
        </Button>
        <Button
          data-testid="compgen-refine-btn-submit"
          onClick={handleSubmit}
          disabled={!hasInput || submitting}
        >
          {submitting ? "Sending…" : "Refine"}
        </Button>
      </div>
    </div>
  );
}

function RefineField({
  label,
  tooltip,
  value,
  onChange,
  testId,
}: {
  label: string;
  tooltip: string;
  value: string;
  onChange: (v: string) => void;
  testId: string;
}) {
  return (
    <div className="space-y-1">
      <Label className="flex items-center gap-1" title={tooltip}>
        {label}
      </Label>
      <Textarea
        data-testid={testId}
        value={value}
        onChange={(e) => onChange(e.target.value.slice(0, MAX_FIELD))}
        rows={2}
        placeholder={tooltip}
      />
      <p className="text-right text-xs text-muted-foreground">
        {value.length}/{MAX_FIELD}
      </p>
    </div>
  );
}
