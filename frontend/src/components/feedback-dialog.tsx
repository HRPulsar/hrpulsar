"use client";

import { useState } from "react";
import { CircleHelp } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { submitFeedback, type FeedbackRating } from "@/lib/api/feedback";
import { FeedbackRatingButtons } from "@/components/feedback-rating";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/** "?" button in the app header: rate the product and leave a comment
 * (HRP-586). The submission reaches the team's chat channel; nothing is
 * stored in the workspace. */
export function FeedbackDialog() {
  const t = useTranslations("feedback");
  const [open, setOpen] = useState(false);
  const [rating, setRating] = useState<FeedbackRating | null>(null);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);

  async function send() {
    setSending(true);
    try {
      await submitFeedback({ rating, message: message.trim(), source: "platform" });
      toast.success(t("sent"));
      setOpen(false);
      setRating(null);
      setMessage("");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("failed"));
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={t("open")}
        onClick={() => setOpen(true)}
        data-testid="header-btn-feedback"
      >
        <CircleHelp className="h-4 w-4" />
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="feedback-dialog">
          <DialogHeader>
            <DialogTitle>{t("title")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <p className="font-medium">{t("ratingQuestion")}</p>
            <FeedbackRatingButtons
              value={rating}
              onChange={setRating}
              testIdPrefix="feedback"
            />
          </div>
          <div className="space-y-2">
            <p className="font-medium">{t("messageQuestion")}</p>
            <Textarea
              rows={4}
              maxLength={2000}
              value={message}
              placeholder={t("messagePlaceholder")}
              onChange={(e) => setMessage(e.target.value)}
              data-testid="feedback-input-message"
            />
          </div>
          <DialogFooter>
            <Button
              onClick={send}
              // Nothing to say yet — the backend rejects an empty submission,
              // so the button gates on the same condition.
              disabled={sending || (!rating && !message.trim())}
              data-testid="feedback-submit"
            >
              {sending ? t("sending") : t("send")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
