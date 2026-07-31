"use client";

import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";

import type { CompetenceUsage } from "@/lib/types";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

/** HRP-476: usage flag → key in the `competences` i18n namespace. The map
 *  owns the flag → key relation; the wording lives in the catalog. */
const AREA_LABEL_KEYS: Array<{ key: keyof CompetenceUsage; labelKey: string }> =
  [
    { key: "matrix", labelKey: "usageAreaMatrix" },
    { key: "employee_card", labelKey: "usageAreaEmployeeCard" },
    { key: "assessment", labelKey: "usageAreaAssessment" },
    { key: "idp", labelKey: "usageAreaIdp" },
    { key: "talent_market", labelKey: "usageAreaTalentMarket" },
  ];

/** Translated usage areas. `t` is passed in so vitest can pin the key set
 *  without an intl provider. */
export function listUsageAreas(
  t: (key: string) => string,
  usage: CompetenceUsage | null,
): string[] {
  if (!usage || !usage.is_used) return [];
  return AREA_LABEL_KEYS.filter((a) => usage[a.key]).map((a) => t(a.labelKey));
}

export function CompetenceUsageBanner({
  usage,
  testIdPrefix = "competence-usage",
}: {
  usage: CompetenceUsage;
  testIdPrefix?: string;
}) {
  const t = useTranslations("competences");
  const areas = listUsageAreas(t, usage);
  if (areas.length === 0) return null;
  return (
    <div
      data-testid={`${testIdPrefix}-banner`}
      className="flex gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-700 dark:bg-amber-950/30"
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
      <div className="space-y-1">
        <p className="font-medium text-amber-900 dark:text-amber-200">
          {t("usageBannerTitle")}
        </p>
        <p className="text-amber-800 dark:text-amber-300">
          {t("usageBannerBody")}
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
  title,
  body,
  confirmLabel,
  onConfirm,
  loading,
  testIdPrefix = "competence-usage-warning",
}: CompetenceUsageWarningDialogProps) {
  const t = useTranslations("competences");
  const tc = useTranslations("common");
  const resolvedTitle = title ?? t("usageSaveAnywayTitle");
  const resolvedBody = body ?? t("usageSaveAnywayBody");
  const resolvedConfirmLabel = confirmLabel ?? t("usageSaveAnywayConfirm");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid={`${testIdPrefix}-dialog`}
        className="sm:max-w-md"
      >
        <DialogHeader>
          <DialogTitle data-testid={`${testIdPrefix}-title`}>
            {resolvedTitle}
          </DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">{resolvedBody}</p>
        {usage && <CompetenceUsageBanner usage={usage} testIdPrefix={testIdPrefix} />}
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={loading}
            data-testid={`${testIdPrefix}-btn-cancel`}
          >
            {tc("cancel")}
          </Button>
          <Button
            onClick={onConfirm}
            disabled={loading}
            data-testid={`${testIdPrefix}-btn-confirm`}
          >
            {loading ? t("savingEllipsis") : resolvedConfirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
