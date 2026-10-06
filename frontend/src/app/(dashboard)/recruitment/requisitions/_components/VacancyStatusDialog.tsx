"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { RadioGroup, RadioItem } from "@/components/ui/radio";
import { api } from "@/lib/api";
import type { Vacancy, VacancyAnalytics } from "@/lib/types";
import {
  VACANCY_COMMAND_TARGET,
  type VacancyCloseResolution,
  type VacancyStatusCommand,
} from "@/lib/vacancy-status";
import { toast } from "sonner";

type Props = {
  vacancy: Vacancy;
  /** The command being confirmed; `null` keeps the dialog closed. */
  command: VacancyStatusCommand | null;
  onOpenChange: (open: boolean) => void;
  onChanged?: () => void;
};

// HRP-427 / HRP-836: every lifecycle command goes through a confirmation.
const COPY: Record<
  VacancyStatusCommand,
  { title: string; description: string; confirm: string; done: string }
> = {
  publish: {
    title: "vacancyPublishTitle",
    description: "vacancyPublishDescription",
    confirm: "actionPublish",
    done: "vacancyToastPublished",
  },
  pause: {
    title: "vacancyPauseTitle",
    description: "vacancyPauseDescription",
    confirm: "actionPause",
    done: "vacancyToastPaused",
  },
  reopen: {
    title: "vacancyReopenTitle",
    description: "vacancyReopenDescription",
    confirm: "actionReopen",
    done: "vacancyToastReopened",
  },
  close: {
    title: "vacancyCloseTitle",
    description: "vacancyCloseDescription",
    confirm: "vacancyCloseConfirm",
    done: "vacancyToastClosed",
  },
  cancel: {
    title: "vacancyCancelTitle",
    description: "vacancyCancelDescription",
    confirm: "vacancyCancelConfirm",
    done: "vacancyToastCancelled",
  },
};

const RESOLUTIONS: readonly {
  value: VacancyCloseResolution;
  labelKey: string;
}[] = [
  { value: "hired", labelKey: "vacancyResolutionHired" },
  { value: "closed_no_hire", labelKey: "vacancyResolutionNoHire" },
];

export function VacancyStatusDialog({
  vacancy,
  command,
  onOpenChange,
  onChanged,
}: Props) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [saving, setSaving] = useState(false);
  const [resolution, setResolution] = useState<VacancyCloseResolution | "">(
    "",
  );
  // Close: the resolution has to match the funnel — "with hiring" needs a
  // candidate on a terminal-positive stage, "without hiring" must not have
  // one. The backend checks the same; this says so before the click.
  const [hiredCount, setHiredCount] = useState<number | null>(null);

  useEffect(() => {
    if (command !== "close") return;
    setResolution("");
    setHiredCount(null);
    let cancelled = false;
    api
      .get<VacancyAnalytics>(`/recruitment/vacancies/${vacancy.id}/analytics`)
      .then((a) => {
        if (!cancelled) setHiredCount(a.win_loss.hired);
      })
      .catch(() => {
        // Unknown: the backend's own check still answers.
      });
    return () => {
      cancelled = true;
    };
  }, [command, vacancy.id]);

  const resolutionError =
    command !== "close" || hiredCount === null || !resolution
      ? null
      : resolution === "hired" && hiredCount === 0
        ? t("vacancyCloseNeedsHire")
        : resolution === "closed_no_hire" && hiredCount > 0
          ? t("vacancyCloseHasHire")
          : null;

  async function handleConfirm() {
    if (!command) return;
    setSaving(true);
    try {
      if (command === "close") {
        await api.post(`/recruitment/vacancies/${vacancy.id}/close`, {
          resolution,
        });
      } else {
        await api.post(`/recruitment/vacancies/${vacancy.id}/status`, {
          status: VACANCY_COMMAND_TARGET[command],
        });
      }
      toast.success(t(COPY[command].done));
      onOpenChange(false);
      onChanged?.();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("vacancyStatusChangeFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  const copy = command ? COPY[command] : null;
  const destructive = command === "cancel" || command === "close";

  return (
    <Dialog open={command !== null} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="vacancy-status-modal"
        onClick={(e) => e.stopPropagation()}
      >
        {copy && (
          <>
            <DialogHeader>
              <DialogTitle>{t(copy.title)}</DialogTitle>
              <DialogDescription>
                {t(copy.description, { title: vacancy.title })}
              </DialogDescription>
            </DialogHeader>
            {command === "close" && (
              <div className="space-y-2">
                <p className="text-sm font-medium">
                  {t("vacancyCloseResolutionLabel")}
                </p>
                <RadioGroup
                  value={resolution}
                  onValueChange={(v) =>
                    setResolution(v as VacancyCloseResolution)
                  }
                >
                  {RESOLUTIONS.map((r) => (
                    <label
                      key={r.value}
                      className="flex cursor-pointer items-center gap-2 text-sm"
                    >
                      <RadioItem
                        value={r.value}
                        data-testid={`vacancy-close-resolution-${r.value}`}
                      />
                      {t(r.labelKey)}
                    </label>
                  ))}
                </RadioGroup>
                {resolutionError && (
                  <p
                    className="text-sm text-destructive"
                    data-testid="vacancy-status-modal-error"
                  >
                    {resolutionError}
                  </p>
                )}
              </div>
            )}
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={saving}
                data-testid="vacancy-status-modal-cancel"
              >
                {tc("cancel")}
              </Button>
              <Button
                variant={destructive ? "destructive" : "default"}
                onClick={handleConfirm}
                disabled={
                  saving ||
                  (command === "close" && (!resolution || !!resolutionError))
                }
                data-testid="vacancy-status-modal-confirm"
              >
                {t(copy.confirm)}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
