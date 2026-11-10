"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { useAuth } from "@/context/auth-context";
import { MUTATION_EVENT, type MutationEventDetail } from "@/lib/api";
import {
  submitFeedback,
  type FeedbackContext,
  type FeedbackRating,
} from "@/lib/api/feedback";
import { saveDemoAccess } from "@/lib/demo";
import { trackDemoConversion } from "@/lib/google-ads";
import { TURNSTILE_FAILED_MESSAGE_KEY, useTurnstileGate } from "@/lib/turnstile";
import { FeedbackRatingButtons } from "@/components/feedback-rating";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

/** HRP-1158: the timer card is for visitors who only browse, so it comes
 * after a minute (it was five, HRP-587). Overridable per deployment via
 * NEXT_PUBLIC_DEMO_FEEDBACK_DELAY_MS. */
const DEFAULT_DELAY_MS = 60_000;

/** A value moment's card shows this long after the request: room for the
 * router.push that follows a create to land first. */
const MOMENT_DELAY_MS = 1_500;

/** The timer card is shown once per demo sandbox — keyed by tenant so a
 * genuinely new demo session asks again, while reloads and extra tabs do
 * not. A value moment's card adds `:<context>`: once per kind. */
const STORAGE_PREFIX = "demo_feedback_done:";

/** First time this sandbox rendered the dashboard — the delay counts from
 * here, not from the latest mount: reloads and route-group switches used
 * to restart the countdown, so the most engaged visitors (the ones who
 * navigate) never reached it. */
const START_PREFIX = "demo_feedback_start:";

/** Contacts from the last call-back request, so the next one opens with
 * them filled in. Per tab (sessionStorage): the visitor's own details
 * need not outlive the browsing session. They never fill the save block:
 * a call-back request must not turn into an account request on Send. */
const CONTACT_PREFIX = "demo_feedback_contact:";

/** Save access requested from a card or the banner's modal (HRP-1160):
 * the save block and the banner's reminder stop asking. */
export const DEMO_SAVED_PREFIX = "demo_saved:";
/** A card's save block closed without an email — lets the banner remind. */
export const DEMO_SAVE_SKIPPED_PREFIX = "demo_save_skipped:";
/** Fired whenever one of the demo flags changes; the banner rereads them. */
export const DEMO_SAVE_STATE_EVENT = "hrpulsar:demo-save-state";

/** Fired by the demo banner's "Talk to us" button: opens the card right
 * away, whether or not the timer ran or the card was dismissed before. */
export const OPEN_DEMO_FEEDBACK_EVENT = "hrpulsar:demo-feedback-open";

// Storage can be off (private mode): a flag that cannot be read is unset,
// one that cannot be written is simply asked about again.
function stored(key: string, area: "local" | "session" = "local"): string | null {
  try {
    return (area === "local" ? localStorage : sessionStorage).getItem(key);
  } catch {
    return null;
  }
}

function store(key: string, value = "1", area: "local" | "session" = "local") {
  try {
    (area === "local" ? localStorage : sessionStorage).setItem(key, value);
  } catch {
    // Nothing to do — see above.
  }
}

/** Read one of the per-sandbox demo flags. */
export function demoFlag(prefix: string, tenantId: string): boolean {
  return !!stored(`${prefix}${tenantId}`);
}

/** Raise a per-sandbox demo flag and tell the banner. */
export function setDemoFlag(prefix: string, tenantId: string) {
  store(`${prefix}${tenantId}`);
  window.dispatchEvent(new Event(DEMO_SAVE_STATE_EVENT));
}

type MomentContext = Exclude<FeedbackContext, "timer">;
type Moment = { context: MomentContext; title: string | null };

/** Value moments (HRP-1158): a successful POST to `path` opens the card
 * for `context`, once per sandbox. `:id` stands for any one segment;
 * `title` names the response field that names the object, where there
 * is one. */
const TRIGGERS: { path: string; context: MomentContext; title?: string }[] = [
  { path: "/pdp", context: "pdp_created", title: "title" },
  { path: "/assessments", context: "assessment_created", title: "employee_name" },
  { path: "/assessment-groups", context: "assessment_created", title: "title" },
  { path: "/work/decomposition/sessions/:id/apply", context: "decomposition_applied" },
  { path: "/work/containers/:id/gaps/hire-need", context: "hire_need_created" },
];

