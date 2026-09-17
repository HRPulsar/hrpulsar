import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";
import createNextIntlPlugin from "next-intl/plugin";
import * as fs from "fs";
import * as path from "path";

// App version: prefer env var (Docker build arg), fallback to version.py, then "dev"
let APP_VERSION = process.env.APP_VERSION || "dev";
if (APP_VERSION === "dev") {
  try {
    const content = fs.readFileSync(
      path.resolve(process.cwd(), "../version.py"),
      "utf-8",
    );
    const match = content.match(/__version__\s*=\s*"([^"]+)"/);
    if (match) APP_VERSION = match[1];
  } catch {}
}

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_APP_VERSION: APP_VERSION,
  },
  output: "standalone",
  async redirects() {
    return [
      // The recruitment index used to be a server component calling
      // redirect(); rendered under the client-side RequireRole gate it
      // tripped React's dev performance tracking ("negative time stamp").
      // A config redirect never renders anything.
      {
        source: "/recruitment",
        destination: "/recruitment/requisitions",
        permanent: false,
      },
    ];
  },
};

// i18n (F1): next-intl request config — inner wrapper, composed before
// the conditional Sentry one below.
const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");
const intlConfig = withNextIntl(nextConfig);

// Wrap with Sentry when the build can do something useful with it: a
// build-time DSN, or upload credentials (M31 — the DSN now normally reaches
// the browser at runtime via window.__ENV__, so the auth token is what tells
// us this build should ship source maps).
const hasSentry = !!(
  process.env.NEXT_PUBLIC_SENTRY_DSN || process.env.SENTRY_AUTH_TOKEN
);

export default hasSentry
  ? withSentryConfig(intlConfig, {
      // Upload source maps for better stack traces
      sourcemaps: {
        deleteSourcemapsAfterUpload: true,
      },
      // Must match the `release` the SDKs report (sentry.*.config.ts,
      // src/instrumentation-client.ts) or the uploaded maps are never
      // applied to the events.
      release: { name: `hrpulsar@${APP_VERSION}` },
      // Suppress Sentry CLI logs in dev
      silent: true,
    })
  : intlConfig;
