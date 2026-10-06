"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FormErrorBanner } from "@/components/ui/form-error";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  ANSWER_MAX,
  DESCRIPTION_MAX,
  DESCRIPTION_MIN,
  FREQUENCIES,
  HOURLY_RATE_MAX,
  TEAM_SIZE_MAX,
  checkLocaleFor,
  createCheck,
  type CheckUtm,
  type Frequency,
  TURNSTILE_ACTIONS,
} from "@/lib/api/public-check";
import { useTurnstileGate } from "@/lib/turnstile";
import { cn } from "@/lib/utils";

import { CaptchaGate } from "./captcha";
import { DictateButton } from "./dictate-button";
import { createErrorKey, invalidField } from "./errors";
import { useTrackOnce } from "./funnel";
import { rememberOwnerKey } from "./owner-key";

/** Ready-made processes, one click fills the field. Short versions of the
 * process library (docs/plans/process-library/en, HRP-929); the texts live
 * in the catalogs so a German visitor gets a German example. */
const EXAMPLE_KEYS = [
  { id: "month-end-close", label: "exampleMonthEndCloseLabel", text: "exampleMonthEndCloseText" },
  { id: "support-ticket", label: "exampleSupportTicketLabel", text: "exampleSupportTicketText" },
  { id: "contract-review", label: "exampleContractReviewLabel", text: "exampleContractReviewText" },
  { id: "onboarding", label: "exampleOnboardingLabel", text: "exampleOnboardingText" },
  { id: "hiring", label: "exampleHiringLabel", text: "exampleHiringText" },
  { id: "goods-receipt", label: "exampleGoodsReceiptLabel", text: "exampleGoodsReceiptText" },
] as const;

const FREQUENCY_KEYS: Record<Frequency, string> = {
  daily: "frequencyDaily",
  weekly: "frequencyWeekly",
  monthly: "frequencyMonthly",
  quarterly: "frequencyQuarterly",
  yearly: "frequencyYearly",
  ad_hoc: "frequencyAdHoc",
};

/** EUR first: the default of the backend (``Answers.currency``). */
const CURRENCIES = ["EUR", "USD", "GBP", "CHF"];

const SELECT_CLASS =
  "h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-base outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive md:text-sm dark:bg-input/30";

interface CheckFormProps {
  /** A result lives at `${resultBase}/<token>` on this host. */
  resultBase: string;
  utm: CheckUtm | null;
}

