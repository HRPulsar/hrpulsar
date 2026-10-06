"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Check, Loader2 } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { FormErrorBanner } from "@/components/ui/form-error";
import { ApiError } from "@/lib/api";
import {
  DESCRIPTION_MAX,
  DESCRIPTION_MIN,
  createCheck,
  getCheck,
  type CheckPhase,
  type CheckRead,
  TURNSTILE_ACTIONS,
} from "@/lib/api/public-check";
import { useTurnstileGate } from "@/lib/turnstile";
import { cn } from "@/lib/utils";

import { CaptchaGate } from "./captcha";
import { createErrorKey, runErrorKey } from "./errors";
import { forgetOwnerKey, rememberOwnerKey } from "./owner-key";
import { ExpiresNote, ResultView } from "./result-view";

/** The GET is cheap and has no create limit (HRP-923 contract): every
 * 1.5 s while the check runs, twice that after a failed poll. */
export const POLL_MS = 1500;

/** Failed polls in a row before the page stops asking and says so. */
export const MAX_POLL_FAILURES = 10;

/** The progress bar's steps; `key: null` is the queue. */
const PHASE_KEYS: { key: CheckPhase | null; label: string }[] = [
  { key: null, label: "phaseQueued" },
  { key: "splitting", label: "phaseSplitting" },
  { key: "classifying", label: "phaseClassifying" },
  { key: "finishing", label: "phaseFinishing" },
];

interface CheckResultPageProps {
  token: string;
  inputHref: string;
  resultBase: string;
  registerHref: string;
  /** The canonical address of this result, on the check host (HRP-928). */
  shareUrl: string;
}

export function CheckResultPage({
  token,
  inputHref,
  resultBase,
  registerHref,
  shareUrl,
}: CheckResultPageProps) {
  const [check, setCheck] = useState<CheckRead | null>(null);
  const [missing, setMissing] = useState(false);
  const [offline, setOffline] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  // Bumped by "try again" on the unavailable state: restarts the polling.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      try {
        const data = await getCheck(token);
        if (cancelled) return;
        // "ready" without a result breaks the contract: a failed poll,
        // not a page stuck on the progress bar.
        if (data.status === "ready" && !data.result) throw new Error("ready without a result");
        failures = 0;
        // Kept without a term: nothing left to save with the owner key.
        if (data.expires_at === null) forgetOwnerKey(token);
        setCheck(data);
        setOffline(false);
        if (data.status === "pending" || data.status === "running") {
          timer = setTimeout(poll, POLL_MS);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          forgetOwnerKey(token); // gone or past its term
          setMissing(true);
          return;
        }
        // A blip (network, a restart, a soft limit) must not end a check
        // that is still running on the server: keep asking, slower - but
        // not forever: a server that stays away is said so, with a retry.
        failures += 1;
        if (failures >= MAX_POLL_FAILURES) {
          setUnavailable(true);
          return;
        }
        setOffline(true);
        timer = setTimeout(poll, POLL_MS * 2);
      }
    }
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [token, attempt]);

  if (missing) return <NotFound inputHref={inputHref} />;
  if (unavailable) {
    return (
      <Unavailable
        onRetry={() => {
          setUnavailable(false);
          setOffline(false);
          setAttempt((n) => n + 1);
        }}
      />
    );
  }
  if (!check) return <Loading offline={offline} />;
  if (check.status === "error") {
    return <RunError check={check} inputHref={inputHref} resultBase={resultBase} />;
  }
  if (check.status === "ready" && check.result) {
    return (
      <ResultView
        check={check}
        result={check.result}
        inputHref={inputHref}
        registerHref={registerHref}
        shareUrl={shareUrl}
        save={{ token }}
      />
    );
  }
  return <Progress check={check} offline={offline} />;
}

function Loading({ offline }: { offline: boolean }) {
  const t = useTranslations("publicCheck");
  return (
    <div
      role="status"
      aria-busy="true"
      className="flex flex-col items-center gap-3 py-16"
      data-testid="check-loading"
    >
      <Loader2 className="size-6 animate-spin text-muted-foreground" aria-hidden="true" />
      <span className="sr-only">{t("loadingLabel")}</span>
      {offline ? <p className="text-sm text-muted-foreground">{t("reconnecting")}</p> : null}
    </div>
  );
}

/** Polling gave up after MAX_POLL_FAILURES: "try again" asks again - the
 * check itself may well be fine on the server. */
