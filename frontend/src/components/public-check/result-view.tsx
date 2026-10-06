"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";

import { buttonVariants } from "@/components/ui/button";
import type {
  Bucket,
  CheckRead,
  CheckResult,
  ResultStep,
  StepReason,
} from "@/lib/api/public-check";
import { cn } from "@/lib/utils";

import { ShareButtons } from "./share-buttons";
import { SaveResults } from "./save-results";

/** The three lists in the engine's order, with their catalog keys. */
const BUCKET_KEYS: {
  key: Bucket;
  testId: string;
  shareTestId: string;
  title: string;
  hint: string;
  bar: string;
}[] = [
  {
    key: "moves",
    testId: "check-list-moves",
    shareTestId: "check-share-moves",
    title: "bucketMovesTitle",
    hint: "bucketMovesHint",
    bar: "bg-primary",
  },
  {
    key: "to_review",
    testId: "check-list-to-review",
    shareTestId: "check-share-to-review",
    title: "bucketToReviewTitle",
    hint: "bucketToReviewHint",
    bar: "bg-primary/45",
  },
  {
    key: "stays",
    testId: "check-list-stays",
    shareTestId: "check-share-stays",
    title: "bucketStaysTitle",
    hint: "bucketStaysHint",
    bar: "bg-muted-foreground/25",
  },
];

/** `publicCheck` key of a step's reason sentence. `review_required` has no
 * deciding capability (its `codes` are empty): responsibility or the
 * output type decided it, so the sentence names that instead. */
export function reasonKey(reason: StepReason): string {
  switch (reason.mode) {
    case "automatable":
      return "reasonAutomatable";
    case "draft_then_review":
      return "reasonDraftThenReview";
    case "blocked_judgment":
      return "reasonBlockedJudgment";
    case "blocked_physical":
      return "reasonBlockedPhysical";
    case "review_required":
      if (reason.responsibility === "regulatory") return "reasonReviewRegulatory";
      if (reason.responsibility === "formal") return "reasonReviewFormal";
      if (reason.output_type === "external_change") return "reasonReviewExternal";
      return "reasonReviewRequired";
    default:
      return "reasonNoCapability";
  }
}

function useFigures(result: CheckResult) {
  const t = useTranslations("publicCheck");
  const format = useFormatter();
  const hours = (value: number) =>
    format.number(value, { maximumFractionDigits: value < 10 ? 1 : 0 });
  const money = (value: number) =>
    format.number(value, {
      style: "currency",
      currency: result.money?.currency ?? "EUR",
      maximumFractionDigits: 0,
    });
  const percent = (value: number) =>
    format.number(value / 100, { style: "percent", maximumFractionDigits: 0 });
  /** "120 h a year", plus the money when the visitor gave a rate. */
  const yearly = (bucket: keyof CheckResult["hours"] & keyof NonNullable<CheckResult["money"]>) =>
    result.money
      ? t("yearlyHoursMoney", {
          hours: hours(result.hours[bucket]),
          money: money(result.money[bucket]),
        })
      : t("yearlyHours", { hours: hours(result.hours[bucket]) });
  return { hours, money, percent, yearly };
}

/**
 * The breakdown itself, from the result alone - the result page and the
 * gallery (HRP-930) show it the same way. A result without any hour
 * estimate (the gallery's never has one) shows no hours at all, rather
 * than "no estimate" on every step. `lead` stands in for the note on why
 * there are no percentages.
 */
