/**
 * Per-site billing currency/locale (HRP-451), mirroring lib/brand.ts.
 *
 * The authoritative money data (pack prices, currency, requisites) comes
 * from GET /billing/profile; these env-backed getters exist for contexts
 * that need to format money before/without that request. Fleet sites set:
 *
 *   NEXT_PUBLIC_BILLING_CURRENCY — ISO 4217 code (default USD)
 *   NEXT_PUBLIC_BILLING_LOCALE   — BCP 47 locale for Intl (default en-US)
 */

const DEFAULT_CURRENCY = "USD";
const DEFAULT_LOCALE = "en-US";

type CurrencyEnvKey = "NEXT_PUBLIC_BILLING_CURRENCY" | "NEXT_PUBLIC_BILLING_LOCALE";

/** Build-time inlined values; static member access per key is required
 * for the bundler to substitute them. */
function buildTimeEnv(key: CurrencyEnvKey): string | undefined {
  switch (key) {
    case "NEXT_PUBLIC_BILLING_CURRENCY":
      return process.env.NEXT_PUBLIC_BILLING_CURRENCY;
    case "NEXT_PUBLIC_BILLING_LOCALE":
      return process.env.NEXT_PUBLIC_BILLING_LOCALE;
  }
}

function readEnv(key: CurrencyEnvKey): string | undefined {
  if (typeof window === "undefined") {
    // Server: dynamic read on purpose — see runtime-env-script.tsx.
    return process.env[key] || undefined;
  }
  return window.__ENV__?.[key] || buildTimeEnv(key) || undefined;
}

/** ISO 4217 is exactly three letters. */
const CURRENCY_CODE = /^[A-Za-z]{3}$/;

/**
 * Normalize an env-provided currency code, mirroring the backend rule in
 * `app/core/currency.py`: three letters uppercased, anything else falls
 * back to USD. Without this a typo like "EURO" reached the API (422 on
 * save, since the column is String(3)) and Intl.NumberFormat, which
 * throws on an invalid code.
 */
function normalizeCurrency(raw: string | undefined): string {
  const value = (raw ?? "").trim();
  return CURRENCY_CODE.test(value) ? value.toUpperCase() : DEFAULT_CURRENCY;
}

export function getBillingCurrency(): string {
  return normalizeCurrency(readEnv("NEXT_PUBLIC_BILLING_CURRENCY"));
}

export function getBillingLocale(): string {
  return readEnv("NEXT_PUBLIC_BILLING_LOCALE") || DEFAULT_LOCALE;
}

/**
 * HRP-439: default currency for HR money fields (grade salary ranges,
 * employee compensations).
 *
 * Those defaults used to be literals — "RUB" on the grade chain, "USD" on
 * compensations — so at least one of them was wrong on every site. The HR
 * domain reuses the per-installation billing currency rather than adding
 * a second knob; the backend mirrors this with `app/core/currency.py`.
 * Kept as its own named export so the two can be split later without
 * hunting down call sites.
 */
export function getDefaultSalaryCurrency(): string {
  return getBillingCurrency();
}

/** Currencies commonly picked in HR forms, most relevant first. */
const COMMON_CURRENCIES = ["USD", "EUR", "GBP", "RUB"];

/**
 * Options for a currency picker: the installation's currency first (it is
 * the default and the most likely pick), then the common codes, without
 * duplicates.
 */
export function getCurrencyOptions(): string[] {
  const installation = getDefaultSalaryCurrency();
  return [installation, ...COMMON_CURRENCIES.filter((c) => c !== installation)];
}

/** Price formatter: whole amounts stay whole (₽2 500, $25), fractional
 * ones keep cents. Falls back to a plain "amount CODE" string when Intl
 * rejects the currency code (misconfigured profile must not crash the
 * billing page). */
export function formatMoney(
  amount: number,
  currency: string = getBillingCurrency(),
  locale: string = getBillingLocale(),
): string {
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${amount} ${currency}`;
  }
}
