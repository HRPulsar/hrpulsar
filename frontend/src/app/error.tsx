"use client";

import { useEffect } from "react";
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
  }, [error]);

  return (
    <div className="min-h-screen bg-background py-20">
      <ServerErrorScreen onRetry={reset} />
    </div>
  );
}
