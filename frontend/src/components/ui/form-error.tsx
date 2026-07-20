"use client";

import { useEffect, useRef } from "react";

/**
 * In-modal error display for backend mutation failures (HRP-399).
 * Banner replaces the old toast-only handling; FieldError renders under
 * the offending input. Both render nothing without a message. The banner
 * scrolls itself into view — long scrollable dialogs (position edit) would
 * otherwise mount it above the fold where the user never sees it.
 */

export function FormErrorBanner({
  message,
  testId,
}: {
  message: string | null;
  testId: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (message) {
      ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [message]);

  if (!message) return null;
  return (
    <div
      ref={ref}
      role="alert"
      data-testid={testId}
      className="whitespace-pre-wrap break-words rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive"
    >
      {message}
    </div>
  );
}

export function FieldError({
  message,
  testId,
}: {
  message?: string;
  testId: string;
}) {
  if (!message) return null;
  return (
    <p data-testid={testId} className="text-sm text-destructive">
      {message}
    </p>
  );
}
