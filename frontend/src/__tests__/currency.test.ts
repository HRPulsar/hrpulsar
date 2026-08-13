// HRP-439: HR money fields default to the installation's currency.
//
// Salary ranges hardcoded "RUB" and compensations hardcoded "USD", so a
// site was wrong about one of them no matter which one it was. Both now
// read NEXT_PUBLIC_BILLING_CURRENCY — the per-installation value that
// already drives the billing surfaces (backend mirror:
// app/core/currency.py).

import { afterEach, describe, expect, it } from "vitest";

import {
  getCurrencyOptions,
  getDefaultSalaryCurrency,
} from "@/lib/currency";

const ENV_KEY = "NEXT_PUBLIC_BILLING_CURRENCY";

afterEach(() => {
  delete process.env[ENV_KEY];
});

describe("getDefaultSalaryCurrency (HRP-439)", () => {
  it("falls back to USD when the installation sets nothing", () => {
    expect(getDefaultSalaryCurrency()).toBe("USD");
  });

  it("follows the configured installation currency", () => {
    process.env[ENV_KEY] = "EUR";
    expect(getDefaultSalaryCurrency()).toBe("EUR");
    process.env[ENV_KEY] = "RUB";
    expect(getDefaultSalaryCurrency()).toBe("RUB");
  });
});

describe("currency code validation (HRP-439 review fix)", () => {
  // The backend drops anything that is not three letters to USD. Without
  // the same rule here a typo reached the API (422 — the column is
  // String(3)) and Intl.NumberFormat, which throws on an invalid code.
  it.each(["EURO", "E", "12", "€€€", "  ", "US1"])(
    "falls back to USD for %j",
    (bad) => {
      process.env[ENV_KEY] = bad;
      expect(getDefaultSalaryCurrency()).toBe("USD");
    },
  );

  it("uppercases and trims a valid code", () => {
    process.env[ENV_KEY] = " eur ";
    expect(getDefaultSalaryCurrency()).toBe("EUR");
  });

  it("never offers an invalid code as an option", () => {
    process.env[ENV_KEY] = "EURO";
    const options = getCurrencyOptions();
    expect(options).not.toContain("EURO");
    expect(options[0]).toBe("USD");
    expect(new Set(options).size).toBe(options.length);
  });
});

describe("getCurrencyOptions (HRP-439)", () => {
  it("leads with the installation currency", () => {
    process.env[ENV_KEY] = "EUR";
    expect(getCurrencyOptions()[0]).toBe("EUR");
  });

  it("never repeats the installation currency", () => {
    process.env[ENV_KEY] = "RUB";
    const options = getCurrencyOptions();
    expect(options.filter((c) => c === "RUB")).toHaveLength(1);
    expect(new Set(options).size).toBe(options.length);
  });

  it("keeps the common codes reachable on an exotic installation", () => {
    process.env[ENV_KEY] = "CHF";
    expect(getCurrencyOptions()).toEqual(["CHF", "USD", "EUR", "GBP", "RUB"]);
  });
});