export function matchMoment(detail: MutationEventDetail): Moment | null {
  if (detail.method !== "POST") return null;
  const parts = detail.path.split("/");
  const row = TRIGGERS.find(({ path }) => {
    const want = path.split("/");
    return (
      want.length === parts.length &&
      want.every((seg, i) => (seg.startsWith(":") ? !!parts[i] : seg === parts[i]))
    );
  });
  if (!row) return null;
  const data = (detail.data ?? {}) as Record<string, unknown>;
  const raw = row.title ? data[row.title] : null;
  const title = typeof raw === "string" ? raw.trim().slice(0, 200) : "";
  return {
    // A plan made from an assessment's growth areas is a moment of its own.
    context:
      row.context === "pdp_created" && data.assessment_id
        ? "pdp_from_assessment"
        : row.context,
    title: title || null,
  };
}

/** Catalog keys per moment: the heading, the heading that names the
 * object (where the response carries a name), and the one question the
 * card asks about it. */
const MOMENT_COPY: Record<
  MomentContext,
  { heading: string; named?: string; question: string }
> = {
  pdp_created: {
    heading: "demoPlanHeading",
    named: "demoPlanHeadingNamed",
    question: "demoPlanQuestion",
  },
  pdp_from_assessment: {
    heading: "demoPlanHeading",
    named: "demoPlanHeadingNamed",
    question: "demoPlanFromAssessmentQuestion",
  },
  assessment_created: {
    heading: "demoAssessmentHeading",
    named: "demoAssessmentHeadingNamed",
    question: "demoAssessmentQuestion",
  },
  decomposition_applied: {
    heading: "demoProcessHeading",
    question: "demoProcessQuestion",
  },
  hire_need_created: {
    heading: "demoHireNeedHeading",
    question: "demoHireNeedQuestion",
  },
};

const ANSWERS = [
  ["yes", "clarityYes"],
  ["partly", "answerPartly"],
  ["no", "clarityNo"],
] as const;

type Answer = (typeof ANSWERS)[number][0];
type Contacts = { name: string; email: string; phone: string };
type Card = "contact" | "moment" | "survey";

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

/** Dismissable corner card for demo sandboxes. One slot, three cards:
 * - "Talk to us" from the banner: a call-back request (HRP-587);
 * - a value moment — the visitor just made a plan, an assessment, a
 *   process breakdown or a hire need: one question about that object,
 *   once per kind (HRP-1158);
 * - the timer, for visitors who only browse: a short survey.
 * The last two carry the save-access block (HRP-1160) until an email was
 * left. Renders nothing outside a demo session — `tenant_is_demo` is
 * never set on a community build, so the component is inert there. */
