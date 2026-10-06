"use client";

import { useState, type FormEvent } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FormErrorBanner } from "@/components/ui/form-error";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { checkLocaleFor, requestLink, saveCheck, TURNSTILE_ACTIONS } from "@/lib/api/public-check";
import { useTurnstileGate, type TurnstileGate } from "@/lib/turnstile";

import { CaptchaGate } from "./captcha";
import { saveErrorKey } from "./errors";
import { useOwnerKey } from "./owner-key";

// ponytail: the product links no privacy policy anywhere yet; the landing
// serves it here. Move to a shared setting once a white-label check needs its own.
export const PRIVACY_URL = "https://hrpulsar.com/privacy";

const CHECKBOX_CLASS = "mt-0.5 size-4 shrink-0 accent-primary";

/** The submit of a form behind the captcha: busy, or verifying, or ready.
 * Never disabled for a missing field - the click says what is missing. */
function SubmitButton({
  turnstile,
  busy,
  label,
  testId,
}: {
  turnstile: TurnstileGate;
  busy: boolean;
  label: string;
  testId: string;
}) {
  const tAuth = useTranslations("auth");
  return (
    <Button
      type="submit"
      size="lg"
      className="h-11 px-6 text-base"
      disabled={busy || !turnstile.isReady}
      data-testid={testId}
    >
      {busy ? <Loader2 className="animate-spin" /> : null}
      {!turnstile.isReady && !turnstile.failed ? tAuth("verifying") : label}
    </Button>
  );
}

/**
 * "Keep this result" on the result page (HRP-926): the address, the required
 * consent with the privacy policy, a separate optional opt-in to product
 * news, the captcha. Every address - confirmed before or not - gets a letter
 * to confirm this result: a save proves nothing about owning the address, so
 * the answer never says which it was, and the result keeps its term until
 * the click. Letters go out in the address's language.
 */
export function SaveResults({
  token,
  expiresAt,
}: {
  token: string;
  /** The check's term: a check kept already has nothing to save. */
  expiresAt: string | null;
}) {
  const t = useTranslations("publicCheck");
  const locale = useLocale();
  const turnstile = useTurnstileGate(TURNSTILE_ACTIONS.save);
  // Only the browser that ran the check holds its owner key: a viewer of a
  // shared link sees no save block.
  const ownerKey = useOwnerKey(token);
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [marketing, setMarketing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !turnstile.isReady || !ownerKey) return;
    if (email.trim() === "" || !consent) {
      setErrorKey(email.trim() === "" ? "saveErrorEmail" : "saveConsentRequired");
      return;
    }
    setBusy(true);
    setErrorKey(null);
    try {
      await saveCheck(token, {
        email: email.trim(),
        consent: true,
        marketing,
        locale: checkLocaleFor(locale),
        owner_key: ownerKey,
        ...(turnstile.token ? { turnstile_token: turnstile.token } : {}),
      });
      setSentTo(email.trim());
    } catch (err) {
      setErrorKey(saveErrorKey(err));
    } finally {
      // Single-use: a retry or a second save needs a fresh token.
      turnstile.reset();
      setBusy(false);
    }
  }

  if ((!expiresAt || !ownerKey) && sentTo === null) return null;
  return (
    <section className="space-y-4 rounded-xl border p-5 sm:p-6" data-testid="check-save">
      <div className="space-y-1">
        <h2 className="text-xl font-semibold tracking-tight">{t("saveTitle")}</h2>
        <p className="text-sm text-muted-foreground">{t("saveLead")}</p>
      </div>
      {sentTo !== null ? (
        <p role="status" data-testid="check-save-sent">
          {t("saveSent", { email: sentTo })}
        </p>
      ) : (
        <form onSubmit={submit} className="space-y-4" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="check-save-email">{t("emailLabel")}</Label>
            <Input
              id="check-save-email"
              type="email"
              autoComplete="email"
              required
              maxLength={320}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-invalid={errorKey === "saveErrorEmail"}
              data-testid="check-save-input-email"
            />
          </div>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className={CHECKBOX_CLASS}
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              required
              aria-invalid={errorKey === "saveConsentRequired"}
              data-testid="check-save-consent"
            />
            <span>
              {t.rich("saveConsent", {
                privacy: (chunks) => (
                  <a
                    href={PRIVACY_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary underline"
                    data-testid="check-save-privacy-link"
                  >
                    {chunks}
                  </a>
                ),
              })}
            </span>
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className={CHECKBOX_CLASS}
              checked={marketing}
              onChange={(e) => setMarketing(e.target.checked)}
              data-testid="check-save-marketing"
            />
            <span className="text-muted-foreground">{t("saveMarketing")}</span>
          </label>
          <CaptchaGate turnstile={turnstile} />
          <FormErrorBanner message={errorKey ? t(errorKey) : null} testId="check-save-error" />
          <SubmitButton
            turnstile={turnstile}
            busy={busy}
            label={t("saveSubmit")}
            testId="check-save-btn-submit"
          />
        </form>
      )}
    </section>
  );
}

/**
 * "Send me my link" (HRP-926): on "my checks" without a link, and where a
 * letter's link no longer works. The answer is the same whatever the address
 * - a confirmed one gets its "my checks" link, an unconfirmed one a new
 * letter to confirm it.
 */
export function LinkRequestForm() {
  const t = useTranslations("publicCheck");
  const turnstile = useTurnstileGate(TURNSTILE_ACTIONS.link);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [errorKey, setErrorKey] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !turnstile.isReady) return;
    if (email.trim() === "") {
      setErrorKey("saveErrorEmail");
      return;
    }
    setBusy(true);
    setErrorKey(null);
    try {
      await requestLink({
        email: email.trim(),
        ...(turnstile.token ? { turnstile_token: turnstile.token } : {}),
      });
      setSent(true);
    } catch (err) {
      setErrorKey(saveErrorKey(err, "errorUnavailable"));
    } finally {
      turnstile.reset();
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <p role="status" data-testid="check-link-sent">
        {t("linkSent")}
      </p>
    );
  }
  return (
    <form onSubmit={submit} className="space-y-4" noValidate data-testid="check-link-request">
      <div className="space-y-1.5">
        <Label htmlFor="check-link-email">{t("emailLabel")}</Label>
        <Input
          id="check-link-email"
          type="email"
          autoComplete="email"
          required
          maxLength={320}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          aria-invalid={errorKey === "saveErrorEmail"}
          data-testid="check-link-input-email"
        />
      </div>
      <CaptchaGate turnstile={turnstile} />
      <FormErrorBanner message={errorKey ? t(errorKey) : null} testId="check-link-error" />
      <SubmitButton
        turnstile={turnstile}
        busy={busy}
        label={t("linkSubmit")}
        testId="check-link-btn-submit"
      />
    </form>
  );
}
