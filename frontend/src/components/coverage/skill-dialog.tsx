"use client";

// HRP-760: a step's SKILL.md - generate it, read it, download it. Since W6
// (§5.12) the generation runs in a Celery task, so the dialog follows the
// row by polling and shows the shared progress strip meanwhile.
//
// Used from the Coverage tab and from the To do tab's second section, so
// it takes the smallest shape both rows have rather than a whole row.

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Download, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { GenerationProgress } from "@/components/coverage/generation-progress";
import { EECreditCostBadge } from "@/lib/ee-hooks";
import { SKILL_ACTION, type SkillStatus, type StepSkill, workApi } from "@/lib/api/work";

// The limit sits past the three-minute staleness timeout, after which the
// row reads as failed anyway.
const POLL_MS = 3_000;
const POLL_LIMIT = 80;

export interface SkillTarget {
  step_id: string;
  title: string;
  skill_status: SkillStatus;
}

export function SkillDialog({
  step,
  canEdit,
  onClose,
  onChanged,
}: {
  step: SkillTarget;
  canEdit: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const t = useTranslations("coverage");
  const [skill, setSkill] = useState<StepSkill | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<string | null>(null);
  // One generation per opened dialog: Strict Mode replays the effect, and a
  // second POST would race the first on the step's unique skill row.
  const started = useRef(false);

  const generate = useCallback(async () => {
    setError(null);
    try {
      // Queued: the row comes back generating and the poll below follows
      // it to ready or failed.
      setSkill(await workApi.generateSkill(step.step_id));
      setStartedAt(new Date().toISOString());
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("skillFailed"));
      onChanged();
    }
  }, [step.step_id, t, onChanged]);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    (async () => {
      if (step.skill_status !== "none") {
        try {
          const existing = await workApi.getSkill(step.step_id);
          setSkill(existing);
          if (existing.status === "generating") {
            // Started elsewhere (another tab, a bulk run): follow it.
            setStartedAt(new Date().toISOString());
            return;
          }
          if (existing.status === "failed" && existing.error_message) {
            setError(existing.error_message);
          }
          if (existing.content) return;
          // Ready but with nothing to show: a silent regeneration here is a
          // charge nobody asked for. Say so and leave it to Regenerate.
          if (existing.status === "ready") {
            setError(t("skillEmpty"));
            return;
          }
        } catch {
          // fall through to a fresh generation
        }
      }
      if (canEdit) void generate();
    })();
    // Runs once per opened step: the dialog is remounted per step.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step.step_id]);

  const generating = skill?.status === "generating";
  useEffect(() => {
    if (!generating) return;
    let polls = 0;
    const timer = window.setInterval(async () => {
      polls += 1;
      if (polls > POLL_LIMIT) {
        window.clearInterval(timer);
        setError(t("skillFailed"));
        // Leaving the row "generating" keeps the progress strip animating
        // next to the error and disables Regenerate for good.
        setSkill((prev) => (prev ? { ...prev, status: "failed" } : prev));
        // The row behind the dialog is still "generating" too: refresh it,
        // or "Get skill" stays disabled until the page is reloaded.
        onChanged();
        return;
      }
      try {
        const fresh = await workApi.getSkill(step.step_id);
        if (fresh.status === "generating") return;
        setSkill(fresh);
        setError(
          fresh.status === "failed" ? (fresh.error_message ?? t("skillFailed")) : null,
        );
        onChanged();
      } catch {
        // keep the last snapshot; the next tick retries
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [generating, step.step_id, t, onChanged]);

  async function download() {
    try {
      const blob = await workApi.downloadSkill(step.step_id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "SKILL.md";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-3xl" data-testid="coverage-modal-skill">
        <DialogHeader>
          <DialogTitle>{t("skillTitle", { title: step.title })}</DialogTitle>
          <DialogDescription>{t("skillText")}</DialogDescription>
        </DialogHeader>
        {/* The file is written in English on purpose - agents read it, not
            the company. Without a word here that reads as a bug. */}
        <p className="text-xs text-muted-foreground">{t("skillEnglishHint")}</p>
        {generating && (
          <GenerationProgress
            phase={1}
            phases={1}
            startedAt={startedAt}
            caption={t("generatingSkill")}
            testId="coverage-skill-progress"
          />
        )}
        {error && (
          <p className="text-sm text-destructive" data-testid="coverage-skill-error">
            {error}
          </p>
        )}
        {skill?.content && (
          <pre
            className="max-h-[60vh] overflow-auto rounded-md border bg-muted/40 p-3 text-xs whitespace-pre-wrap"
            data-testid="coverage-skill-preview"
          >
            {skill.content}
          </pre>
        )}
        <DialogFooter>
          {canEdit && (
            <Button
              variant="outline"
              disabled={generating}
              onClick={generate}
              data-testid="coverage-btn-skill-regenerate"
            >
              <RefreshCw className="size-4" />
              {t("regenerateSkill")}
              <EECreditCostBadge action={SKILL_ACTION} />
            </Button>
          )}
          <Button
            disabled={!skill?.content}
            onClick={download}
            data-testid="coverage-btn-skill-download"
          >
            <Download className="size-4" />
            {t("downloadSkill")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
