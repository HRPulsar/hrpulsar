"use client";

import { useEffect, useState } from "react";
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
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import type { Interview } from "@/lib/types";
import { Loader2, Save, ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { ALERT_TONE } from "@/lib/badge-tones";

interface TranscriptEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  interview: Interview;
  onUpdated?: (interview: Interview) => void;
}

export function TranscriptEditDialog({
  open,
  onOpenChange,
  interview,
  onUpdated,
}: TranscriptEditDialogProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [text, setText] = useState<string>(interview.transcript || "");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) setText(interview.transcript || "");
  }, [open, interview.transcript]);

  async function handleSave() {
    setSubmitting(true);
    try {
      const updated = await api.put<Interview>(
        `/recruitment/interviews/${interview.id}/transcript`,
        { transcript: text },
      );
      toast.success(t("transcriptEditToastSaved"));
      onUpdated?.(updated);
      onOpenChange(false);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("transcriptEditSaveFailed"),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-3xl"
        data-testid="recruitment-transcript-edit-dialog"
      >
        <DialogHeader>
          <DialogTitle>{t("transcriptEditTitle")}</DialogTitle>
          <DialogDescription>{t("transcriptEditDescription")}</DialogDescription>
        </DialogHeader>
        <div className={`rounded-md border p-2 text-xs ${ALERT_TONE.amber}`}>
          <span className="flex items-start gap-1.5">
            <ShieldAlert className="mt-0.5 size-3.5" />
            {t("transcriptEditPiiWarning")}
          </span>
        </div>
        <Textarea
          rows={18}
          value={text}
          onChange={(e) => setText(e.target.value)}
          data-testid="recruitment-transcript-textarea"
          className="font-mono text-xs"
        />
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            {tc("cancel")}
          </Button>
          <Button
            onClick={handleSave}
            disabled={submitting}
            data-testid="recruitment-transcript-btn-save"
          >
            {submitting ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Save className="size-4" />
            )}
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