export function ResultBody({ result, lead }: { result: CheckResult; lead?: ReactNode }) {
  const t = useTranslations("publicCheck");
  const { hours, money, percent } = useFigures(result);
  const { shares } = result;
  const timed = result.hours.total > 0;

  const figures =
    timed ? (
      <section className="grid gap-3 sm:grid-cols-2" data-testid="check-result-figures">
        <Figure
          testId="check-figure-total"
          label={t("figureTotal")}
          value={t("hoursShort", { hours: hours(result.hours.total) })}
          sub={result.money ? money(result.money.total) : null}
        />
        <Figure
          testId="check-figure-freed"
          label={t("figureFreed")}
          value={t("hoursShort", { hours: hours(result.hours.freed) })}
          sub={result.money ? money(result.money.freed) : null}
          hint={t("figureFreedHint")}
        />
      </section>
    ) : null;

  const lists = (
    <div className="space-y-8">
      {BUCKET_KEYS.map((bucket) => (
        <BucketList key={bucket.key} bucket={bucket} result={result} timed={timed} />
      ))}
      {result.out_of_scope.length > 0 ? (
        <details className="rounded-lg border p-4" data-testid="check-out-of-scope">
          <summary className="cursor-pointer font-medium">
            {t("outOfScopeTitle", { count: result.out_of_scope.length })}
          </summary>
          <p className="mt-2 text-sm text-muted-foreground">{t("outOfScopeHint")}</p>
          <ol className="mt-3 space-y-3">
            {result.out_of_scope.map((step) => (
              <StepItem key={step.position} step={step} timed={timed} />
            ))}
          </ol>
        </details>
      ) : null}
    </div>
  );

  return (
    <>
      {shares ? (
        <>
          <section className="space-y-4" data-testid="check-result-headline" data-share={shares.moves}>
            <div>
              <p className="text-5xl font-semibold tabular-nums tracking-tight sm:text-6xl">
                {percent(shares.moves)}
              </p>
              <p className="mt-1 text-lg">{t("headlineText")}</p>
            </div>
            <div className="flex h-3 overflow-hidden rounded-full bg-muted" aria-hidden="true">
              {BUCKET_KEYS.map((bucket) => (
                <div
                  key={bucket.key}
                  className={bucket.bar}
                  style={{ width: `${shares[bucket.key]}%` }}
                />
              ))}
            </div>
            <ul className="flex flex-col gap-1 text-sm sm:flex-row sm:flex-wrap sm:gap-x-5">
              {BUCKET_KEYS.map((bucket) => (
                <li
                  key={bucket.key}
                  className="flex items-center gap-2"
                  data-testid={bucket.shareTestId}
                  data-share={shares[bucket.key]}
                >
                  <span className={cn("size-2.5 rounded-full", bucket.bar)} />
                  {t("shareLegend", { label: t(bucket.title), share: percent(shares[bucket.key]) })}
                </li>
              ))}
            </ul>
          </section>
          {figures}
          {lists}
        </>
      ) : (
        <>
          {lead ?? (
            <p className="text-muted-foreground" data-testid="check-result-no-shares">
              {t("noShares")}
            </p>
          )}
          {lists}
          {figures}
        </>
      )}

      {timed && result.hours.unestimated > 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="check-result-unestimated">
          {t("unestimated", { count: result.hours.unestimated })}
        </p>
      ) : null}
    </>
  );
}

interface ResultViewProps {
  check: CheckRead;
  result: CheckResult;
  inputHref: string;
  registerHref: string;
  /** The canonical address to share (HRP-928). None on "my checks": a saved
   * check is read there by its id, its link token is not stored. */
  shareUrl?: string;
  /** "Keep this result" by email (HRP-926); shown while the check has a term. */
  save?: { token: string };
}

export function ResultView({
  check,
  result,
  inputHref,
  registerHref,
  shareUrl,
  save,
}: ResultViewProps) {
  const t = useTranslations("publicCheck");
  return (
    <article className="space-y-8" data-testid="check-result">
      <header className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          {t("resultTitle")}
        </h1>
        {result.preliminary ? (
          <p
            className="inline-block rounded-md bg-amber-500/10 px-2.5 py-1 text-sm text-amber-800 dark:text-amber-300"
            data-testid="check-result-preliminary"
          >
            {t("preliminary")}
          </p>
        ) : null}
        <p className="line-clamp-3 whitespace-pre-line text-sm text-muted-foreground">
          {check.description}
        </p>
      </header>

      <ResultBody result={result} />

      {shareUrl ? (
        <ShareButtons url={shareUrl} result={result} title={check.title} utm={check.utm} />
      ) : null}

      {save ? <SaveResults {...save} expiresAt={check.expires_at} /> : null}

      <section className="space-y-3 rounded-xl border bg-muted/40 p-5 sm:p-6" data-testid="check-bridge">
        <h2 className="text-xl font-semibold tracking-tight">{t("bridgeTitle")}</h2>
        <p>{t("bridgeText")}</p>
        <a
          href={registerHref}
          className={buttonVariants({ size: "lg", className: "h-11 px-6 text-base" })}
          data-testid="check-cta-register"
        >
          {t("bridgeCta")}
        </a>
      </section>

      <footer className="flex flex-col gap-2 border-t pt-4 sm:flex-row sm:items-center sm:justify-between">
        <ExpiresNote expiresAt={check.expires_at} />
        <Link href={inputHref} className="text-sm text-primary hover:underline" data-testid="check-link-new">
          {t("checkAnother")}
        </Link>
      </footer>
    </article>
  );
}

