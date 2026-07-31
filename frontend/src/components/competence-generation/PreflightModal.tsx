"use client";

import { useEffect, useState } from "react";
import { Users } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  OtherActiveSession,
  competenceGenerationApi,
} from "@/lib/api/competence-generation";

export interface PreflightModalProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  hasOwnSession: boolean;
  onGoToOwn?: () => void;
  /** Pre-fetched list; if absent the modal fetches on open. */
  others?: OtherActiveSession[];
}

export function PreflightModal({
  open,
  onOpenChange,
  hasOwnSession,
  onGoToOwn,
  others: providedOthers,
}: PreflightModalProps) {
  const t = useTranslations("competences");
  const [fetched, setFetched] = useState<OtherActiveSession[]>([]);
  const others = providedOthers ?? fetched;

  useEffect(() => {
    if (!open || providedOthers !== undefined) return;
    competenceGenerationApi
      .getActiveOthers()
      .then(setFetched)
      .catch(() => setFetched([]));
  }, [open, providedOthers]);

  const names = others.map((o) => o.user_full_name).filter(Boolean).join(", ");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="compgen-preflight-modal"
        className="sm:max-w-md"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Users className="h-4 w-4 text-primary" />
            {t("preflightTitle")}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <p>
            {t.rich("preflightBody", {
              names: names || "—",
              strong: (chunks) => (
                <span className="font-medium text-foreground">{chunks}</span>
              ),
            })}
          </p>
          <p className="text-muted-foreground">{t("preflightHint")}</p>
        </div>
        <DialogFooter>
          {hasOwnSession && onGoToOwn && (
            <Button
              data-testid="compgen-preflight-btn-goto-own"
              variant="outline"
              onClick={() => {
                onOpenChange(false);
                onGoToOwn();
              }}
            >
              {t("preflightOpenOwn")}
            </Button>
          )}
          <Button
            data-testid="compgen-preflight-btn-ok"
            onClick={() => onOpenChange(false)}
          >
            {t("preflightGotIt")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
