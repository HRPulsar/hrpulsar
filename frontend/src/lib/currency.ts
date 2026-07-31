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

export function getBillingCurrency(): string {
  return readEnv("NEXT_PUBLIC_BILLING_CURRENCY") || DEFAULT_CURRENCY;
}

export function getBillingLocale(): string {
  return readEnv("NEXT_PUBLIC_BILLING_LOCALE") || DEFAULT_LOCALE;
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
