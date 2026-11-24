"use client";

// W6 (§5.4): the two plaques above the Coverage buckets - what share of
// this work moves to an agent, and what the work costs in hours and in the
// company's own money. The three buckets stay below as the breakdown.
//
// HRP-860: one scale. The bar and its legend are the same three shares of
// the same estimated hours; the step-count quality row that sat under the
// bar had another denominator and another colour code, and is gone - the
// quality stays on each step's row.
//
// The agent's own cost is deliberately absent: the platform hands the
// skill to the client's runner and never sees a token (decision
// 2026-08-06), so "saving minus the cost of AI" would be invented. The
// screen says so rather than leaving the reader to assume.

import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";

import { BADGE_COLOR } from "@/lib/badge-tones";
import { usePermissions } from "@/hooks/use-permissions";
import type { AutomationMode, Coverage, CoverageStep, Quality } from "@/lib/api/work";
import { wholePercents as largestRemainder } from "@/lib/whole-percents";

/** The bar's segments and the legend's dots, in bar order: one list, so the
 * two cannot drift apart. The labels are the bucket cards' own. The grey is
 * the remainder on purpose, and zinc-500 in both themes: a lighter or a
 * blue-tinted grey is too close to the review blue to tell apart. */
const BUCKETS = [
  { key: "moves", color: "bg-green-500", label: "summaryMoves" },
  { key: "to_review", color: "bg-blue-400", label: "summaryToReview" },
  { key: "stays", color: "bg-zinc-500", label: "summaryStays" },
] as const;

export type BucketKey = (typeof BUCKETS)[number]["key"];
type Shares = NonNullable<Coverage["shares"]>;

/** The backend's `BUCKET_OF_MODE`: which share a step's hours go to. */
const BUCKET_OF_MODE: Record<AutomationMode, BucketKey> = {
  automatable: "moves",
  draft_then_review: "to_review",
  review_required: "to_review",
  blocked_judgment: "stays",
  blocked_physical: "stays",
};

/** The in-scope steps of each bucket, estimated or not. One function for the
 * legend, the bucket cards and who-does-what (HRP-1195, HRP-1200), so their
 * step counts cannot disagree. */
export function bucketsOf(steps: CoverageStep[]): Record<BucketKey, CoverageStep[]> {
  const out: Record<BucketKey, CoverageStep[]> = { moves: [], to_review: [], stays: [] };
  for (const s of steps) if (s.in_scope && s.mode) out[BUCKET_OF_MODE[s.mode]].push(s);
  return out;
}

/** The shares as whole percents that add up to 100 - what the headline, the
 * bar, the legend and the cards under the summary (HRP-1148) all print. A
 * tie goes to the bar's order. */
export function wholePercents(shares: Shares): Record<BucketKey, number> {
  return largestRemainder(
    shares,
    BUCKETS.map((b) => b.key),
  );
}

export const QUALITY_BADGE: Record<Quality, string> = {
  better_than_human: BADGE_COLOR.emerald,
  strong: BADGE_COLOR.green,
  draft: BADGE_COLOR.yellow,
  no: BADGE_COLOR.red,
};

/** Where an admin sets the rate: the tenant settings it lives on. */
export const RATE_SETTINGS_HREF = "/company/profile";

