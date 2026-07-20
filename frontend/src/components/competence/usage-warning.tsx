"use client";

import { AlertTriangle } from "lucide-react";

import type { CompetenceUsage } from "@/lib/types";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

const AREA_LABELS: Array<{ key: keyof CompetenceUsage; label: string }> = [
  { key: "matrix", label: "Specialization matrices" },
  { key: "employee_card", label: "Employee cards" },
  { key: "assessment", label: "Assessments" },
  { key: "idp", label: "Development plans" },
  { key: "talent_market", label: "Talent market" },
];

export function listUsageAreas(usage: CompetenceUsage | null): string[] {
  if (!usage || !usage.is_used) return [];
  return AREA_LABELS.filter((a) => usage[a.key]).map((a) => a.label);
}

export function CompetenceUsageBanner({
  usage,
  testIdPrefix = "competence-usage",
}: {
  usage: CompetenceUsage;
  testIdPrefix?: string;
}) {
  const areas = listUsageAreas(usage);
  if (areas.length === 0) return null;
  return (
    <div
      data-testid={`${testIdPrefix}-banner`}
      className="flex gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-700 dark:bg-amber-950/30"
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
      <div className="space-y-1">
        <p className="font-medium text-amber-900 dark:text-amber-200">
          This competence is in active use
        </p>
        <p className="text-amber-800 dark:text-amber-300">
          Changes to its indicators will propagate everywhere it is used:
        </p>
        <ul
          data-testid={`${testIdPrefix}-areas`}
          className="ml-4 list-disc text-amber-800 dark:text-amber-300"
        >
          {areas.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export interface CompetenceUsageWarningDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  usage: CompetenceUsage | null;
  title?: string;
  body?: string;
  confirmLabel?: string;
  onConfirm: () => void | Promise<void>;
  loading?: boolean;
  testIdPrefix?: string;
}

export function CompetenceUsageWarningDialog({
  open,
  onOpenChange,
  usage,
  title = "Save anyway?",
  body = "Saving will update every place that references this competence.",
  confirmLabel = "Save anyway",
  onConfirm,
  loading,
  testIdPrefix = "competence-usage-warning",
}: CompetenceUsageWarningDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid={`${testIdPrefix}-dialog`}
        className="sm:max-w-md"
      >
        <DialogHeader>
          <DialogTitle data-testid={`${testIdPrefix}-title`}>{title}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">{body}</p>
        {usage && <CompetenceUsageBanner usage={usage} testIdPrefix={testIdPrefix} />}
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={loading}
            data-testid={`${testIdPrefix}-btn-cancel`}
          >
            Cancel
          </Button>
          <Button
            onClick={onConfirm}
            disabled={loading}
            data-testid={`${testIdPrefix}-btn-confirm`}
          >
            {loading ? "Saving…" : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