export function CheckForm({ resultBase, utm }: CheckFormProps) {
  const t = useTranslations("publicCheck");
  const tAuth = useTranslations("auth");
  const format = useFormatter();
  const locale = useLocale();
  const router = useRouter();
  const turnstile = useTurnstileGate(TURNSTILE_ACTIONS.check);

  const [description, setDescription] = useState("");
  const descriptionRef = useRef<HTMLTextAreaElement>(null);
  // The field holds dictated text (HRP-947); an example replaces it.
  const [dictated, setDictated] = useState(false);
  const [industry, setIndustry] = useState("");
  const [teamSize, setTeamSize] = useState("");
  const [frequency, setFrequency] = useState<Frequency | "">("");
  const [hourlyRate, setHourlyRate] = useState("");
  const [currency, setCurrency] = useState(CURRENCIES[0]);
  const [submitting, setSubmitting] = useState(false);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [badField, setBadField] = useState<string | null>(null);

  useTrackOnce("opened", utm);
  // Typed, dictated or an example - any text in the field is a start.
  useTrackOnce("started", utm, description.length > 0);

  const length = description.trim().length;
  const tooShort = length < DESCRIPTION_MIN;
  // Dictation can carry the text past the limit (`maxLength` stops typing,
  // not a value set by code): shown and blocked, never cut.
  const tooLong = length > DESCRIPTION_MAX;
  const invalid = (field: string) => badField === field || undefined;

  /** Dictated text goes after what is typed, never over it; the cursor
   * waits at its end for the visitor's corrections. */
  function appendDictated(text: string) {
    setDescription((current) => (current.trim() ? `${current.trimEnd()}\n${text}` : text));
    setDictated(true);
    setBadField(null);
    requestAnimationFrame(() => {
      const field = descriptionRef.current;
      if (!field) return;
      field.focus();
      field.setSelectionRange(field.value.length, field.value.length);
      field.scrollTop = field.scrollHeight;
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (tooShort || tooLong || submitting || !turnstile.isReady) return;
    setSubmitting(true);
    setErrorKey(null);
    setBadField(null);
    try {
      const created = await createCheck({
        description: description.trim(),
        answers: {
          industry: industry.trim() || null,
          team_size: teamSize ? Number(teamSize) : null,
          frequency: frequency || null,
          hourly_rate: hourlyRate ? Number(hourlyRate) : null,
          currency,
        },
        locale: checkLocaleFor(locale),
        utm,
        ...(turnstile.token ? { turnstile_token: turnstile.token } : {}),
        ...(dictated ? { dictated: true } : {}),
      });
      rememberOwnerKey(created.token, created.owner_key, created.expires_at);
      // The progress lives on the result page, so a reload never loses
      // the check.
      router.push(`${resultBase}/${created.token}`);
    } catch (err) {
      setErrorKey(createErrorKey(err));
      setBadField(invalidField(err));
      // Captcha tokens are single-use.
      turnstile.reset();
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          {t("inputTitle")}
        </h1>
        <p className="text-muted-foreground">{t("inputLead")}</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6" data-testid="check-form">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Label htmlFor="check-description">{t("descriptionLabel")}</Label>
            <DictateButton onText={appendDictated} />
          </div>
          <Textarea
            ref={descriptionRef}
            id="check-description"
            data-testid="check-input-description"
            value={description}
            onChange={(e) => {
              setDescription(e.target.value);
              // The dictated text is gone with an emptied field.
              if (!e.target.value.trim()) setDictated(false);
            }}
            placeholder={t("descriptionPlaceholder")}
            maxLength={DESCRIPTION_MAX}
            aria-invalid={invalid("description") || (tooLong ? true : undefined)}
            aria-describedby="check-description-count"
            className="min-h-40"
          />
          <div className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground">
            <span className={cn(tooLong && "text-destructive")} data-testid="check-description-hint">
              {tooShort
                ? t("descriptionMin", { min: DESCRIPTION_MIN })
                : tooLong
                  ? t("errorDescriptionLength", { min: DESCRIPTION_MIN, max: DESCRIPTION_MAX })
                  : null}
            </span>
            <span
              id="check-description-count"
              data-testid="check-description-count"
              data-over-limit={tooLong || undefined}
              className={cn(tooLong && "font-medium text-destructive")}
            >
              {t("descriptionCount", {
                count: format.number(description.length),
                max: format.number(DESCRIPTION_MAX),
              })}
            </span>
          </div>
        </div>

        <div className="space-y-2">
          <p className="text-sm font-medium">{t("examplesLabel")}</p>
          <div className="flex flex-wrap gap-2">
            {EXAMPLE_KEYS.map((example) => (
              <Button
                key={example.id}
                type="button"
                variant="outline"
                size="sm"
                data-testid={`check-example-${example.id}`}
                onClick={() => {
                  setDescription(t(example.text));
                  setDictated(false);
                  setBadField(null);
                }}
              >
                {t(example.label)}
              </Button>
            ))}
          </div>
        </div>

        <fieldset className="space-y-4 rounded-lg border p-4">
          <legend className="px-1 text-sm font-medium">{t("answersLegend")}</legend>
          <p className="text-sm text-muted-foreground">{t("answersHint")}</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="check-industry">{t("industryLabel")}</Label>
              <Input
                id="check-industry"
                data-testid="check-input-industry"
                value={industry}
                onChange={(e) => setIndustry(e.target.value)}
                placeholder={t("industryPlaceholder")}
                maxLength={ANSWER_MAX}
                aria-invalid={invalid("industry")}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="check-team-size">{t("teamSizeLabel")}</Label>
              <Input
                id="check-team-size"
                data-testid="check-input-team-size"
                type="number"
                inputMode="numeric"
                min={1}
                max={TEAM_SIZE_MAX}
                step={1}
                value={teamSize}
                onChange={(e) => setTeamSize(e.target.value)}
                aria-invalid={invalid("team_size")}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="check-frequency">{t("frequencyLabel")}</Label>
              <select
                id="check-frequency"
                data-testid="check-select-frequency"
                className={SELECT_CLASS}
                value={frequency}
                onChange={(e) => setFrequency(e.target.value as Frequency | "")}
                aria-invalid={invalid("frequency")}
              >
                <option value="">{t("frequencyUnset")}</option>
                {FREQUENCIES.map((value) => (
                  <option key={value} value={value}>
                    {t(FREQUENCY_KEYS[value])}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="check-hourly-rate">{t("hourlyRateLabel")}</Label>
              <div className="flex gap-2">
                <Input
                  id="check-hourly-rate"
                  data-testid="check-input-hourly-rate"
                  type="number"
                  inputMode="decimal"
                  min={0.01}
                  max={HOURLY_RATE_MAX}
                  step={0.01}
                  value={hourlyRate}
                  onChange={(e) => setHourlyRate(e.target.value)}
                  aria-invalid={invalid("hourly_rate")}
                />
                <select
                  aria-label={t("currencyLabel")}
                  data-testid="check-select-currency"
                  className={cn(SELECT_CLASS, "w-24 shrink-0")}
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value)}
                  aria-invalid={invalid("currency")}
                >
                  {CURRENCIES.map((code) => (
                    <option key={code} value={code}>
                      {code}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        </fieldset>

        <CaptchaGate turnstile={turnstile} />
        <FormErrorBanner
          message={errorKey ? t(errorKey, { min: DESCRIPTION_MIN, max: DESCRIPTION_MAX }) : null}
          testId="check-error"
        />

        <div className="space-y-3">
          <Button
            type="submit"
            size="lg"
            className="h-11 w-full px-6 text-base sm:w-auto"
            disabled={tooShort || tooLong || submitting || !turnstile.isReady}
            data-testid="check-btn-submit"
          >
            {submitting ? <Loader2 className="animate-spin" /> : null}
            {!turnstile.isReady && !turnstile.failed ? tAuth("verifying") : t("submit")}
          </Button>
          <p className="text-xs text-muted-foreground">{t("privacyNote")}</p>
        </div>
      </form>
    </div>
  );
}