export function CoverageSummary({
  coverage,
  note,
}: {
  coverage: Coverage;
  /** Why the shares are not there yet, when they are not (HRP-1207). */
  note?: string | null;
}) {
  const t = useTranslations("coverage");
  const locale = useLocale();
  // HRP-622: the rate lives on the company profile, which only the admin
  // role edits (and a plain employee cannot even open) - below it the
  // sentence stays, the link to a page that bounces does not.
  const { canAdminister } = usePermissions();
  const { shares, hours, hourly_rate: rate, hourly_rate_currency: currency } = coverage;
  // The currency is the company's (HRP-868), and an amount without one is
  // not money: a step may carry a rate while the company has none, and the
  // card then asks for the company rate instead of printing a bare number.
  const sums = currency === null ? null : coverage.money;
  const inScope = coverage.steps.filter((s) => s.in_scope).length;

  const round = (value: number) => Math.round(value).toLocaleString(locale);
  // HRP-868: the amounts are the backend's - a step may name its own rate,
  // so hours times the company rate is no longer the money. This only formats.
  const money = (amount: number) =>
    t("roiMoney", { amount: round(amount), currency: currency ?? "" });
  // HRP-861: the review bucket reads "before → after".
  const moneyBeforeAfter = (before: number, after: number) =>
    t("roiMoneyBeforeAfter", {
      before: round(before),
      after: round(after),
      currency: currency ?? "",
    });

  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <div className="flex flex-col rounded-lg border p-4" data-testid="coverage-headline">
        {shares === null ? (
          <>
            <p className="text-sm text-muted-foreground">{t("headlineNoSharesTitle")}</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums" data-testid="coverage-headline-share">
              {t("headlineSteps", { count: inScope })}
            </p>
          </>
        ) : (
          <SharesCard
            shares={shares}
            hours={hours}
            buckets={bucketsOf(coverage.steps)}
            inScope={inScope}
            round={round}
            t={t}
          />
        )}
        {/* At the foot of the card, set like the note on the agent's cost. */}
        {note && (
          <p
            className="mt-auto pt-3 text-xs text-muted-foreground"
            data-testid="coverage-summary-weight-note"
          >
            {note}
          </p>
        )}
      </div>

      <div className="rounded-lg border p-4" data-testid="coverage-roi">
        {hours.total === 0 ? (
          <p className="text-sm text-muted-foreground">{t("roiNoHours")}</p>
        ) : (
          <>
            <dl className="space-y-2">
              <RoiRow
                testId="coverage-roi-total"
                label={t("roiTotal")}
                hours={hours.total}
                round={round}
                money={sums === null ? null : money(sums.total)}
                t={t}
              />
              <RoiRow
                testId="coverage-roi-freed"
                label={t("roiMoves")}
                hours={hours.freed}
                round={round}
                money={sums === null ? null : money(sums.freed)}
                t={t}
              />
              <RoiRow
                testId="coverage-roi-to-review"
                label={t("roiToReview")}
                hint={t("roiToReviewHint")}
                hours={hours.to_review}
                after={hours.to_review_after}
                round={round}
                money={
                  sums === null ? null : moneyBeforeAfter(sums.to_review, sums.to_review_after)
                }
                t={t}
              />
            </dl>
            {/* HRP-862: next to the potential above, what is already done. */}
            <p
              className="mt-3 text-sm"
              data-testid="coverage-roi-automated"
              data-hours={Math.round(hours.automated)}
            >
              {t("roiHoursDone", { automated: round(hours.automated), total: round(hours.total) })}
              {/* HRP-1194: how the figure is counted - a second sentence, the
                  way RoiRow's hints are. */}
              <span className="ml-1 text-xs text-muted-foreground" data-testid="coverage-roi-automated-hint">
                · {t("roiHoursDoneHint")}
              </span>
            </p>
            {hours.unestimated > 0 && (
              <p className="mt-3 text-xs text-muted-foreground" data-testid="coverage-roi-unestimated">
                {t("roiUnestimated", { count: hours.unestimated })}
              </p>
            )}
            {sums !== null && sums.unpriced > 0 && (
              <p className="mt-3 text-xs text-muted-foreground" data-testid="coverage-roi-unpriced">
                {t("roiUnpriced", { count: sums.unpriced })}
              </p>
            )}
            {/* HRP-858: "no hourly rate, so no money here" is only true while
              * there is no money on the card. A step can carry its own rate
              * (HRP-868) and the company keeps its currency, so the figures
              * above can be real - the line would be arguing with them. The
              * company rate is still one hint away, in the hours editor. */}
            {(rate !== null || sums === null) && (
              <p className="mt-3 text-xs text-muted-foreground" data-testid="coverage-roi-rate">
                {rate === null ? (
                  <>
                    {t("roiRateMissing")}
                    {canAdminister && (
                      <>
                        {" "}
                        <Link href={RATE_SETTINGS_HREF} className="text-primary underline-offset-4 hover:underline">
                          {t("roiRateSet")}
                        </Link>
                      </>
                    )}
                  </>
                ) : (
                  <>
                    {t("roiRate", {
                      rate: rate.toLocaleString(locale),
                      currency: currency ?? "",
                    })}
                    {canAdminister && (
                      <>
                        {" "}
                        <Link href={RATE_SETTINGS_HREF} className="text-primary underline-offset-4 hover:underline">
                          {t("roiRateEdit")}
                        </Link>
                      </>
                    )}
                  </>
                )}
              </p>
            )}
            <p className="mt-1 text-xs text-muted-foreground">{t("roiAgentCostNote")}</p>
          </>
        )}
      </div>
    </div>
  );
}

