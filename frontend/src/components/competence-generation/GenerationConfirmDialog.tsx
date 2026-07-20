"use client";

import { useEffect, useState } from "react";
import { Sparkles, Zap } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { UsedDataTooltip } from "./UsedDataTooltip";
import { WholeBaseContextPicker } from "./WholeBaseContextPicker";
import { useCostConfirmation } from "@/hooks/use-cost-confirmation";
import type { SessionScope } from "@/lib/api/competence-generation";

const ACTION_KEY_BY_SCOPE: Record<SessionScope, string> = {
  whole_base: "ai.generate_competences",
  group: "ai.generate_competences",
  competence_indicators: "ai.generate_indicators",
  // specialization_matrix has its own dialog (`SpecializationAIGeneratePage`)
  // and never reaches this confirm dialog; keep an entry to satisfy the type.
  specialization_matrix: "ai_specialization_matrix.start",
};

export interface GenerationConfirmSubmit {
  with_indicators: boolean;
  refinement_prompt?: string;
  context_excludes?: string[];
}

export interface GenerationConfirmDialogProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  scope: SessionScope;
  /** Human-readable name of the target (group/competence) for the title. */
  targetTitle?: string | null;
  /** HRP-114: target group / competence id, required by the per-item
   * picker so it can fetch the right scope-specific lists. */
  targetId?: string | null;
  /** HRP-124: legacy hint that the library is non-empty. The HRP-143
   * picker fetches the tree directly and renders its own controls, so
   * this prop is no longer read inside the dialog. Kept on the type so
   * existing callers compile. */
  hasExistingLibrary?: boolean;
  onSubmit: (params: GenerationConfirmSubmit) => Promise<void> | void;
}

