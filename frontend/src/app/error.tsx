"use client";

import { useEffect } from "react";
import * as Sentry from "@sentry/nextjs";
import { ServerErrorScreen } from "@/components/system-screens";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[app/error.tsx]", error);
    // M31: the boundary is the last stop for a render error — without this
    // it never reaches Sentry.
    Sentry.captureException(error);
  }, [error]);

  return (
    <div className="min-h-screen bg-background py-20">
      <ServerErrorScreen onRetry={reset} />
    </div>
  );
}
