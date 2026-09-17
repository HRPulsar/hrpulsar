/* eslint-disable react/jsx-no-literals -- intentionally English: the root
   error boundary renders outside NextIntlClientProvider, t() is unavailable */
"use client";

import { useEffect } from "react";
import * as Sentry from "@sentry/nextjs";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[app/global-error.tsx]", error);
    // M31: root boundary — nothing else reports this one.
    Sentry.captureException(error);
  }, [error]);

  return (
    <html lang="en">
      <body>
        <div
          style={{
            minHeight: "100vh",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: "system-ui, sans-serif",
            padding: "2rem",
            textAlign: "center",
          }}
        >
          <div>
            <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>
              Something went wrong
            </h1>
            <p style={{ marginTop: "0.5rem", color: "#666" }}>
              A server error occurred.
            </p>
            <button
              type="button"
              onClick={reset}
              style={{
                marginTop: "1rem",
                padding: "0.5rem 1rem",
                border: "1px solid #ccc",
                borderRadius: "0.375rem",
                background: "transparent",
                cursor: "pointer",
              }}
            >
              Try again
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