export function GenerationConfirmDialog({
  open,
  onOpenChange,
  scope,
  targetTitle,
  targetId,
  onSubmit,
}: GenerationConfirmDialogProps) {
  const [withIndicators, setWithIndicators] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  // HRP-123: only surfaced for whole_base preflight; other scopes stay simple.
  const [contextExcludes, setContextExcludes] = useState<Set<string>>(
    () => new Set(),
  );
  // HRP-155: explicit "augment existing items" toggle for the group scope.
  // Default unchecked — fresh generation under the target group. When the
  // operator opts in, the existing subtree (source_tree + descendants)
  // travels with the prompt and the worker tags existing nodes so the
  // tree renders them as locked.
  const [augmentExisting, setAugmentExisting] = useState(false);
  const [refinement, setRefinement] = useState("");
  const cost = useCostConfirmation(ACTION_KEY_BY_SCOPE[scope]);

  // For competence_indicators scope the indicators flag is always true.
  const indicatorsFlagApplies = scope !== "competence_indicators";
  // HRP-114: the matrix has its own dedicated dialog
  // (`SpecializationAIGeneratePage`); every other scope flows through here
  // and supports the context-chip + refinement controls.
  const showContextControls = scope !== "specialization_matrix";
  // HRP-155: augment toggle is group-only — whole_base already starts from
  // the existing library by default; competence_indicators is single-
  // competence and has its own existing-indicators chip.
  const showAugmentToggle = scope === "group";

  useEffect(() => {
    if (open) {
      setWithIndicators(true);
      setSubmitting(false);
      setContextExcludes(new Set());
      setAugmentExisting(false);
      setRefinement("");
    }
  }, [open]);

  const title =
    scope === "whole_base"
      ? "AI generation: competence library"
      : scope === "group"
        ? `AI generation: group${targetTitle ? ` "${targetTitle}"` : ""}`
        : `AI generation: indicators${targetTitle ? ` for "${targetTitle}"` : ""}`;

  const helpText =
    scope === "whole_base"
      ? "Builds a full competence tree (groups → competences → optional indicators) tailored to your specializations and divisions. You can review and edit every node before publishing."
      : scope === "group"
        ? "Adds new competences to this group based on the existing structure of your library. Existing competences stay intact — only new branches are proposed."
        : "Generates behavioral indicators for this competence at every skill level. Existing indicators stay locked — only new ones are proposed.";

  async function handleSubmit() {
    setSubmitting(true);
    try {
      const payload: GenerationConfirmSubmit = {
        with_indicators: withIndicators,
      };
      if (showContextControls) {
        const excludes = new Set(contextExcludes);
        // HRP-155: when augment is off for the group scope, the worker
        // must skip the existing subtree entirely — drop both the source
        // tree and its descendants regardless of what the chip picker
        // shows. When augment is on, both stay in so the prompt can ask
        // the LLM to extend existing items and the post-LLM annotation
        // step can attach snapshot_id to matched nodes.
        if (showAugmentToggle && !augmentExisting) {
          excludes.add("source_tree");
          excludes.add("descendants");
        }
        if (excludes.size > 0) {
          payload.context_excludes = Array.from(excludes);
        }
        const trimmedRefinement = refinement.trim();
        if (trimmedRefinement) payload.refinement_prompt = trimmedRefinement;
      }
      await onSubmit(payload);
      onOpenChange(false);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="compgen-confirm-dialog"
        className="flex max-h-[90vh] flex-col sm:max-w-lg"
      >
        <DialogHeader className="shrink-0">
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            {title}
          </DialogTitle>
        </DialogHeader>
        <div
          data-testid="ai-generation-dialog-body"
          className="-mx-4 min-h-0 flex-1 space-y-4 overflow-y-auto px-4"
        >
          <p className="text-sm text-muted-foreground" data-testid="compgen-confirm-help">
            {helpText}
          </p>
          {indicatorsFlagApplies && (
            <label className="flex items-start gap-2">
              <Checkbox
                data-testid="compgen-confirm-checkbox-indicators"
                checked={withIndicators}
                onCheckedChange={(v) => setWithIndicators(Boolean(v))}
                className="mt-0.5"
              />
              <span className="text-sm">
                <Label className="font-medium">
                  Also generate indicators
                </Label>
                <span className="block text-xs text-muted-foreground">
                  Uncheck to get only the competence list without
                  indicators.
                </span>
              </span>
            </label>
          )}
          {showAugmentToggle && (
            <label className="flex items-start gap-2">
              <Checkbox
                data-testid="compgen-confirm-checkbox-augment"
                checked={augmentExisting}
                onCheckedChange={(v) => setAugmentExisting(Boolean(v))}
                className="mt-0.5"
              />
              <span className="text-sm">
                <Label className="font-medium">
                  Augment existing items in the group
                </Label>
                <span className="block text-xs text-muted-foreground">
                  Add new competences to existing subgroups and new
                  indicators to existing competences. Off by default —
                  the model would otherwise only invent fresh branches.
                </span>
              </span>
            </label>
          )}
          {showContextControls ? (
            // HRP-143 / HRP-114: granular per-item picker for every
            // non-matrix scope. Renders sections appropriate to the scope
            // (specializations / related specs / divisions / company /
            // source tree / ancestors / descendants / siblings / existing
            // indicators).
            <WholeBaseContextPicker
              scope={scope}
              targetId={targetId}
              excludes={contextExcludes}
              onChange={setContextExcludes}
              hideExistingSubtree={showAugmentToggle && !augmentExisting}
            />
          ) : null}
          {showContextControls && (
            <div className="space-y-1.5">
              <Label
                htmlFor="compgen-confirm-refinement"
                className="text-xs font-medium uppercase tracking-wide text-muted-foreground"
              >
                Refinement notes (optional)
              </Label>
              <Textarea
                id="compgen-confirm-refinement"
                data-testid="compgen-confirm-refinement"
                placeholder="Tell the model what to emphasise, exclude, or how to phrase the output."
                value={refinement}
                onChange={(e) => setRefinement(e.target.value)}
                rows={3}
                maxLength={4000}
                className="text-sm"
              />
              <p className="text-xs text-muted-foreground">
                Same field as the in-session refinement panel — set it now if
                you already know what to nudge.
              </p>
            </div>
          )}
          {!showContextControls && <UsedDataTooltip />}
          {cost.cost !== null && cost.cost > 0 && (
            <div
              data-testid="compgen-confirm-cost"
              className={`flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${
                cost.requiresConfirmation
                  ? "border-amber-500/40 bg-amber-500/5"
                  : "bg-muted/40"
              }`}
            >
              <Zap className="mt-0.5 h-4 w-4 text-primary" />
              <div className="space-y-0.5">
                <p>
                  <span className="font-mono font-semibold">
                    {cost.cost} {cost.cost === 1 ? "credit" : "credits"}
                  </span>{" "}
                  will be charged when generation starts.
                </p>
                {cost.requiresConfirmation && (
                  <p className="text-xs text-muted-foreground">
                    Above your {cost.threshold}-credit warning threshold.
                    Adjust it in Settings → Billing → Settings.
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
        <DialogFooter className="shrink-0">
          <Button
            data-testid="compgen-confirm-btn-cancel"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button
            data-testid="compgen-confirm-btn-start"
            onClick={handleSubmit}
            disabled={submitting}
          >
            {submitting
              ? "Starting…"
              : cost.requiresConfirmation
                ? `Confirm & start (${cost.cost} credits)`
                : "Start"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
