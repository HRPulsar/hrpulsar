import type { APIRequestContext, Page } from "@playwright/test";

import { API_BASE } from "./helpers";

/**
 * Public process check "AI or Human?" (epic HRP-918, e2e HRP-932).
 *
 * Contract of the run (like DEPLOYMENT_MODE, HRP-390): backend, frontend and
 * the Playwright process get the same PUBLIC_CHECK_ENABLED and
 * PUBLIC_CHECK_HOST - an origin with scheme and port, e.g.
 * `http://check.localhost:3100`, so the links of the letters open. Chromium
 * resolves `*.localhost` to loopback by itself. Community CI leaves the
 * service off and every check spec skips. The frontend also needs
 * NEXT_PUBLIC_APP_DOMAIN (the app host of the bridge links and the 307s).
 *
 * CI has no model key and no inbox: the specs start from the E2E-only seeds
 * of the backend (`/api/public-check/_test/*`, 404 outside E2E_MODE) and
 * walk the rest through the real pages and endpoints.
 */
export const PUBLIC_CHECK_E2E = /^(1|true|yes|on)$/i.test(
  (process.env.PUBLIC_CHECK_ENABLED ?? "").trim(),
);

/** Origin of the check host - the backend's rule: https without a scheme. */
export const CHECK_ORIGIN = (() => {
  const raw = (process.env.PUBLIC_CHECK_HOST ?? "").trim().replace(/\/+$/, "");
  return raw.includes("://") ? raw : `https://${raw}`;
})();

/** Origin of the app host of the run (playwright.config.ts baseURL). */
export const APP_ORIGIN = process.env.E2E_BASE_URL ?? "http://localhost:3100";

/** The check host as a Host header: request-level calls (no browser) go to
 * the app origin with it - no DNS for `*.localhost` needed outside Chromium. */
export const CHECK_HOST_HEADER = { "x-forwarded-host": PUBLIC_CHECK_E2E ? new URL(CHECK_ORIGIN).host : "" };

const SEED = `${API_BASE}/public-check/_test`;

/** A description no other test (or run) shares: its first line is the title. */
export function uniqueProcess(name = "Customer request handling"): string {
  const stamp = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
  return `${name} ${stamp}\nWe read the request, draft the reply, file the return and decide on exceptions.`;
}

/** A documentation address (RFC 5737) for one visitor of a test. */
export function uniqueIp(): string {
  const n = () => Math.floor(Math.random() * 250) + 1;
  return `198.51.${n()}.${n()}`;
}

export interface SeededCheck {
  id: string;
  token: string;
  owner_key: string;
  status: string;
}

async function seedPost<T>(
  request: APIRequestContext,
  path: string,
  data: Record<string, unknown>,
  headers?: Record<string, string>,
): Promise<T> {
  const resp = await request.post(`${SEED}/${path}`, { data, headers });
  if (!resp.ok()) {
    throw new Error(`public check seed ${path} failed (${resp.status()}): ${await resp.text()}`);
  }
  return resp.json() as Promise<T>;
}

/**
 * A finished check: the real intake and freeze, a fixed answer of the model
 * - five steps: one to an agent, two drafted for review, one for people,
 * one out of scope; 12 h a year each, so 25 / 50 / 25 %.
 */
export function seedReadyCheck(
  request: APIRequestContext,
  body: {
    description?: string;
    answers?: Record<string, unknown>;
    locale?: "en" | "de";
    utm?: Record<string, string>;
  } = {},
): Promise<SeededCheck> {
  return seedPost(request, "checks", { description: uniqueProcess(), ...body });
}

/** The link a letter to the address would carry now: the confirmation of
 * its newest check still waiting, or "my checks" once the address is
 * confirmed. `kind: "confirm"` asks for the letter of a check saved to an
 * address confirmed before - every save needs its own click. */
export function seedLetterToken(
  request: APIRequestContext,
  email: string,
  kind?: "confirm" | "magic",
): Promise<{ kind: "confirm" | "magic"; token: string }> {
  return seedPost(request, "email-token", kind ? { email, kind } : { email });
}

/** The one-time login of a SaaS signup's approval letter. */
export async function seedMagicLogin(
  request: APIRequestContext,
  email: string,
): Promise<string> {
  return (await seedPost<{ token: string }>(request, "magic-login", { email })).token;
}

/** Spend a visitor's per-IP budget of new checks; the next one is a 429. */
export async function spendIpBudget(request: APIRequestContext, ip: string): Promise<number> {
  const spent = await seedPost<{ hits: number }>(request, "spend-ip-budget", {}, {
    "x-forwarded-for": ip,
  });
  return spent.hits;
}

/** This browser is the one that ran the check: its owner key in storage,
 * as the input page leaves it (`owner-key.ts`). */
export async function actAsOwner(page: Page, check: SeededCheck): Promise<void> {
  await page.addInitScript(
    ([key, value]) => {
      try {
        localStorage.setItem(key, value);
      } catch {
        // A page without storage just has no save block.
      }
    },
    [`public-check:owner:${check.token}`, check.owner_key],
  );
}

/** Every API call of the page comes from `ip`, as Caddy names a visitor. */
export async function browseFrom(page: Page, ip: string): Promise<void> {
  await page.route(`${API_BASE}/**`, (route) =>
    route.continue({
      headers: { ...route.request().headers(), "x-forwarded-for": ip },
    }),
  );
}
