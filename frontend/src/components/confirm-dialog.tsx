"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  onConfirm: () => void | Promise<void>;
  loading?: boolean;
  // HRP-171: caller can override the destructive "Delete" copy for
  // non-destructive confirms (e.g. "Continue" on a "Required
  // competencies will be recomputed" warning). Defaults preserve the
  // original delete-confirmation behaviour for every existing caller.
  confirmLabel?: string;
  loadingLabel?: string;
  confirmVariant?: "destructive" | "default";
  // HRP-103 redo: callers like the specialization-delete confirm need
  // to enumerate live references (positions, grade chains) right under
  // the description. Optional so existing call sites stay unchanged.
  children?: ReactNode;
  // HRP-103 redo: separately disable the confirm button even when the
  // dialog itself stays interactive (e.g. references still present).
  confirmDisabled?: boolean;
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  onConfirm,
  loading,
  confirmLabel,
  loadingLabel,
  confirmVariant = "destructive",
  children,
  confirmDisabled,
}: ConfirmDialogProps) {
  const t = useTranslations("common");
  const resolvedConfirmLabel = confirmLabel ?? t("delete");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" data-testid="confirm-dialog">
        <DialogHeader>
          <DialogTitle data-testid="confirm-dialog-title">{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {children}
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={loading}
            data-testid="confirm-dialog-btn-cancel"
          >
            {t("cancel")}
          </Button>
          <Button
            variant={confirmVariant}
            onClick={onConfirm}
            disabled={loading || confirmDisabled}
            data-testid="confirm-dialog-btn-confirm"
          >
            {loading
              ? (loadingLabel ?? `${resolvedConfirmLabel}...`)
              : resolvedConfirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
