"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
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
  onDeleted?: () => void;
};

export function VacancyDeleteDialog({
  vacancy,
  open,
  onOpenChange,
  onDeleted,
}: Props) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const router = useRouter();
  const [saving, setSaving] = useState(false);

  async function handleDelete() {
    setSaving(true);
    try {
      await api.delete(`/recruitment/vacancies/${vacancy.id}`);
      toast.success(t("vacancyToastDeleted"));
      onOpenChange(false);
      if (onDeleted) {
        onDeleted();
      } else {
        router.push("/recruitment/requisitions");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("vacancyDeleteFailed"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="vacancy-delete-modal">
        <DialogHeader>
          <DialogTitle>{t("vacancyDeleteTitle")}</DialogTitle>
          <DialogDescription>
            {t("vacancyDeleteDescription", { title: vacancy.title })}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
            data-testid="vacancy-delete-modal-cancel"
          >
            {tc("cancel")}
          </Button>
          <Button
            variant="destructive"
            disabled={saving}
            onClick={handleDelete}
            data-testid="vacancy-delete-modal-confirm"
          >
            {saving ? t("vacancyDeleting") : tc("delete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
