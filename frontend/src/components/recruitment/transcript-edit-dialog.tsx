"use client";

import { useEffect, useState } from "react";
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
      toast.success("Transcript saved (PII automatically masked)");
      onUpdated?.(updated);
      onOpenChange(false);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to save transcript",
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
          <DialogTitle>Edit transcript</DialogTitle>
          <DialogDescription>
            Free-form editing of the entire transcript. After saving, the
            text is run through the PII filter (ID numbers and personal
            identifiers are masked automatically).
          </DialogDescription>
        </DialogHeader>
        <div className={`rounded-md border p-2 text-xs ${ALERT_TONE.amber}`}>
          <span className="flex items-start gap-1.5">
            <ShieldAlert className="mt-0.5 size-3.5" />
            Do not paste document numbers or contacts by hand — the system
            will mask them, but it is safer not to add them at all.
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
            Cancel
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
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
