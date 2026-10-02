"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useBillingActionLabel } from "@/lib/billing-labels";
import { formatDateTime, splitDuration } from "@/lib/date-format";
import type { CreditTransactionDetail } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

interface TransactionDetailSheetProps {
  transactionId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// HRP-965: detail behind GET /billing/credits/history/{id} (admin-only —
// the page only mounts this sheet for admins, see R13). A fetch failure
// (403 for a role that slipped through, 404 for a since-purged row) toasts
// and closes the sheet instead of showing a broken panel.
export function TransactionDetailSheet({
  transactionId,
  open,
  onOpenChange,
}: TransactionDetailSheetProps) {
  const t = useTranslations("settings");
  const locale = useLocale();
  const actionLabel = useBillingActionLabel();
  const [loaded, setLoaded] = useState<CreditTransactionDetail | null>(null);
  // Derived, not reset in an effect: while open, a row fetched for another
  // transaction never paints; while closing, the last row stays for the
  // exit animation (the page clears `transactionId` on close).
  const detail = loaded && (!open || loaded.id === transactionId) ? loaded : null;
  const loadFailed = t("billingTxLoadFailed");

  // HRP-965 fix round 1: the page passes a fresh inline arrow for
  // `onOpenChange` on every render. Keeping the latest one in a ref (rather
  // than the fetch effect's deps) means a parent re-render while the sheet
  // is open no longer resets `detail` and re-hits the admin-only endpoint.
  const onOpenChangeRef = useRef(onOpenChange);
  useEffect(() => {
    onOpenChangeRef.current = onOpenChange;
  });

  useEffect(() => {
    if (!open || !transactionId) return;
    let cancelled = false;
    api
      .get<CreditTransactionDetail>(`/billing/credits/history/${transactionId}`)
      .then((res) => {
        if (!cancelled) setLoaded(res);
      })
      .catch(() => {
        if (cancelled) return;
        // Or the closing sheet would paint the last transaction opened.
        setLoaded(null);
        toast.error(loadFailed);
        onOpenChangeRef.current(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, transactionId, loadFailed]);

  const duration = detail?.calls ? splitDuration(detail.calls.total_latency_ms) : null;
  const entityTypeLabel = (type: string) =>
    t.has(`billingEntityType.${type}`) ? t(`billingEntityType.${type}`) : type;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent data-testid="settings-billing-tx-sheet" className="sm:max-w-md">
        {detail === null ? (
          <SheetTitle className="py-12 text-center text-sm font-normal text-muted-foreground">
            {t("billingTxLoading")}
          </SheetTitle>
        ) : (
          <>
            <SheetHeader>
              <SheetTitle>{actionLabel(detail.action)}</SheetTitle>
              <SheetDescription>
                {detail.amount > 0 ? "+" : ""}
                {detail.amount.toLocaleString(locale)} · {formatDateTime(detail.created_at)}
              </SheetDescription>
            </SheetHeader>
            <dl className="mt-6 grid grid-cols-[9rem_1fr] gap-x-4 gap-y-3 text-sm">
              <dt className="text-muted-foreground">{t("billingTxWho")}</dt>
              <dd>{detail.user_name ?? t("billingWhoSystem")}</dd>
              <dt className="text-muted-foreground">{t("billingTxObject")}</dt>
              <dd>
                {detail.entity === null ? (
                  t("billingTxNoObject")
                ) : detail.entity.path ? (
                  <>
                    {detail.entity.title && (
                      <>
                        {entityTypeLabel(detail.entity.type)} ·{" "}
                      </>
                    )}
                    <Link
                      href={detail.entity.path}
                      className="text-primary underline"
                      data-testid="settings-billing-tx-object-link"
                    >
                      {detail.entity.title ?? entityTypeLabel(detail.entity.type)}
                    </Link>
                  </>
                ) : (
                  entityTypeLabel(detail.entity.type)
                )}
              </dd>
              {detail.calls && duration && (
                <div className="contents" data-testid="settings-billing-tx-calls">
                  <dt className="text-muted-foreground">{t("billingTxModel")}</dt>
                  <dd>{detail.calls.models.join(", ")}</dd>
                  <dt className="text-muted-foreground">{t("billingTxDuration")}</dt>
                  <dd>
                    {duration.minutes > 0
                      ? t("billingTxDurationMinSec", duration)
                      : t("billingTxDurationSec", duration)}
                  </dd>
                  <dt className="text-muted-foreground">{t("billingTxCalls")}</dt>
                  <dd>{detail.calls.count}</dd>
                </div>
              )}
            </dl>
            <SheetFooter className="mt-8">
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                {t("billingTxClose")}
              </Button>
            </SheetFooter>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
