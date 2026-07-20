"use client";

import { Zap } from "lucide-react";

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
          <DialogTitle>Confirm AI action</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <p>
            <span className="font-medium">{actionLabel}</span> will charge your
            workspace balance.
          </p>
          {cost !== null && (
            <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2">
              <Zap className="h-4 w-4 text-primary" />
              <span className="font-mono text-base font-semibold">
                {cost} {cost === 1 ? "credit" : "credits"}
              </span>
              <span className="text-xs text-muted-foreground">
                (above the {threshold}-credit warning threshold)
              </span>
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            You can adjust the threshold in Settings → Billing → Settings.
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            onClick={onConfirm}
            data-testid={
              testId ? `${testId}-confirm` : "cost-confirm-dialog-confirm"
            }
          >
            Run anyway
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
