"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Download, Loader2 } from "lucide-react";
import { toast } from "sonner";

interface QuestionsExportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: string;
  vacancyId: string;
  candidateName?: string;
  vacancyTitle?: string;
}

export function QuestionsExportDialog({
  open,
  onOpenChange,
  candidateId,
  vacancyId,
  candidateName,
  vacancyTitle,
}: QuestionsExportDialogProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [includeGood, setIncludeGood] = useState(true);
  const [includeAcceptable, setIncludeAcceptable] = useState(true);
  const [includePoor, setIncludePoor] = useState(false);
  const [downloading, setDownloading] = useState(false);

  async function handleDownload() {
    setDownloading(true);
    try {
      const blob = await api.postBlob(
        `/recruitment/candidates/${candidateId}/vacancies/${vacancyId}/questions/pdf`,
        {
          include_good: includeGood,
          include_acceptable: includeAcceptable,
          include_poor: includePoor,
        },
      );
      const objectUrl = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      const safeName = (candidateName || candidateId).replace(/[^a-zA-Z0-9_-]+/g, "_");
      link.download = `questions-${safeName}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(objectUrl);
      onOpenChange(false);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : t("questionsExportFailed");
      toast.error(message);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="questions-export-dialog">
        <DialogHeader>
          <DialogTitle>{t("questionsExportTitle")}</DialogTitle>
          <DialogDescription>
            {candidateName && vacancyTitle
              ? t("questionsExportSubtitle", {
                  candidate: candidateName,
                  vacancy: vacancyTitle,
                })
              : t("questionsExportDescription")}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            {t("questionsExportIncludeHeading")}
          </p>
          <label className="flex items-center gap-3 text-sm">
            <Checkbox
              checked={includeGood}
              onCheckedChange={(v) => setIncludeGood(Boolean(v))}
              data-testid="export-good"
            />
            <Label className="cursor-pointer">
              {t("questionsExportGood")}
            </Label>
          </label>
          <label className="flex items-center gap-3 text-sm">
            <Checkbox
              checked={includeAcceptable}
              onCheckedChange={(v) => setIncludeAcceptable(Boolean(v))}
              data-testid="export-acceptable"
            />
            <Label className="cursor-pointer">
              {t("questionsExportAcceptable")}
            </Label>
          </label>
          <label className="flex items-center gap-3 text-sm">
            <Checkbox
              checked={includePoor}
              onCheckedChange={(v) => setIncludePoor(Boolean(v))}
              data-testid="export-poor"
            />
            <Label className="cursor-pointer">
              {t("questionsExportPoor")}
            </Label>
          </label>
          <p className="rounded-md bg-muted/50 p-2 text-xs text-muted-foreground">
            {t("questionsExportNote")}
          </p>
        </div>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={downloading}
          >
            {tc("cancel")}
          </Button>
          <Button
            onClick={handleDownload}
            disabled={downloading}
            data-testid="export-btn-download"
          >
            {downloading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <>
                <Download className="mr-1 size-4" />
                {t("questionsExportDownload")}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
