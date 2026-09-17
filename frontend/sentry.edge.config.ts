import * as Sentry from "@sentry/nextjs";

const SENTRY_DSN = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (SENTRY_DSN) {
  Sentry.init({
    dsn: SENTRY_DSN,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT || "development",
    // Same release string as the browser SDK (M31) — APP_VERSION is the
    // Docker build-arg, mirrored into NEXT_PUBLIC_APP_VERSION by next.config.ts.
    release: `hrpulsar@${process.env.APP_VERSION || process.env.NEXT_PUBLIC_APP_VERSION || "dev"}`,
    tracesSampleRate: 0.1,
  });
}
