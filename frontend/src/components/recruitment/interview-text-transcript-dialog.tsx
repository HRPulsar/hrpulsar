"use client";

import { useState } from "react";
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
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import type { Interview } from "@/lib/types";
import { toast } from "sonner";
import { Loader2, Sparkles } from "lucide-react";

interface InterviewTextTranscriptDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  interviewId: string;
  onSaved?: (interview: Interview) => void;
}

export function InterviewTextTranscriptDialog({
  open,
  onOpenChange,
  interviewId,
  onSaved,
}: InterviewTextTranscriptDialogProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    if (!text.trim()) {
      toast.error(t("textTranscriptEmptyError"));
      return;
    }
    setSubmitting(true);
    try {
      const updated = await api.post<Interview>(
        `/recruitment/interviews/${interviewId}/transcript-text`,
        { text },
      );
      toast.success(t("textTranscriptToastSaved"));
      onSaved?.(updated);
      onOpenChange(false);
      setText("");
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : t("textTranscriptSaveFailed"),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-2xl"
        data-testid="recruitment-interview-text-transcript-dialog"
      >
        <DialogHeader>
          <DialogTitle>{t("interviewPasteText")}</DialogTitle>
          <DialogDescription>{t("textTranscriptDescription")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="rec-int-paste">{t("textTranscriptTextLabel")}</Label>
          <Textarea
            id="rec-int-paste"
            rows={14}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t("textTranscriptPlaceholder")}
            data-testid="recruitment-interview-input-paste-text"
          />
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            {tc("cancel")}
          </Button>
          <Button
            onClick={() => void handleSubmit()}
            disabled={submitting}
            data-testid="recruitment-interview-btn-save-text-transcript"
          >
            {submitting ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                {t("textTranscriptSaving")}
              </>
            ) : (
              <>
                <Sparkles className="size-4" />
                {t("save")}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
