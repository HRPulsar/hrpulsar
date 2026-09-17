/**
 * Server/edge Sentry bootstrap (M31).
 *
 * `sentry.server.config.ts` and `sentry.edge.config.ts` are plain modules —
 * nothing loads them on its own. Next.js only calls `register()` from this
 * file, so without it the server SDK never initialised and every SSR/route
 * error went unreported.
 */
import * as Sentry from "@sentry/nextjs";

export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("../sentry.server.config");
  }
  if (process.env.NEXT_RUNTIME === "edge") {
    await import("../sentry.edge.config");
  }
}

// Reports errors thrown by server components, route handlers and middleware.
export const onRequestError = Sentry.captureRequestError;
