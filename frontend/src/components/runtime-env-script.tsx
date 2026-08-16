/**
 * Runtime env injection for client components.
 *
 * Background: ``NEXT_PUBLIC_*`` are inlined into the client bundle at
 * ``npm run build`` time. On a CI-built + GHCR-pulled production image
 * that bundle is frozen — any env change on the prod host can't reach
 * client-side code.
 *
 * Workaround: this server component runs on every SSR pass, reads
 * ``process.env`` from the running Node container (which DOES see the
 * single ``/opt/hrpulsar/.env`` file via docker compose ``env_file:``),
 * and writes the values onto ``window.__ENV__`` before any client
 * component hydrates. Client code reads from ``window.__ENV__`` first
 * with a ``process.env`` fallback for static contexts.
 *
 * Important: the layout that hosts this component would otherwise be
 * statically prerendered in CI (when ``process.env.NEXT_PUBLIC_*`` is
 * empty), and that prerendered HTML would be served forever — runtime
 * env would never be re-read. Calling ``headers()`` opts the request
 * into dynamic rendering so every SSR pass re-evaluates this
 * component against the live container env.
 *
 * Add new public vars to ``PUBLIC_ENV_KEYS`` below. Keep the list
 * narrow — anything dropped here ends up in the rendered HTML.
 */

import { headers } from "next/headers";

const PUBLIC_ENV_KEYS = [
  "NEXT_PUBLIC_TURNSTILE_SITE_KEY",
  // App domain for the cross-domain demo handoff. The CI-built frontend
  // image freezes NEXT_PUBLIC_* at build time, but SaaS supplies this as
  // a runtime env var (deploy/docker-compose.saas.yml), so client code
  // (lib/demo.ts) must read it from window.__ENV__ rather than the empty
  // build-time inline. Without it the handoff branch never fires and the
  // demo lands on /login.
  "NEXT_PUBLIC_APP_DOMAIN",
  // White-label branding (HRP-393, HRP-463) — read by lib/brand.ts.
  "NEXT_PUBLIC_BRAND_NAME",
  "NEXT_PUBLIC_LOGO_URL",
  "NEXT_PUBLIC_LOGO_DARK_URL",
  "NEXT_PUBLIC_BRAND_ACCENT_COLOR",
  "NEXT_PUBLIC_FAVICON_URL",
  // Interface locales (i18n F0, HRP-474) — read by lib/locale.ts.
  "NEXT_PUBLIC_AVAILABLE_LOCALES",
  "NEXT_PUBLIC_DEFAULT_LOCALE",
  "NEXT_PUBLIC_SIDEBAR_LOGO_HEIGHT",
  "NEXT_PUBLIC_BRAND_THEME",
  "NEXT_PUBLIC_BRAND_AUTH_BG_COLOR",
  "NEXT_PUBLIC_BRAND_AUTH_BG_URL",
  // Delay before the demo feedback popup appears, in ms (HRP-587) —
  // read by components/dashboard/demo-feedback-popup.tsx.
  "NEXT_PUBLIC_DEMO_FEEDBACK_DELAY_MS",
  // Per-site billing currency/locale (HRP-451) — read by lib/currency.ts.
  "NEXT_PUBLIC_BILLING_CURRENCY",
  "NEXT_PUBLIC_BILLING_LOCALE",
] as const;

type PublicEnvKey = (typeof PUBLIC_ENV_KEYS)[number];

declare global {
  interface Window {
    __ENV__?: Partial<Record<PublicEnvKey, string>>;
  }
}

export async function RuntimeEnvScript() {
  // Reading headers also flips the host route into dynamic rendering.
  // The nonce comes from the proxy's CSP on hardened routes
  // (/public/assessments/*) — without it this inline script would be
  // blocked there; elsewhere the header is absent and nonce is omitted.
  const hdrs = await headers();
  const nonce = hdrs.get("x-nonce") ?? undefined;

  const env: Partial<Record<PublicEnvKey, string>> = {};
  for (const key of PUBLIC_ENV_KEYS) {
    const value = process.env[key];
    if (value) env[key] = value;
  }
  // Serialize for safe embedding in an inline <script>: escape `<`/`>`/`&`
  // so no payload can close the element or open a comment, and the line/para
  // separators U+2028/U+2029 which are valid in JSON but break a JS string
  // literal (a real inline-script XSS/breakage vector JSON.stringify misses).
  const json = JSON.stringify(env)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
  return (
    <script
      nonce={nonce}
      dangerouslySetInnerHTML={{ __html: `window.__ENV__=${json};` }}
    />
  );
}
