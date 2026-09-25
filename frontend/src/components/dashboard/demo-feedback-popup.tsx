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

/** Contacts from the last sent card, so the survey that follows a
 * call-back request opens with them filled in. Per tab (sessionStorage):
 * the visitor's own details need not outlive the browsing session. */
const CONTACT_PREFIX = "demo_feedback_contact:";

type Contacts = { name: string; email: string; phone: string };

function savedContacts(key: string): Partial<Contacts> | null {
  try {
    return JSON.parse(sessionStorage.getItem(key) ?? "null");
  } catch {
    return null;
  }
}

/** Fired by the demo banner's "Talk to us" button: opens the card right
 * away, whether or not the timer ran or the card was dismissed before. */
export const OPEN_DEMO_FEEDBACK_EVENT = "hrpulsar:demo-feedback-open";

function delayMs(): number {
  const raw =
    (typeof window !== "undefined" &&
      window.__ENV__?.NEXT_PUBLIC_DEMO_FEEDBACK_DELAY_MS) ||
    process.env.NEXT_PUBLIC_DEMO_FEEDBACK_DELAY_MS;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : DEFAULT_DELAY_MS;
}

/** Phone field for the call-back request — on for sites whose visitors
 * expect a call rather than an email (the RU site); off on the flagship. */
function phoneEnabled(): boolean {
  const raw =
    (typeof window !== "undefined" &&
      window.__ENV__?.NEXT_PUBLIC_DEMO_CONTACT_PHONE) ||
    process.env.NEXT_PUBLIC_DEMO_CONTACT_PHONE;
  return raw === "true";
}

/** Delayed, dismissable feedback card for demo sandboxes (HRP-587).
 * The timer opens it as a short survey; the banner's "Talk to us" button
 * opens it as a call-back request — contacts first, no survey questions.
 * Renders nothing outside a demo session — `tenant_is_demo` is never set
 * on a community build, so the component is inert there. */
