"use client";

import { useState } from "react";
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
import { api } from "@/lib/api";
import type { Vacancy } from "@/lib/types";
import { toast } from "sonner";

type Props = {
  vacancy: Vacancy;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onArchived?: () => void;
};

export function VacancyArchiveDialog({
  vacancy,
  open,
  onOpenChange,
  onArchived,
}: Props) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [saving, setSaving] = useState(false);

  async function handleArchive() {
    setSaving(true);
    try {
      await api.post(`/recruitment/vacancies/${vacancy.id}/archive`);
      toast.success(t("vacancyToastArchived"));
      onOpenChange(false);
      onArchived?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("vacancyArchiveFailed"));
    } finally {
      setSaving(false);
    }
  }

  const invites = vacancy.active_invites_count ?? 0;
  const candidates = vacancy.candidates_count ?? 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="vacancy-archive-modal">
        <DialogHeader>
          <DialogTitle>{t("vacancyArchiveTitle")}</DialogTitle>
          <DialogDescription>
            {t("vacancyArchiveDescription", { title: vacancy.title })}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2 text-sm">
          {invites > 0 && (
            <p className="text-yellow-700">
              {t("vacancyArchiveInvitesWarning", { count: invites })}
            </p>
          )}
          {candidates > 0 && (
            <p className="text-muted-foreground">
              {t("vacancyArchiveCandidatesNote", { count: candidates })}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
            data-testid="vacancy-archive-modal-cancel"
          >
            {tc("cancel")}
          </Button>
          <Button
            variant="destructive"
            onClick={handleArchive}
            disabled={saving}
            data-testid="vacancy-archive-modal-confirm"
          >
            {saving ? t("vacancyArchiving") : t("actionArchive")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
