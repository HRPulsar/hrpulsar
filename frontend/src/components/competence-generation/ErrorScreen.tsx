"use client";

import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

const MESSAGES: Record<string, { title: string; body: string }> = {
  parse_error: {
    title: "AI returned an invalid response",
    body: "The model couldn't format the result correctly. Try again — this is usually a transient issue.",
  },
  service_error: {
    title: "AI service error",
    body: "The AI service is temporarily unavailable or returned an error. Retry the request or try again later.",
  },
  insufficient_data: {
    title: "Not enough input data",
    body: "Generation needs at least one specialization, active skill levels, and a populated company description.",
  },
  overload: {
    title: "AI service overloaded",
    body: "Too many concurrent requests. Wait a minute and try again.",
  },
  output_truncated: {
    title: "Result too large for one run",
    body: "The generated tree hit the model's output limit. Narrow the scope — generate one group at a time, or reduce the number of specializations.",
  },
};

export interface ErrorScreenProps {
  errorCode: string | null;
  errorMessage: string | null;
  onRetry?: () => void;
  retrying?: boolean;
}

export function ErrorScreen({
  errorCode,
  errorMessage,
  onRetry,
  retrying = false,
}: ErrorScreenProps) {
  const fallback = {
    title: "Generation failed",
    body: errorMessage || "Something went wrong. Please try again later.",
  };
  const m = (errorCode && MESSAGES[errorCode]) || fallback;
  // Retrying a truncated generation re-runs the same over-budget request;
  // the remedy is a narrower scope, so the retry button is hidden.
  const retryable = errorCode !== "output_truncated";
  return (
    <div
      data-testid="compgen-error-screen"
      className="flex flex-col items-center justify-center gap-4 rounded-md border border-destructive/30 bg-destructive/5 p-6 text-center"
    >
      <AlertCircle className="h-10 w-10 text-destructive" />
      <div className="space-y-1">
        <p className="text-base font-medium text-foreground">{m.title}</p>
        <p className="text-sm text-muted-foreground">{m.body}</p>
      </div>
      {onRetry && retryable && (
        <Button
          data-testid="compgen-error-btn-retry"
          onClick={onRetry}
          disabled={retrying}
        >
          {retrying ? "Retrying…" : "Try again"}
        </Button>
      )}
    </div>
  );
}