export function DemoFeedbackPopup() {
  const { user } = useAuth();
  // An open call-back request takes the card; a moment or a survey that
  // falls due meanwhile waits and shows as soon as the request closes.
  const [contactOpen, setContactOpen] = useState(false);
  const [moment, setMoment] = useState<Moment | null>(null);
  const [surveyDue, setSurveyDue] = useState(false);
  const [saved, setSaved] = useState(false);
  // Remounts the card per opening and per kind: answers belong to their
  // card, also when a moment replaces an open timer card.
  const [opened, setOpened] = useState(0);

  const isDemo = !!user?.tenant_is_demo;
  const tenantId = user?.tenant_id ?? "";
  const doneKey = `${STORAGE_PREFIX}${tenantId}`;
  const startKey = `${START_PREFIX}${tenantId}`;
  const card: Card | null = contactOpen
    ? "contact"
    : moment
      ? "moment"
      : surveyDue
        ? "survey"
        : null;

  useEffect(() => {
    if (!isDemo || !tenantId) return;
    const sync = () => setSaved(demoFlag(DEMO_SAVED_PREFIX, tenantId));
    sync();
    window.addEventListener(DEMO_SAVE_STATE_EVENT, sync);
    return () => window.removeEventListener(DEMO_SAVE_STATE_EVENT, sync);
  }, [isDemo, tenantId]);

  useEffect(() => {
    if (!isDemo || !tenantId || stored(doneKey)) return;
    const now = Date.now();
    const start = Number(stored(startKey)) || now;
    if (start === now) store(startKey, String(now));
    const id = setTimeout(
      // A value moment since the mount means the visitor did more than
      // browse: its trigger marked the timer card done.
      () => !stored(doneKey) && setSurveyDue(true),
      Math.max(0, start + delayMs() - now),
    );
    return () => clearTimeout(id);
  }, [isDemo, tenantId, doneKey, startKey]);

  useEffect(() => {
    if (!isDemo || !tenantId) return;
    const pending: ReturnType<typeof setTimeout>[] = [];
    function onMutation(e: Event) {
      const hit = matchMoment((e as CustomEvent<MutationEventDetail>).detail);
      if (!hit) return;
      store(doneKey);
      if (stored(`${doneKey}:${hit.context}`)) return;
      pending.push(
        setTimeout(() => {
          // The moment replaces an open timer card. A moment card already
          // open keeps the slot; this one is not marked, so the next
          // action of its kind asks again.
          setSurveyDue(false);
          setMoment((open) => open ?? hit);
        }, MOMENT_DELAY_MS),
      );
    }
    window.addEventListener(MUTATION_EVENT, onMutation);
    return () => {
      window.removeEventListener(MUTATION_EVENT, onMutation);
      pending.forEach(clearTimeout);
    };
  }, [isDemo, tenantId, doneKey]);

  useEffect(() => {
    const open = () => setContactOpen(true);
    window.addEventListener(OPEN_DEMO_FEEDBACK_EVENT, open);
    return () => window.removeEventListener(OPEN_DEMO_FEEDBACK_EVENT, open);
  }, []);

  /** Closes the given card — for a send, the one it was sent from. */
  function close(which: Card, skippedSave: boolean) {
    if (which === "contact") setContactOpen(false);
    if (which === "moment" && moment) {
      store(`${doneKey}:${moment.context}`);
      setMoment(null);
    }
    if (which === "survey") {
      store(doneKey);
      setSurveyDue(false);
    }
    if (skippedSave) setDemoFlag(DEMO_SAVE_SKIPPED_PREFIX, tenantId);
    setOpened((n) => n + 1);
  }

  if (!isDemo || !card) return null;
  return (
    <DemoCard
      key={`${opened}:${card}`}
      card={card}
      moment={moment}
      saved={saved}
      tenantId={tenantId}
      onClose={(skippedSave) => close(card, skippedSave)}
    />
  );
}