/** "The result is kept until <date>" - nothing for a check without a term. */
export function ExpiresNote({ expiresAt }: { expiresAt: string | null }) {
  const t = useTranslations("publicCheck");
  const format = useFormatter();
  if (!expiresAt) return null;
  return (
    <p className="text-sm text-muted-foreground" data-testid="check-result-expires">
      {t("expiresAt", { date: format.dateTime(new Date(expiresAt), { dateStyle: "long" }) })}
    </p>
  );
}

function Figure({
  testId,
  label,
  value,
  sub,
  hint,
}: {
  testId: string;
  label: string;
  value: string;
  sub: string | null;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border p-4" data-testid={testId}>
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {sub ? <p className="text-sm tabular-nums">{sub}</p> : null}
      {hint ? <p className="mt-2 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function BucketList({
  bucket,
  result,
  timed,
}: {
  bucket: (typeof BUCKET_KEYS)[number];
  result: CheckResult;
  timed: boolean;
}) {
  const t = useTranslations("publicCheck");
  const { hours, yearly } = useFigures(result);
  const steps = result.buckets[bucket.key];
  const headingId = `${bucket.testId}-title`;
  return (
    <section className="space-y-3" data-testid={bucket.testId} aria-labelledby={headingId}>
      <div className="space-y-1">
        <h2 id={headingId} className="text-lg font-semibold">
          {t("bucketHeading", { title: t(bucket.title), count: steps.length })}
        </h2>
        <p className="text-sm text-muted-foreground">{t(bucket.hint)}</p>
        {steps.length > 0 && timed ? (
          <p className="text-sm tabular-nums">{yearly(bucket.key)}</p>
        ) : null}
        {bucket.key === "to_review" && result.hours.to_review_after > 0 ? (
          <p className="text-xs text-muted-foreground">
            {t("toReviewAfter", { hours: hours(result.hours.to_review_after) })}
          </p>
        ) : null}
      </div>
      {steps.length > 0 ? (
        <ol className="space-y-3">
          {steps.map((step) => (
            <StepItem key={step.position} step={step} timed={timed} />
          ))}
        </ol>
      ) : (
        <p className="text-sm text-muted-foreground">{t("bucketEmpty")}</p>
      )}
    </section>
  );
}

function StepItem({ step, timed }: { step: ResultStep; timed: boolean }) {
  const t = useTranslations("publicCheck");
  const tRef = useTranslations("reference");
  const format = useFormatter();
  const capability = (code: string) => {
    const key = `primitive.${code.toLowerCase()}.label`;
    return tRef.has(key) ? tRef(key) : code;
  };
  return (
    <li className="rounded-lg border p-3 sm:p-4" data-testid={`check-step-${step.position}`}>
      <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <h3 className="font-medium">{step.title}</h3>
        {timed ? (
          <span className="shrink-0 text-sm tabular-nums text-muted-foreground">
            {step.hours_per_year != null
              ? t("yearlyHours", {
                  hours: format.number(step.hours_per_year, {
                    maximumFractionDigits: step.hours_per_year < 10 ? 1 : 0,
                  }),
                })
              : t("stepNoEstimate")}
          </span>
        ) : null}
      </div>
      {step.description ? (
        <p className="mt-1 text-sm text-muted-foreground">{step.description}</p>
      ) : null}
      <div className="mt-2 space-y-1.5 text-sm" data-testid={`check-step-${step.position}-reason`}>
        <p>{t(reasonKey(step.reason))}</p>
        {step.reason.codes.length > 0 ? (
          <ul className="flex flex-wrap gap-1.5">
            {step.reason.codes.map((code) => (
              <li key={code} className="rounded-md bg-muted px-2 py-0.5 text-xs">
                {capability(code)}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </li>
  );
}
