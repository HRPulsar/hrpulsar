"use client";

// HRP-760: a step's SKILL.md - generate it, read it, download it. Since W6
// (§5.12) the generation runs in a Celery task. HRP-1202: the dialog does
// not hold the reader while it runs - starting one closes it, and the
// process page follows the step (use-skill-watch) until the file is ready.
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
import { generationErrorText } from "@/components/coverage/generation-errors";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { useAuth } from "@/context/auth-context";
import { useCostConfirmation } from "@/hooks/use-cost-confirmation";
import { EECreditCostBadge } from "@/lib/ee-hooks";
import { SKILL_ACTION, type SkillStatus, type StepSkill, workApi } from "@/lib/api/work";

export interface SkillTarget {
  step_id: string;
  position: number;
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
  const tc = useTranslations("common");
  // HRP-1201: a demo visitor has no agent runner of their own: one line
  // says where the file goes instead of a skills folder they do not have.
  const isDemo = !!useAuth().user?.tenant_is_demo;
  const [skill, setSkill] = useState<StepSkill | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  // One generation per opened dialog: Strict Mode replays the effect, and a
  // second POST would race the first on the step's unique skill row.
  const started = useRef(false);
  // HRP-960: opening a step with no skill (or a failed one) used to start
  // the generation - a charge - at once. It waits for a confirmation now;
  // a ready or running skill opens straight away, reading it costs nothing.
  const wouldGenerate =
    canEdit && step.skill_status !== "ready" && step.skill_status !== "generating";
  const [confirmed, setConfirmed] = useState(!wouldGenerate);
  // A failed regeneration keeps the skill it had: such a step opens on that
  // content, free, instead of a confirmation promising a charged generation
  // that would never run. Read first; ask only when there is nothing.
  const [probing, setProbing] = useState(
    wouldGenerate && step.skill_status === "failed",
  );
  useEffect(() => {
    if (!probing) return;
    let cancelled = false;
    workApi
      .getSkill(step.step_id)
      .then((existing) => {
        if (cancelled || !existing.content) return;
        started.current = true;
        setSkill(existing);
        if (existing.error_code || existing.error_message) {
          setError(
            generationErrorText(t, existing.error_code, existing.error_message, "skillFailed"),
          );
        }
        setConfirmed(true);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setProbing(false);
      });
    return () => {
      cancelled = true;
    };
  }, [probing, step.step_id, t]);
  // The same price the bulk confirmation on the To do tab names.
  const { cost } = useCostConfirmation(SKILL_ACTION);

  // Queued, not awaited: the page follows the step from here (HRP-1202),
  // so the reader goes back to the process instead of a progress bar.
  const leaveRunning = useCallback(() => {
    toast.success(t("skillQueuedToast", { position: step.position }));
    onChanged();
    onClose();
  }, [step.position, t, onChanged, onClose]);

  const generate = useCallback(async () => {
    setError(null);
    setStarting(true);
    try {
      await workApi.generateSkill(step.step_id);
      leaveRunning();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("skillFailed"));
      onChanged();
    } finally {
      setStarting(false);
    }
  }, [step.step_id, t, onChanged, leaveRunning]);

  useEffect(() => {
    if (!confirmed || started.current) return;
    started.current = true;
    (async () => {
      if (step.skill_status !== "none") {
        try {
          const existing = await workApi.getSkill(step.step_id);
          if (existing.status === "generating") {
            // Started elsewhere (another tab, a bulk run): the page follows it.
            leaveRunning();
            return;
          }
          setSkill(existing);
          if (existing.status === "failed" && (existing.error_code || existing.error_message)) {
            setError(
              generationErrorText(t, existing.error_code, existing.error_message, "skillFailed"),
            );
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
      else setError(tc("loadFailed"));
    })();
    // Runs once per opened step: the dialog is remounted per step.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step.step_id, confirmed]);

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

  // Nothing to show yet: the row is being read, or the generation is
  // being queued and the dialog is about to close.
  if (probing || (confirmed && !skill && !error)) return null;
  if (!confirmed) {
    return (
      <ConfirmDialog
        open
        onOpenChange={(open) => !open && onClose()}
        title={t("skillTitle", { title: step.title })}
        description={cost === null ? t("skillConfirm") : t("skillConfirmCost", { cost })}
        onConfirm={() => setConfirmed(true)}
        confirmLabel={t("getSkill")}
        confirmVariant="default"
        confirmTestId="coverage-skill-confirm-btn-confirm"
        cancelTestId="coverage-skill-confirm-btn-cancel"
      />
    );
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-3xl" data-testid="coverage-modal-skill">
        <DialogHeader>
          <DialogTitle>{t("skillTitle", { title: step.title })}</DialogTitle>
          <DialogDescription data-testid="coverage-skill-text">
            {t(isDemo ? "skillTextDemo" : "skillText")}
          </DialogDescription>
        </DialogHeader>
        {/* HRP-912: the file follows the workspace's AI content language,
            like every other generated text - say where that is set. HRP-1182:
            only under a file - ru says it "was prepared". */}
        {skill?.content && <p className="text-xs text-muted-foreground">{t("skillLanguageHint")}</p>}
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
              disabled={starting}
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
