/**
 * Browser Sentry bootstrap (M31).
 *
 * Replaces `sentry.client.config.ts`: under Turbopack (the default builder
 * in Next 16) the SDK does not inject that file, so the browser SDK was
 * never initialised in production. `instrumentation-client.ts` is loaded by
 * Next itself, before the app bundle hydrates.
 *
 * DSN and environment are read from `window.__ENV__` first (written by
 * <RuntimeEnvScript/>, a synchronous inline script in <head>, so it is set
 * before this module runs) and fall back to the build-time inline. That way
 * a CI-built image can be pointed at a Sentry project through the host
 * `.env` instead of being rebuilt.
 */
import * as Sentry from "@sentry/nextjs";

function runtimeEnv(key: "NEXT_PUBLIC_SENTRY_DSN" | "NEXT_PUBLIC_SENTRY_ENVIRONMENT") {
  return (typeof window !== "undefined" ? window.__ENV__?.[key] : undefined) || undefined;
}

const SENTRY_DSN = runtimeEnv("NEXT_PUBLIC_SENTRY_DSN") || process.env.NEXT_PUBLIC_SENTRY_DSN;

if (SENTRY_DSN) {
  Sentry.init({
    dsn: SENTRY_DSN,
    environment:
      runtimeEnv("NEXT_PUBLIC_SENTRY_ENVIRONMENT") ||
      process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ||
      "development",
    // Ties an event to the shipped version. NEXT_PUBLIC_APP_VERSION is set
    // from the APP_VERSION build-arg in next.config.ts.
    release: `hrpulsar@${process.env.NEXT_PUBLIC_APP_VERSION || "dev"}`,
    tracesSampleRate: 0.1,
    // Disable integrations that may trigger browser permission prompts
    integrations: (defaults) =>
      defaults.filter(
        (i) =>
          i.name !== "BrowserProfiling" &&
          i.name !== "Spotlight",
      ),

    beforeSend(event) {
      // Strip PII from user context
      if (event.user) {
        delete event.user.email;
        delete event.user.username;
        delete event.user.ip_address;
      }
      // Strip PII from request body
      const data = event.request?.data;
      if (data && typeof data === "object") {
        const piiKeys = [
          "email",
          "first_name",
          "last_name",
          "phone",
          "password",
        ];
        for (const key of piiKeys) {
          if (key in data) {
            (data as Record<string, unknown>)[key] = "[Filtered]";
          }
        }
      }
      return event;
    },
  });
}

// Navigation spans for the App Router.
export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
