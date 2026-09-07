"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";

// HRP-728: an API failure on a list page must render as an error with a
// retry, not as the empty state ("no records yet") the lists used to fall
// back to. One block for every list; the page supplies its testid prefix.
export function LoadErrorState({
  onRetry,
  retrying = false,
  testIdPrefix,
  // Pages whose ids predate the `<prefix>-load-failed` shape keep them.
  failedTestId = `${testIdPrefix}-load-failed`,
  retryTestId = `${testIdPrefix}-load-retry`,
}: {
  onRetry: () => void;
  retrying?: boolean;
  testIdPrefix: string;
  failedTestId?: string;
  retryTestId?: string;
}) {
  const tc = useTranslations("common");
  return (
    <div
      className="flex flex-col items-center justify-center gap-3 py-12"
      data-testid={failedTestId}
    >
      <p className="text-sm text-muted-foreground">{tc("loadFailed")}</p>
      <Button
        size="sm"
        variant="outline"
        data-testid={retryTestId}
        disabled={retrying}
        onClick={onRetry}
      >
        {tc("tryAgain")}
      </Button>
    </div>
  );
}