export function DemoFeedbackPopup() {
  const { user } = useAuth();
  const t = useTranslations("feedback");
  // An open call-back request takes the card; a survey that falls due
  // meanwhile waits and shows as soon as the request closes.
  const [contactOpen, setContactOpen] = useState(false);
  const [surveyDue, setSurveyDue] = useState(false);
  const [rating, setRating] = useState<FeedbackRating | null>(null);
  const [clarity, setClarity] = useState<"yes" | "no" | null>(null);
  const [message, setMessage] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [sending, setSending] = useState(false);

  const isDemo = !!user?.tenant_is_demo;
  const storageKey = user ? `${STORAGE_PREFIX}${user.tenant_id}` : "";
  const startKey = user ? `${START_PREFIX}${user.tenant_id}` : "";
  const contactKey = user ? `${CONTACT_PREFIX}${user.tenant_id}` : "";
  const mode = contactOpen ? "contact" : surveyDue ? "survey" : null;

  useEffect(() => {
    if (!contactKey) return;
    const saved = savedContacts(contactKey);
    if (!saved) return;
    setName(saved.name ?? "");
    setEmail(saved.email ?? "");
    setPhone(saved.phone ?? "");
  }, [contactKey]);

  useEffect(() => {
    if (!isDemo || !storageKey) return;
    if (localStorage.getItem(storageKey)) return;
    const now = Date.now();
    const stored = Number(localStorage.getItem(startKey));
    const start = Number.isFinite(stored) && stored > 0 ? stored : now;
    if (start === now) localStorage.setItem(startKey, String(now));
    const id = setTimeout(
      () => setSurveyDue(true),
      Math.max(0, start + delayMs() - now),
    );
    return () => clearTimeout(id);
  }, [isDemo, storageKey, startKey]);

  useEffect(() => {
    const open = () => setContactOpen(true);
    window.addEventListener(OPEN_DEMO_FEEDBACK_EVENT, open);
    return () => window.removeEventListener(OPEN_DEMO_FEEDBACK_EVENT, open);
  }, []);

  /** Closes the given card — for a send, the one it was sent from: the
   * request resolves later, and the visitor may have switched cards. */
  function close(which: "survey" | "contact") {
    // Only the survey is once per sandbox: a call-back request, sent or
    // dismissed, still leaves the survey to come at its time.
    if (which === "survey") {
      localStorage.setItem(storageKey, "1");
      setSurveyDue(false);
    } else {
      setContactOpen(false);
    }
    // A comment belongs to its card, sent or dismissed.
    setMessage("");
  }

  async function send(e: React.FormEvent) {
    // Submitting through a <form> lets the browser reject a malformed
    // optional email with its own localized hint, instead of the user
    // meeting a raw 422 from the EmailStr field.
    e.preventDefault();
    if (!mode) return;
    const sentFrom = mode;
    const survey = sentFrom === "survey";
    setSending(true);
    try {
      await submitFeedback({
        source: "demo",
        // The survey's answers go with the survey only — the call-back
        // card does not show them.
        rating: survey ? rating : null,
        clarity: survey ? clarity : null,
        message: message.trim(),
        contact_name: name.trim() || null,
        contact_email: email.trim() || null,
        contact_phone: phone.trim() || null,
      });
      toast.success(t("sent"));
      try {
        sessionStorage.setItem(
          contactKey,
          JSON.stringify({ name, email, phone } satisfies Contacts),
        );
      } catch {
        // Storage off (private mode): the next card just starts empty.
      }
      // The contacts stay for the next card.
      close(sentFrom);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("failed"));
    } finally {
      setSending(false);
    }
  }

  if (!mode) return null;

  const contact = mode === "contact";
  const withPhone = phoneEnabled();
  // The call-back card needs an email or a phone: `required` makes the
  // browser say so on Send, instead of a disabled button with no reason
  // given. The survey needs an answer of its own — contacts carried over
  // from a call-back request are not one.
  const reachable = !!(email.trim() || phone.trim());
  const needContact = contact && !reachable;
  const canSend = contact || !!(rating || clarity || message.trim());

  const contactFields = (
    <div className="space-y-1.5">
      {!contact && (
        <p className="text-muted-foreground">{t("demoContactQuestion")}</p>
      )}
      <Input
        value={name}
        maxLength={100}
        autoComplete="name"
        placeholder={t("namePlaceholder")}
        aria-label={t("namePlaceholder")}
        onChange={(e) => setName(e.target.value)}
        data-testid="demo-feedback-input-name"
      />
      <Input
        type="email"
        value={email}
        required={needContact}
        autoComplete="email"
        placeholder={t("emailPlaceholder")}
        aria-label={t("emailLabel")}
        onChange={(e) => setEmail(e.target.value)}
        data-testid="demo-feedback-input-email"
      />
      {withPhone && (
        <Input
          type="tel"
          value={phone}
          required={needContact}
          maxLength={40}
          autoComplete="tel"
          placeholder={t("phonePlaceholder")}
          aria-label={t("phoneLabel")}
          onChange={(e) => setPhone(e.target.value)}
          data-testid="demo-feedback-input-phone"
        />
      )}
    </div>
  );

  return (
    <form
      onSubmit={send}
      // Corner card, never a backdrop: the demo tour behind it stays
      // clickable (acceptance criterion 3).
      className="fixed bottom-4 right-4 z-50 w-[min(24rem,calc(100vw-2rem))] space-y-3 rounded-xl border border-border bg-popover p-4 text-sm text-popover-foreground shadow-xl"
      data-testid="demo-feedback-popup"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="font-semibold">
          {contact ? t("demoContactTitle") : t("demoTitle")}
        </p>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={t("dismiss")}
          onClick={() => close(mode)}
          data-testid="demo-feedback-dismiss"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {contact && contactFields}

      {!contact && (
        <>
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
        </>
      )}

      <div className="space-y-1.5">
        <p className="text-muted-foreground">
          {contact ? t("demoContactMessageQuestion") : t("messageQuestion")}
        </p>
        <Textarea
          rows={3}
          maxLength={2000}
          value={message}
          placeholder={contact ? undefined : t("messagePlaceholder")}
          onChange={(e) => setMessage(e.target.value)}
          data-testid="demo-feedback-input-message"
        />
      </div>

      {!contact && contactFields}

      <Button
        type="submit"
        className="w-full"
        disabled={sending || !canSend}
        data-testid="demo-feedback-submit"
      >
        {sending ? t("sending") : t("send")}
      </Button>
    </form>
  );
}