/** The headline percentage, the bar and its legend - one set of shares read
 * three times, so they are rounded once, together. The exact percentage
 * stays on each element in `data-share`.
 *
 * HRP-1195: a percent is of yearly hours, so a long step weighs more than a
 * short one. Each legend line says how many steps and how many hours stand
 * behind it, and the caption names the base and the steps left out of it. */
function SharesCard({
  shares,
  hours,
  buckets,
  inScope,
  round,
  t,
}: {
  shares: Shares;
  hours: Coverage["hours"];
  buckets: Record<BucketKey, CoverageStep[]>;
  inScope: number;
  round: (value: number) => string;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  const whole = wholePercents(shares);
  // Built here rather than in the JSX: a bare template literal as a child
  // trips react/jsx-no-literals, and the glyph needs no catalog entry.
  const percent = (key: BucketKey) => `${whole[key]}%`;

  return (
    <>
      <p className="flex flex-wrap items-baseline gap-2">
        <span
          className="text-4xl font-semibold tabular-nums"
          data-testid="coverage-headline-share"
          data-share={shares.moves}
        >
          {percent("moves")}
        </span>
        <span className="text-sm text-muted-foreground">{t("headlineMoves")}</span>
      </p>
      {/* The legend below says the same in words, so the bar itself is
          decoration to a screen reader. A bucket too small to print has no
          segment either - it would only double the gap - but keeps its
          legend entry. */}
      <div className="mt-3 flex h-2 gap-0.5 overflow-hidden rounded-full" aria-hidden="true">
        {BUCKETS.filter((b) => whole[b.key] > 0).map((b) => (
          <div
            key={b.key}
            className={b.color}
            style={{ flexGrow: whole[b.key], flexBasis: 0 }}
            title={`${t(b.label)}: ${percent(b.key)}`}
            data-testid={`coverage-bar-${b.key}`}
          />
        ))}
      </div>
      <ul className="mt-3 space-y-1">
        {BUCKETS.map((b) => (
          <li
            key={b.key}
            className="flex flex-wrap items-center gap-x-1.5 text-sm"
            data-testid={`coverage-share-${b.key}`}
            data-share={shares[b.key]}
            data-steps={buckets[b.key].length}
            data-hours={Math.round(hours[b.key])}
          >
            <span className={`size-2.5 shrink-0 rounded-full ${b.color}`} />
            <span className="tabular-nums">{percent(b.key)}</span>
            <span className="text-muted-foreground">{t(b.label)}</span>
            <span className="text-xs text-muted-foreground tabular-nums" data-testid={`coverage-share-${b.key}-basis`}>
              · {t("sharesBucketSteps", { count: buckets[b.key].length, total: inScope })} ·{" "}
              {t("roiHours", { hours: round(hours[b.key]) })}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted-foreground" data-testid="coverage-shares-base">
        {t("sharesBase", { unestimated: hours.unestimated })}
      </p>
    </>
  );
}

function RoiRow({
  testId,
  label,
  hint,
  hours,
  after,
  round,
  money,
  t,
}: {
  testId: string;
  label: string;
  hint?: string;
  hours: number;
  /** HRP-861: set on the review bucket - what is left of `hours` once an
   * agent drafts the work. The row then reads "before → after". */
  after?: number;
  round: (value: number) => string;
  /** Null while no estimated step has a rate: hours only (§5.2, HRP-868). */
  money: string | null;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  return (
    <div
      className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5"
      data-testid={testId}
      data-hours={Math.round(hours)}
      data-hours-after={after === undefined ? undefined : Math.round(after)}
    >
      <dt className="order-2 text-sm text-muted-foreground">
        {label}
        {/* HRP-859: the hint is a second sentence, not a continuation of the
            label - without the separator the two run into one line. */}
        {hint && <span className="ml-1 text-xs">· {hint}</span>}
      </dt>
      <dd className="order-1 flex items-baseline gap-3 tabular-nums">
        <span className="font-medium">
          {after === undefined
            ? t("roiHours", { hours: round(hours) })
            : t("roiHoursBeforeAfter", { before: round(hours), after: round(after) })}
        </span>
        {money && <span className="text-muted-foreground">{money}</span>}
      </dd>
    </div>
  );
}