function Unavailable({ onRetry }: { onRetry: () => void }) {
  const t = useTranslations("publicCheck");
  return (
    <section className="space-y-4" role="alert" data-testid="check-unavailable">
      <h1 className="text-2xl font-semibold tracking-tight">{t("unavailableTitle")}</h1>
      <p className="text-muted-foreground">{t("errorUnavailable")}</p>
      <Button size="lg" onClick={onRetry} data-testid="check-btn-repoll">
        {t("retry")}
      </Button>
    </section>
  );
}

function Progress({ check, offline }: { check: CheckRead; offline: boolean }) {
  const t = useTranslations("publicCheck");
  const current = Math.max(
    0,
    PHASE_KEYS.findIndex((step) => step.key === check.phase),
  );
  // Never 0 or 100: the queue already counts, and done is the result page.
  const value = Math.round(((current + 1) / (PHASE_KEYS.length + 1)) * 100);
  return (
    <section className="space-y-6" data-testid="check-progress" aria-live="polite">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          {t("progressTitle")}
        </h1>
        <p className="text-muted-foreground">{t("progressLead")}</p>
      </div>
      <div
        role="progressbar"
        aria-label={t("progressLabel")}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value}
        aria-valuetext={t(PHASE_KEYS[current].label)}
        data-testid="check-progress-bar"
        data-phase={check.phase ?? "queued"}
        className="h-2 overflow-hidden rounded-full bg-muted"
      >
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-700"
          style={{ width: `${value}%` }}
        />
      </div>
      <ol className="space-y-2">
        {PHASE_KEYS.map((step, index) => (
          <li
            key={step.label}
            className={cn(
              "flex items-center gap-2 text-sm",
              index > current && "text-muted-foreground",
              index === current && "font-medium",
            )}
          >
            {index < current ? (
              <Check className="size-4 text-primary" />
            ) : index === current ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <span className="size-4" />
            )}
            {t(step.label)}
          </li>
        ))}
      </ol>
      {offline ? <p className="text-sm text-muted-foreground">{t("reconnecting")}</p> : null}
      <ExpiresNote expiresAt={check.expires_at} />
    </section>
  );
}

function RunError({
  check,
  inputHref,
  resultBase,
}: {
  check: CheckRead;
  inputHref: string;
  resultBase: string;
}) {
  const t = useTranslations("publicCheck");
  const router = useRouter();
  const turnstile = useTurnstileGate(TURNSTILE_ACTIONS.check);
  const [busy, setBusy] = useState(false);
  const [retryErrorKey, setRetryErrorKey] = useState<string | null>(null);

  // "Try again" is a new check with the same input: the failed one is
  // final on the server.
  async function retry() {
    if (busy || !turnstile.isReady) return;
    setBusy(true);
    setRetryErrorKey(null);
    try {
      const created = await createCheck({
        description: check.description,
        answers: check.answers,
        locale: check.locale,
        utm: check.utm,
        ...(check.dictated ? { dictated: true } : {}),
        ...(turnstile.token ? { turnstile_token: turnstile.token } : {}),
      });
      rememberOwnerKey(created.token, created.owner_key, created.expires_at);
      router.push(`${resultBase}/${created.token}`);
    } catch (err) {
      setRetryErrorKey(createErrorKey(err));
      turnstile.reset();
      setBusy(false);
    }
  }

  return (
    <section className="space-y-4" data-testid="check-run-error">
      <h1 className="text-2xl font-semibold tracking-tight">{t("runErrorTitle")}</h1>
      <p className="text-muted-foreground" data-error-code={check.error_code ?? undefined}>
        {t(runErrorKey(check.error_code))}
      </p>
      <CaptchaGate turnstile={turnstile} />
      <FormErrorBanner
        message={retryErrorKey ? t(retryErrorKey, { min: DESCRIPTION_MIN, max: DESCRIPTION_MAX }) : null}
        testId="check-retry-error"
      />
      <div className="flex flex-wrap items-center gap-3">
        <Button
          size="lg"
          onClick={retry}
          disabled={busy || !turnstile.isReady}
          data-testid="check-btn-retry"
        >
          {busy ? <Loader2 className="animate-spin" /> : null}
          {t("retry")}
        </Button>
        <Link href={inputHref} className="text-sm text-primary hover:underline" data-testid="check-link-new">
          {t("checkAnother")}
        </Link>
      </div>
    </section>
  );
}

function NotFound({ inputHref }: { inputHref: string }) {
  const t = useTranslations("publicCheck");
  return (
    <section className="space-y-4" data-testid="check-not-found">
      <h1 className="text-2xl font-semibold tracking-tight">{t("notFoundTitle")}</h1>
      <p className="text-muted-foreground">{t("notFoundText")}</p>
      <Link href={inputHref} className={buttonVariants({ size: "lg" })} data-testid="check-link-new">
        {t("checkAnother")}
      </Link>
    </section>
  );
}
