"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
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
  const router = useRouter();
  const [saving, setSaving] = useState(false);

  async function handleDelete() {
    setSaving(true);
    try {
      await api.delete(`/recruitment/vacancies/${vacancy.id}`);
      toast.success("Vacancy deleted");
      onOpenChange(false);
      if (onDeleted) {
        onDeleted();
      } else {
        router.push("/recruitment/requisitions");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="vacancy-delete-modal">
        <DialogHeader>
          <DialogTitle>Delete vacancy permanently?</DialogTitle>
          <DialogDescription>
            This action cannot be undone. The vacancy &ldquo;{vacancy.title}
            &rdquo; and its draft profile will be permanently removed.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
            data-testid="vacancy-delete-modal-cancel"
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={saving}
            onClick={handleDelete}
            data-testid="vacancy-delete-modal-confirm"
          >
            {saving ? "Deleting..." : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
