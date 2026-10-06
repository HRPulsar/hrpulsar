"use client";

import { useTranslations } from "next-intl";

import { TURNSTILE_FAILED_MESSAGE_KEY, type TurnstileGate } from "@/lib/turnstile";

/** The captcha of a create call (HRP-923): the widget, and when it fails,
 * the reason with a retry - as on the signup form. Nothing without a site
 * key. */
export function CaptchaGate({ turnstile }: { turnstile: TurnstileGate }) {
  const t = useTranslations("auth");
  return (
    <>
      {turnstile.widget}
      {turnstile.failed ? (
        <div
          className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
          data-testid="check-verify-error"
        >
          {t(TURNSTILE_FAILED_MESSAGE_KEY)}{" "}
          <button
            type="button"
            onClick={turnstile.reset}
            className="font-semibold underline"
            data-testid="check-verify-retry"
          >
            {t("retry")}
          </button>
        </div>
      ) : null}
    </>
  );
}
