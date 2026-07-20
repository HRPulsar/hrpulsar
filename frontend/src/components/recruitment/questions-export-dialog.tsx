"use client";

import { useState } from "react";
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
        err instanceof Error ? err.message : "Failed to export PDF";
      toast.error(message);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="questions-export-dialog">
        <DialogHeader>
          <DialogTitle>Export questions to PDF</DialogTitle>
          <DialogDescription>
            {candidateName && vacancyTitle
              ? `Questions for ${candidateName} — ${vacancyTitle}`
              : "Choose which reference answers to include in the PDF."}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Include reference answers
          </p>
          <label className="flex items-center gap-3 text-sm">
            <Checkbox
              checked={includeGood}
              onCheckedChange={(v) => setIncludeGood(Boolean(v))}
              data-testid="export-good"
            />
            <Label className="cursor-pointer">Good answer</Label>
          </label>
          <label className="flex items-center gap-3 text-sm">
            <Checkbox
              checked={includeAcceptable}
              onCheckedChange={(v) => setIncludeAcceptable(Boolean(v))}
              data-testid="export-acceptable"
            />
            <Label className="cursor-pointer">Acceptable answer</Label>
          </label>
          <label className="flex items-center gap-3 text-sm">
            <Checkbox
              checked={includePoor}
              onCheckedChange={(v) => setIncludePoor(Boolean(v))}
              data-testid="export-poor"
            />
            <Label className="cursor-pointer">Poor answer</Label>
          </label>
          <p className="rounded-md bg-muted/50 p-2 text-xs text-muted-foreground">
            PDF: questions grouped by competency, branded with your tenant.
          </p>
        </div>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={downloading}
          >
            Cancel
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
                Download
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
