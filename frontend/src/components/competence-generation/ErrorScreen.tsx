"use client";

import { AlertCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";

/** HRP-476: error_code → key pair in the `competences` i18n namespace. The
 *  map owns the code → key relation only; the wording lives in the catalog. */
const MESSAGE_KEYS: Record<string, { titleKey: string; bodyKey: string }> = {
  parse_error: {
    titleKey: "genErrorParseTitle",
    bodyKey: "genErrorParseBody",
  },
  service_error: {
    titleKey: "genErrorServiceTitle",
    bodyKey: "genErrorServiceBody",
  },
  insufficient_data: {
    titleKey: "genErrorInsufficientDataTitle",
    bodyKey: "genErrorInsufficientDataBody",
  },
  overload: {
    titleKey: "genErrorOverloadTitle",
    bodyKey: "genErrorOverloadBody",
  },
  output_truncated: {
    titleKey: "genErrorTruncatedTitle",
    bodyKey: "genErrorTruncatedBody",
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
  const t = useTranslations("competences");
  const tc = useTranslations("common");
  const keys = errorCode ? MESSAGE_KEYS[errorCode] : undefined;
  const m = keys
    ? { title: t(keys.titleKey), body: t(keys.bodyKey) }
    : {
        title: t("genErrorFallbackTitle"),
        body: errorMessage || t("genErrorFallbackBody"),
      };
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
          {retrying ? t("genRetrying") : tc("tryAgain")}
        </Button>
      )}
    </div>
  );
}
