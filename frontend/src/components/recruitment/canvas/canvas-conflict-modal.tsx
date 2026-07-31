"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { AssessmentConflictState } from "@/lib/types";

interface CanvasConflictModalProps {
  conflicts: Map<string, AssessmentConflictState>;
  onResolve: (cellKey: string, choice: "mine" | "theirs") => Promise<void>;
}

/**
 * HRP-266: shown whenever the Canvas autosave hits HTTP 412 — the
 * backend detected a parallel editor and refused to overwrite their
 * change. The user picks one of Yours / Theirs / Cancel per conflicted
 * cell; choosing Cancel keeps the cell in the conflict state so they
 * can reopen the dialog later via the toast or the Versions sheet.
 */
export function CanvasConflictModal({
  conflicts,
  onResolve,
}: CanvasConflictModalProps) {
  const t = useTranslations("recruitment");
  const entries = useMemo(
    () => Array.from(conflicts.values()),
    [conflicts],
  );
  const [busyKey, setBusyKey] = useState<string | null>(null);
  // Local dismiss flag — clearing all conflicts via onResolve unmounts
  // the dialog naturally; this lets the user defer the resolution
  // without losing the conflict state.
  const [dismissed, setDismissed] = useState(false);
  const conflictCount = entries.length;

  // Reset the dismiss flag whenever a fresh conflict lands so the next
  // 412 surface the dialog instead of staying silently hidden.
  useEffect(() => {
    if (conflictCount === 0 && dismissed) {
      setDismissed(false);
    }
  }, [conflictCount, dismissed]);

  const open = conflictCount > 0 && !dismissed;
  if (!open) return null;

  async function handlePick(
    entry: AssessmentConflictState,
    choice: "mine" | "theirs",
  ) {
    setBusyKey(entry.cellKey);
    try {
      await onResolve(entry.cellKey, choice);
    } finally {
      // Drop the busy marker before the parent's setState propagates so
      // a setBusyKey on an unmounted component cannot fire — onResolve
      // may have emptied ``conflicts`` and hidden this dialog.
      setBusyKey(null);
    }
  }

  return (
    <Dialog open onOpenChange={(next) => !next && setDismissed(true)}>
      <DialogContent
        data-testid="canvas-conflict-modal"
        className="max-w-lg"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="size-4 text-amber-600" />
            {t("canvasConflictTitle")}
          </DialogTitle>
          <DialogDescription>
            {t("canvasConflictDescription", { count: entries.length })}
          </DialogDescription>
        </DialogHeader>

        <ul className="space-y-3 text-xs" data-testid="canvas-conflict-list">
          {entries.map((entry) => (
            <li
              key={entry.cellKey}
              data-testid={`canvas-conflict-row-${entry.cellKey}`}
              className="rounded-md border p-3"
            >
              <div className="mb-2 text-[10px] text-muted-foreground">
                {t("canvasConflictCellLine", {
                  candidate: entry.candidateVacancyId.slice(0, 8),
                  competence: entry.competenceId.slice(0, 8),
                })}
              </div>
              <div className="mb-2">{entry.serverMessage}</div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-muted-foreground">
                  {t("canvasConflictYours")}
                </span>
                <span className="font-mono">
                  {entry.mine === null ? "—" : entry.mine.toFixed(1)}
                </span>
                <Button
                  size="sm"
                  variant="default"
                  disabled={busyKey === entry.cellKey}
                  onClick={() => void handlePick(entry, "mine")}
                  data-testid={`canvas-conflict-keep-mine-${entry.cellKey}`}
                >
                  {t("canvasConflictKeepMine")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busyKey === entry.cellKey}
                  onClick={() => void handlePick(entry, "theirs")}
                  data-testid={`canvas-conflict-keep-theirs-${entry.cellKey}`}
                >
                  {t("canvasConflictKeepTheirs")}
                </Button>
              </div>
            </li>
          ))}
        </ul>

        <DialogFooter className="flex items-center justify-between gap-3">
          <span className="text-[11px] text-muted-foreground">
            {t("canvasConflictFooter")}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setDismissed(true)}
            data-testid="canvas-conflict-defer-btn"
          >
            {t("canvasConflictResolveLater")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
