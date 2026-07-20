import * as Sentry from "@sentry/nextjs";

const SENTRY_DSN = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (SENTRY_DSN) {
  Sentry.init({
    dsn: SENTRY_DSN,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT || "development",
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
