"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { useAuth } from "@/context/auth-context";
import { submitFeedback, type FeedbackRating } from "@/lib/api/feedback";
import { FeedbackRatingButtons } from "@/components/feedback-rating";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

/** HRP-587: the ticket body asks for "~5 minutes", the acceptance criteria
 * for "~5 s". Five minutes is the accepted reading (a survey fired five
 * seconds in interrupts the tour it is asking about); the value is
 * overridable per deployment via NEXT_PUBLIC_DEMO_FEEDBACK_DELAY_MS. */
const DEFAULT_DELAY_MS = 5 * 60_000;

/** Shown once per demo sandbox — keyed by tenant so a genuinely new demo
 * session asks again, while reloads and extra tabs do not. */
const STORAGE_PREFIX = "demo_feedback_done:";

/** First time this sandbox rendered the dashboard — the delay counts from
 * here, not from the latest mount: reloads and route-group switches used
 * to restart the countdown, so the most engaged visitors (the ones who
 * navigate) never reached it. */
const START_PREFIX = "demo_feedback_start:";

function delayMs(): number {
  const raw =
    (typeof window !== "undefined" &&
      window.__ENV__?.NEXT_PUBLIC_DEMO_FEEDBACK_DELAY_MS) ||
    process.env.NEXT_PUBLIC_DEMO_FEEDBACK_DELAY_MS;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : DEFAULT_DELAY_MS;
}

/** Delayed, dismissable feedback card for demo sandboxes (HRP-587).
 * Renders nothing outside a demo session — `tenant_is_demo` is never set
 * on a community build, so the component is inert there. */
export function DemoFeedbackPopup() {
  const { user } = useAuth();
  const t = useTranslations("feedback");
  const [visible, setVisible] = useState(false);
  const [rating, setRating] = useState<FeedbackRating | null>(null);
  const [clarity, setClarity] = useState<"yes" | "no" | null>(null);
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);

  const isDemo = !!user?.tenant_is_demo;
  const storageKey = user ? `${STORAGE_PREFIX}${user.tenant_id}` : "";
  const startKey = user ? `${START_PREFIX}${user.tenant_id}` : "";

  useEffect(() => {
    if (!isDemo || !storageKey) return;
    if (localStorage.getItem(storageKey)) return;
    const now = Date.now();
    const stored = Number(localStorage.getItem(startKey));
    const start = Number.isFinite(stored) && stored > 0 ? stored : now;
    if (start === now) localStorage.setItem(startKey, String(now));
    const id = setTimeout(
      () => setVisible(true),
      Math.max(0, start + delayMs() - now),
    );
    return () => clearTimeout(id);
  }, [isDemo, storageKey, startKey]);

  function close() {
    setVisible(false);
    localStorage.setItem(storageKey, "1");
  }

  async function send(e: React.FormEvent) {
    // Submitting through a <form> lets the browser reject a malformed
    // optional email with its own localized hint, instead of the user
    // meeting a raw 422 from the EmailStr field.
    e.preventDefault();
    setSending(true);
    try {
      await submitFeedback({
        source: "demo",
        rating,
        clarity,
        message: message.trim(),
        contact_email: email.trim() || null,
      });
      toast.success(t("sent"));
      close();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("failed"));
    } finally {
      setSending(false);
    }
  }

  if (!visible) return null;

  return (
    <form
      onSubmit={send}
      // Corner card, never a backdrop: the demo tour behind it stays
      // clickable (acceptance criterion 3).
      className="fixed bottom-4 right-4 z-50 w-[min(24rem,calc(100vw-2rem))] space-y-3 rounded-xl border border-border bg-popover p-4 text-sm text-popover-foreground shadow-xl"
      data-testid="demo-feedback-popup"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="font-semibold">{t("demoTitle")}</p>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={t("dismiss")}
          onClick={close}
          data-testid="demo-feedback-dismiss"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="space-y-1.5">
        <p className="text-muted-foreground">{t("demoRatingQuestion")}</p>
        <FeedbackRatingButtons
          value={rating}
          onChange={setRating}
          testIdPrefix="demo-feedback"
        />
      </div>

      <div className="space-y-1.5">
        <p className="text-muted-foreground">{t("demoClarityQuestion")}</p>
        <div className="flex gap-2">
          {(["yes", "no"] as const).map((value) => (
            <Button
              key={value}
              type="button"
              variant={clarity === value ? "default" : "outline"}
              size="sm"
              onClick={() => setClarity(value)}
              data-testid={`demo-feedback-clarity-${value}`}
            >
              {value === "yes" ? t("clarityYes") : t("clarityNo")}
            </Button>
          ))}
        </div>
      </div>

      <div className="space-y-1.5">
        <p className="text-muted-foreground">{t("messageQuestion")}</p>
        <Textarea
          rows={3}
          maxLength={2000}
          value={message}
          placeholder={t("messagePlaceholder")}
          onChange={(e) => setMessage(e.target.value)}
          data-testid="demo-feedback-input-message"
        />
      </div>

      <div className="space-y-1.5">
        <p className="text-muted-foreground">{t("demoEmailQuestion")}</p>
        <Input
          type="email"
          value={email}
          placeholder={t("emailPlaceholder")}
          onChange={(e) => setEmail(e.target.value)}
          data-testid="demo-feedback-input-email"
        />
      </div>

      <Button
        type="submit"
        className="w-full"
        disabled={sending || (!rating && !clarity && !message.trim())}
        data-testid="demo-feedback-submit"
      >
        {sending ? t("sending") : t("send")}
      </Button>
    </form>
  );
}
