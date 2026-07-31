"use client";

import { Zap } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface CostConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  actionLabel: string;
  cost: number | null;
  threshold: number;
  onConfirm: () => void;
  onCancel: () => void;
  testId?: string;
}

export function CostConfirmDialog({
  open,
  onOpenChange,
  actionLabel,
  cost,
  threshold,
  onConfirm,
  onCancel,
  testId,
}: CostConfirmDialogProps) {
  const t = useTranslations("settings");
  const tc = useTranslations("common");
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
        onOpenChange(next);
      }}
    >
      <DialogContent data-testid={testId ?? "cost-confirm-dialog"}>
        <DialogHeader>
          <DialogTitle>{t("billingCostConfirmTitle")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <p>
            {t.rich("billingCostConfirmBody", {
              b: (chunks) => <span className="font-medium">{chunks}</span>,
              action: actionLabel,
            })}
          </p>
          {cost !== null && (
            <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2">
              <Zap className="h-4 w-4 text-primary" />
              <span className="font-mono text-base font-semibold">
                {tc("credits", { count: cost })}
              </span>
              <span className="text-xs text-muted-foreground">
                {t("billingCostConfirmThreshold", { threshold })}
              </span>
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            {t("billingCostConfirmHint")}
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            {tc("cancel")}
          </Button>
          <Button
            onClick={onConfirm}
            data-testid={
              testId ? `${testId}-confirm` : "cost-confirm-dialog-confirm"
            }
          >
            {t("billingRunAnyway")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
