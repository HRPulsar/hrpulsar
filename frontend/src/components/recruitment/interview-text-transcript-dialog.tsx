"use client";

import { useState } from "react";
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
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    if (!text.trim()) {
      toast.error("Enter the transcript text");
      return;
    }
    setSubmitting(true);
    try {
      const updated = await api.post<Interview>(
        `/recruitment/interviews/${interviewId}/transcript-text`,
        { text },
      );
      toast.success("Transcript saved");
      onSaved?.(updated);
      onOpenChange(false);
      setText("");
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : "Failed to save transcript",
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
          <DialogTitle>Paste text transcript</DialogTitle>
          <DialogDescription>
            Paste the full text. Lines prefixed with
            &ldquo;Interviewer:&rdquo; / &ldquo;Candidate:&rdquo; will be split into segments for
            AI analysis.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="rec-int-paste">Text</Label>
          <Textarea
            id="rec-int-paste"
            rows={14}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={
              "Interviewer: Tell me about yourself…\nCandidate: …"
            }
            data-testid="recruitment-interview-input-paste-text"
          />
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button
            onClick={() => void handleSubmit()}
            disabled={submitting}
            data-testid="recruitment-interview-btn-save-text-transcript"
          >
            {submitting ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Saving…
              </>
            ) : (
              <>
                <Sparkles className="size-4" />
                Save
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
