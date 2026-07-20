"use client";

import { useState } from "react";
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
  const [saving, setSaving] = useState(false);

  async function handleArchive() {
    setSaving(true);
    try {
      await api.post(`/recruitment/vacancies/${vacancy.id}/archive`);
      toast.success("Vacancy archived");
      onOpenChange(false);
      onArchived?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to archive");
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
          <DialogTitle>Archive vacancy?</DialogTitle>
          <DialogDescription>
            &ldquo;{vacancy.title}&rdquo; will be hidden from the active list.
            You can restore it from the Archived filter within 90 days.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2 text-sm">
          {invites > 0 && (
            <p className="text-yellow-700">
              ⚠️ {invites} active reviewer invitation{invites === 1 ? "" : "s"}{" "}
              will be deactivated.
            </p>
          )}
          {candidates > 0 && (
            <p className="text-muted-foreground">
              ℹ️ {candidates} candidate{candidates === 1 ? "" : "s"} will remain
              accessible from the archived vacancy view.
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
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleArchive}
            disabled={saving}
            data-testid="vacancy-archive-modal-confirm"
          >
            {saving ? "Archiving..." : "Archive"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
