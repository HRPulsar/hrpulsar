"use client";

// W6 (§5.4): the two plaques above the Coverage buckets - what share of
// this work moves to an agent and how well an agent does it, and what the
// work costs in hours and in the company's own money. The three buckets
// stay below as the breakdown.
//
// The agent's own cost is deliberately absent: the platform hands the
// skill to the client's runner and never sees a token (decision
// 2026-08-06), so "saving minus the cost of AI" would be invented. The
// screen says so rather than leaving the reader to assume.

import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";

import { BADGE_COLOR } from "@/lib/badge-tones";
import type { Coverage, Quality } from "@/lib/api/work";

/** Weakest last: the row reads best → worst, like the spec's traffic light. */
const QUALITIES: Quality[] = ["better_than_human", "strong", "draft", "no"];

const QUALITY_DOT: Record<Quality, string> = {
  better_than_human: "bg-emerald-500",
  strong: "bg-green-500",
  draft: "bg-yellow-500",
  no: "bg-red-500",
};

export const QUALITY_BADGE: Record<Quality, string> = {
  better_than_human: BADGE_COLOR.emerald,
  strong: BADGE_COLOR.green,
  draft: BADGE_COLOR.yellow,
  no: BADGE_COLOR.red,
};

/** Where an admin sets the rate: the tenant settings it lives on. */
const RATE_SETTINGS_HREF = "/company/profile";

export function CoverageSummary({ coverage }: { coverage: Coverage }) {
  const t = useTranslations("coverage");
  const locale = useLocale();
  const { shares, hours, quality, hourly_rate: rate } = coverage;
  const inScope = coverage.steps.filter((s) => s.in_scope).length;

  const round = (value: number) => Math.round(value).toLocaleString(locale);
  // Built here rather than in the JSX: a bare template literal as a child
  // trips react/jsx-no-literals, and the glyph needs no catalog entry.
  const movesPercent = shares === null ? null : `${Math.round(shares.moves)}%`;
  const money = (value: number) =>
    t("roiMoney", {
      amount: round(value * (rate ?? 0)),
      currency: coverage.hourly_rate_currency ?? "",
    });

  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <div className="rounded-lg border p-4" data-testid="coverage-headline">
        {shares === null ? (
          <>
            <p className="text-sm text-muted-foreground">{t("headlineNoSharesTitle")}</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums" data-testid="coverage-headline-share">
              {t("headlineSteps", { count: inScope })}
            </p>
          </>
        ) : (
          <>
            <p className="flex flex-wrap items-baseline gap-2">
              <span
                className="text-4xl font-semibold tabular-nums"
                data-testid="coverage-headline-share"
                data-share={shares.moves}
              >
                {movesPercent}
              </span>
              <span className="text-sm text-muted-foreground">{t("headlineMoves")}</span>
            </p>
            <div
              className="mt-3 flex h-2 overflow-hidden rounded-full bg-muted"
              role="img"
              aria-label={t("headlineBarAria", {
                moves: Math.round(shares.moves),
                toReview: Math.round(shares.to_review),
              })}
            >
              <div className="bg-green-500" style={{ width: `${shares.moves}%` }} />
              <div className="bg-blue-400" style={{ width: `${shares.to_review}%` }} />
            </div>
          </>
        )}

        <p className="mt-4 text-xs text-muted-foreground">{t("qualityTitle")}</p>
        <ul className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
          {QUALITIES.map((q) => (
            <li
              key={q}
              className="flex items-center gap-1.5 text-sm"
              title={t(`quality_${q}`)}
              data-testid={`coverage-quality-${q}`}
              data-count={quality[q]}
            >
              <span className={`size-2.5 shrink-0 rounded-full ${QUALITY_DOT[q]}`} />
              <span className="tabular-nums">{quality[q]}</span>
              <span className="text-muted-foreground">{t(`quality_${q}`)}</span>
            </li>
          ))}
        </ul>
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
                money={rate === null ? null : money(hours.total)}
                t={t}
              />
              <RoiRow
                testId="coverage-roi-moves"
                label={t("roiMoves")}
                hours={hours.moves}
                round={round}
                money={rate === null ? null : money(hours.moves)}
                t={t}
              />
              <RoiRow
                testId="coverage-roi-to-review"
                label={t("roiToReview")}
                hint={t("roiToReviewHint")}
                hours={hours.to_review}
                round={round}
                money={rate === null ? null : money(hours.to_review)}
                t={t}
              />
            </dl>
            {hours.unestimated > 0 && (
              <p className="mt-3 text-xs text-muted-foreground" data-testid="coverage-roi-unestimated">
                {t("roiUnestimated", { count: hours.unestimated })}
              </p>
            )}
            <p className="mt-3 text-xs text-muted-foreground" data-testid="coverage-roi-rate">
              {rate === null ? (
                <Link href={RATE_SETTINGS_HREF} className="text-primary underline-offset-4 hover:underline">
                  {t("roiRateUnset")}
                </Link>
              ) : (
                <>
                  {t("roiRate", {
                    rate: rate.toLocaleString(locale),
                    currency: coverage.hourly_rate_currency ?? "",
                  })}{" "}
                  <Link href={RATE_SETTINGS_HREF} className="text-primary underline-offset-4 hover:underline">
                    {t("roiRateEdit")}
                  </Link>
                </>
              )}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">{t("roiAgentCostNote")}</p>
          </>
        )}
      </div>
    </div>
  );
}

function RoiRow({
  testId,
  label,
  hint,
  hours,
  round,
  money,
  t,
}: {
  testId: string;
  label: string;
  hint?: string;
  hours: number;
  round: (value: number) => string;
  /** Null until the tenant sets an hourly rate: hours only (§5.2). */
  money: string | null;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  return (
    <div
      className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5"
      data-testid={testId}
      data-hours={Math.round(hours)}
    >
      <dt className="order-2 text-sm text-muted-foreground">
        {label}
        {hint && <span className="ml-1 text-xs">{hint}</span>}
      </dt>
      <dd className="order-1 flex items-baseline gap-3 tabular-nums">
        <span className="font-medium">{t("roiHours", { hours: round(hours) })}</span>
        {money && <span className="text-muted-foreground">{money}</span>}
      </dd>
    </div>
  );
}