function DemoCard({
  card,
  moment,
  saved,
  tenantId,
  onClose,
}: {
  card: Card;
  moment: Moment | null;
  saved: boolean;
  tenantId: string;
  onClose: (skippedSave: boolean) => void;
}) {
  const t = useTranslations("feedback");
  // Save-access copy shared with the banner's modal.
  const tDemo = useTranslations("dashboard");
  // The Turnstile failure copy is shared with the signup form (HRP-476).
  const tAuth = useTranslations("auth");
  const turnstile = useTurnstileGate();
  const contactKey = `${CONTACT_PREFIX}${tenantId}`;
  const [rating, setRating] = useState<FeedbackRating | null>(null);
  const [clarity, setClarity] = useState<"yes" | "no" | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [message, setMessage] = useState("");
  const [contacts, setContacts] = useState<Contacts>(() => {
    try {
      return {
        name: "",
        email: "",
        phone: "",
        ...JSON.parse(stored(contactKey, "session") ?? "{}"),
      };
    } catch {
      return { name: "", email: "", phone: "" };
    }
  });
  const [saveEmail, setSaveEmail] = useState("");
  const [saveName, setSaveName] = useState("");
  const [sending, setSending] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  // A Send that half-failed is retried without the half that went through.
  const feedbackSent = useRef(false);
  const savedHere = useRef(false);

  const contact = card === "contact";
  const showSave = !contact && !saved;
  const email = saveEmail.trim();
  const hasFeedback =
    card === "moment"
      ? !!(answer || message.trim())
      : !!(rating || clarity || message.trim());
  const wantsSave = showSave && !!email;
  const verifying = wantsSave && !turnstile.isReady;
  // The call-back card needs an email or a phone: `required` makes the
  // browser say so on Send, instead of a disabled button with no reason.
  const reachable = !!(contacts.email.trim() || contacts.phone.trim());
  const canSend = contact || ((hasFeedback || wantsSave) && !verifying);

  function setContact(field: keyof Contacts, value: string) {
    setContacts((prev) => ({ ...prev, [field]: value }));
  }

  async function sendContact() {
    await submitFeedback({
      source: "demo",
      message: message.trim(),
      contact_name: contacts.name.trim() || null,
      contact_email: contacts.email.trim() || null,
      contact_phone: contacts.phone.trim() || null,
    });
    store(contactKey, JSON.stringify(contacts), "session");
    toast.success(t("sent"));
    onClose(false);
  }

  async function sendCard() {
    const failed: string[] = [];
    const reason = (err: unknown, fallback: string) =>
      err instanceof Error && err.message ? err.message : fallback;
    const jobs: Promise<void>[] = [];
    if (hasFeedback && !feedbackSent.current) {
      jobs.push(
        submitFeedback({
          source: "demo",
          context: moment?.context ?? "timer",
          context_title: moment?.title ?? null,
          answer: card === "moment" ? answer : null,
          rating: card === "survey" ? rating : null,
          clarity: card === "survey" ? clarity : null,
          message: message.trim(),
          // Ties the answer to the save-access request on the Slack side.
          contact_email: email || null,
          contact_name: (email && saveName.trim()) || null,
        }).then(
          () => {
            feedbackSent.current = true;
          },
          (err) => {
            failed.push(reason(err, t("failed")));
          },
        ),
      );
    }
    if (wantsSave) {
      jobs.push(
        saveDemoAccess({
          email,
          first_name: saveName.trim() || null,
          turnstile_token: turnstile.token,
          // The block exists to keep the sandbox: no checkbox to forget.
          keep_demo_data: true,
        }).then(
          () => {
            savedHere.current = true;
            // HRP-1052: a signup request is the demo conversion.
            trackDemoConversion();
            setDemoFlag(DEMO_SAVED_PREFIX, tenantId);
          },
          (err) => {
            failed.push(reason(err, tDemo("demoSaveFailed")));
            // Single-use token was burned; refresh for the retry.
            turnstile.reset();
          },
        ),
      );
    }
    await Promise.all(jobs);
    if (failed.length) {
      setErrors(failed);
      return;
    }
    toast.success(savedHere.current ? t("demoSaveSent") : t("sent"));
    onClose(showSave && !savedHere.current);
  }

  async function send(e: React.FormEvent) {
    // Submitting through a <form> lets the browser reject a malformed
    // email with its own localized hint, instead of a raw 422.
    e.preventDefault();
    setSending(true);
    setErrors([]);
    try {
      if (contact) await sendContact();
      else await sendCard();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("failed"));
    } finally {
      setSending(false);
    }
  }

  const copy = moment && card === "moment" ? MOMENT_COPY[moment.context] : null;
  const heading = contact
    ? t("demoContactTitle")
    : copy
      ? moment?.title && copy.named
        ? t(copy.named, { title: moment.title })
        : t(copy.heading)
      : t("demoTitle");

  return (
    <form
      onSubmit={send}
      // Corner card, never a backdrop: the demo tour behind it stays
      // clickable (HRP-587 acceptance criterion 3).
      className="fixed bottom-4 right-4 z-50 max-h-[calc(100vh-2rem)] w-[min(24rem,calc(100vw-2rem))] space-y-3 overflow-y-auto rounded-xl border border-border bg-popover p-4 text-sm text-popover-foreground shadow-xl"
      data-testid="demo-feedback-popup"
      data-context={copy ? moment?.context : card}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="font-semibold" data-testid="demo-feedback-heading">
          {heading}
        </p>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={t("dismiss")}
          onClick={() => onClose(showSave)}
          data-testid="demo-feedback-dismiss"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {contact && (
        <div className="space-y-1.5">
          <Input
            value={contacts.name}
            maxLength={100}
            autoComplete="name"
            placeholder={t("namePlaceholder")}
            aria-label={t("namePlaceholder")}
            onChange={(e) => setContact("name", e.target.value)}
            data-testid="demo-feedback-input-name"
          />
          <Input
            type="email"
            value={contacts.email}
            required={!reachable}
            autoComplete="email"
            placeholder={t("emailPlaceholder")}
            aria-label={t("emailLabel")}
            onChange={(e) => setContact("email", e.target.value)}
            data-testid="demo-feedback-input-email"
          />
          {phoneEnabled() && (
            <Input
              type="tel"
              value={contacts.phone}
              required={!reachable}
              maxLength={40}
              autoComplete="tel"
              placeholder={t("phonePlaceholder")}
              aria-label={t("phoneLabel")}
              onChange={(e) => setContact("phone", e.target.value)}
              data-testid="demo-feedback-input-phone"
            />
          )}
        </div>
      )}

      {copy && (
        <div className="space-y-1.5">
          <p className="text-muted-foreground">{t(copy.question)}</p>
          <div className="flex gap-2">
            {ANSWERS.map(([value, label]) => (
              <Button
                key={value}
                type="button"
                variant={answer === value ? "default" : "outline"}
                size="sm"
                aria-pressed={answer === value}
                onClick={() => setAnswer(value)}
                data-testid={`demo-feedback-answer-${value}`}
              >
                {t(label)}
              </Button>
            ))}
          </div>
        </div>
      )}

      {card === "survey" && (
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
          {contact
            ? t("demoContactMessageQuestion")
            : copy
              ? t("demoWhatsOff")
              : t("messageQuestion")}
        </p>
        <Textarea
          rows={copy ? 2 : 3}
          maxLength={2000}
          value={message}
          placeholder={card === "survey" ? t("messagePlaceholder") : undefined}
          onChange={(e) => setMessage(e.target.value)}
          data-testid="demo-feedback-input-message"
        />
      </div>

      {showSave && (
        <div
          className="space-y-1.5 border-t border-border pt-3"
          data-testid="demo-feedback-save"
        >
          <p className="font-medium">{t("demoSaveQuestion")}</p>
          <Input
            type="email"
            value={saveEmail}
            // Only a name typed without an email needs pointing out.
            required={!!saveName.trim()}
            maxLength={320}
            autoComplete="email"
            placeholder={t("emailPlaceholder")}
            aria-label={t("emailLabel")}
            onChange={(e) => setSaveEmail(e.target.value)}
            data-testid="demo-feedback-save-email"
          />
          <Input
            value={saveName}
            maxLength={100}
            autoComplete="name"
            placeholder={t("demoSaveNamePlaceholder")}
            aria-label={t("demoSaveNamePlaceholder")}
            onChange={(e) => setSaveName(e.target.value)}
            data-testid="demo-feedback-save-name"
          />
          {turnstile.failed && (
            <p
              className="text-destructive"
              data-testid="demo-feedback-save-verify-error"
            >
              {tAuth(TURNSTILE_FAILED_MESSAGE_KEY)}{" "}
              <button
                type="button"
                onClick={turnstile.reset}
                className="font-semibold underline"
              >
                {tDemo("demoRetry")}
              </button>
            </p>
          )}
          {turnstile.widget}
        </div>
      )}

      {errors.length > 0 && (
        <div
          className="space-y-1 rounded-md bg-destructive/10 px-3 py-2 text-destructive"
          role="alert"
          data-testid="demo-feedback-error"
        >
          {errors.map((text) => (
            <p key={text}>{text}</p>
          ))}
        </div>
      )}

      <Button
        type="submit"
        className="w-full"
        disabled={sending || !canSend}
        data-testid="demo-feedback-submit"
      >
        {sending
          ? t("sending")
          : verifying && !turnstile.failed
            ? tDemo("demoVerifying")
            : t("send")}
      </Button>
    </form>
  );
}
