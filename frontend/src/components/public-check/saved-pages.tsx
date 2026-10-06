"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { FormErrorBanner } from "@/components/ui/form-error";
import { ApiError } from "@/lib/api";
import {
  confirmEmail,
  deleteSaved,
  getSaved,
  listSaved,
  unsubscribe,
  type CheckRead,
  type CheckStatus,
  type SavedChecks,
} from "@/lib/api/public-check";

import { runErrorKey } from "./errors";
import { ResultView } from "./result-view";
import { LinkRequestForm } from "./save-results";

/** Pages of saving by email (HRP-926), reached from the letters' links. */

function isLinkInvalid(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

function Title({ children }: { children: React.ReactNode }) {
  return <h1 className="text-2xl font-semibold tracking-tight">{children}</h1>;
}

/** A letter's link that no longer works: say so, offer a fresh one. */
function LinkInvalid() {
  const t = useTranslations("publicCheck");
  return (
    <section className="space-y-4" data-testid="check-link-invalid">
      <Title>{t("linkInvalidTitle")}</Title>
      <p className="text-muted-foreground">{t("linkInvalidText")}</p>
      <LinkRequestForm />
    </section>
  );
}

/** One button that POSTs a letter's token. A button, not a POST on load:
 * mail scanners open links, and must neither confirm nor unsubscribe. */
function useTokenAction(action: () => Promise<unknown>) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "invalid" | "failed">("idle");
  async function run() {
    setState("busy");
    try {
      await action();
      setState("done");
    } catch (err) {
      setState(isLinkInvalid(err) ? "invalid" : "failed");
    }
  }
  return { state, run };
}

export function ConfirmEmailPage({ token, myHref }: { token: string; myHref: string }) {
  const t = useTranslations("publicCheck");
  const { state, run } = useTokenAction(() => confirmEmail(token));
  if (state === "invalid") return <LinkInvalid />;
  if (state === "done") {
    return (
      <section className="space-y-4" data-testid="check-confirm-done">
        <Title>{t("confirmDoneTitle")}</Title>
        <p className="text-muted-foreground">{t("confirmDoneText")}</p>
        <Link href={myHref} className={buttonVariants({ size: "lg" })} data-testid="check-confirm-my-link">
          {t("confirmDoneLink")}
        </Link>
      </section>
    );
  }
  return (
    <section className="space-y-4" data-testid="check-confirm">
      <Title>{t("confirmTitle")}</Title>
      <p className="text-muted-foreground">{t("confirmLead")}</p>
      <FormErrorBanner message={state === "failed" ? t("errorGeneric") : null} testId="check-confirm-error" />
      <Button size="lg" onClick={run} disabled={state === "busy"} data-testid="check-confirm-btn">
        {state === "busy" ? <Loader2 className="animate-spin" /> : null}
        {t("confirmSubmit")}
      </Button>
    </section>
  );
}

export function UnsubscribePage({ token }: { token: string }) {
  const t = useTranslations("publicCheck");
  const { state, run } = useTokenAction(() => unsubscribe(token));
  if (state === "invalid") {
    return (
      <section className="space-y-4" data-testid="check-link-invalid">
        <Title>{t("linkInvalidTitle")}</Title>
        <p className="text-muted-foreground">{t("unsubscribeInvalidText")}</p>
      </section>
    );
  }
  return (
    <section className="space-y-4" data-testid="check-unsubscribe">
      <Title>{t("unsubscribeTitle")}</Title>
      {state === "done" ? (
        <p role="status" data-testid="check-unsubscribe-done">
          {t("unsubscribeDone")}
        </p>
      ) : (
        <>
          <p className="text-muted-foreground">{t("unsubscribeLead")}</p>
          <FormErrorBanner message={state === "failed" ? t("errorGeneric") : null} testId="check-unsubscribe-error" />
          <Button size="lg" onClick={run} disabled={state === "busy"} data-testid="check-unsubscribe-btn">
            {state === "busy" ? <Loader2 className="animate-spin" /> : null}
            {t("unsubscribeSubmit")}
          </Button>
        </>
      )}
    </section>
  );
}

/** "My checks" without a link: ask for one. */
export function MyChecksRequestPage() {
  const t = useTranslations("publicCheck");
  return (
    <section className="space-y-4" data-testid="check-my-request">
      <Title>{t("myRequestTitle")}</Title>
      <p className="text-muted-foreground">{t("myRequestLead")}</p>
      <LinkRequestForm />
    </section>
  );
}

const STATUS_KEYS: Record<CheckStatus, string> = {
  pending: "statusPending",
  running: "statusRunning",
  ready: "statusReady",
  error: "statusError",
};

function Loading() {
  const t = useTranslations("publicCheck");
  return (
    <div role="status" aria-busy="true" className="flex justify-center py-16" data-testid="check-loading">
      <Loader2 className="size-6 animate-spin text-muted-foreground" aria-hidden="true" />
      <span className="sr-only">{t("loadingLabel")}</span>
    </div>
  );
}

/** Why a load by a "my checks" link failed: the link itself is dead
 * (`invalid`), the check is not among the address's checks (`missing` -
 * the backend's `public_check_not_found`), or anything else (`failed`). */
type LoadError = "invalid" | "missing" | "failed";

function loadError(err: unknown): LoadError {
  if (!isLinkInvalid(err)) return "failed";
  return (err as ApiError).code === "public_check_not_found" ? "missing" : "invalid";
}

/** Load once by a "my checks" link: the value or why it failed. */
function useLoad<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<LoadError | null>(null);
  useEffect(() => {
    let cancelled = false;
    load().then(
      (value) => !cancelled && setData(value),
      (err) => !cancelled && setError(loadError(err)),
    );
    return () => {
      cancelled = true;
    };
    // The page is keyed by its link: one load per mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return { data, error };
}

/** "Move to HRPulsar" (HRP-927): the ready checks not moved yet become
 * processes of the visitor's workspace - after registering with the
 * address, or, with an account, on the app host signed in as it. */
function MoveBlock({
  data,
  token,
  registerHref,
  importHref,
}: {
  data: SavedChecks;
  token: string;
  registerHref: string;
  importHref: string;
}) {
  const t = useTranslations("publicCheck");
  if (!data.checks.some((c) => c.status === "ready" && !c.moved)) return null;
  const href = data.account
    ? `${importHref}#link=${encodeURIComponent(token)}`
    : `${registerHref}&email=${encodeURIComponent(data.email)}`;
  return (
    <section className="space-y-3 rounded-lg border bg-muted/40 p-4" data-testid="check-my-move">
      <h2 className="text-lg font-semibold">{t("myMoveTitle")}</h2>
      <p className="break-words text-muted-foreground">
        {t(data.account ? "myMoveSignIn" : "myMoveRegister", { email: data.email })}
      </p>
      <a href={href} className={buttonVariants()} data-testid="check-my-move-link">
        {t("myMoveCta")}
      </a>
    </section>
  );
}

export function SavedChecksPage({
  token,
  myHref,
  inputHref,
  moveRegisterHref,
  moveImportHref,
}: {
  token: string;
  myHref: string;
  inputHref: string;
  moveRegisterHref: string;
  moveImportHref: string;
}) {
  const t = useTranslations("publicCheck");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const { data, error } = useLoad<SavedChecks>(() => listSaved(token));
  const [asking, setAsking] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [deleteFailed, setDeleteFailed] = useState(false);

  if (deleted) {
    return (
      <section className="space-y-4" data-testid="check-my-deleted">
        <Title>{t("myDeletedTitle")}</Title>
        <p className="text-muted-foreground">{t("myDeletedText")}</p>
        <Link href={inputHref} className="text-sm text-primary hover:underline" data-testid="check-link-new">
          {t("checkAnother")}
        </Link>
      </section>
    );
  }
  if (error === "invalid") return <LinkInvalid />;
  // `missing` here is the switched-off service: the list itself has no other.
  if (error) return <FormErrorBanner message={t("errorUnavailable")} testId="check-my-error" />;
  if (!data) return <Loading />;

  async function remove() {
    setDeleteFailed(false);
    try {
      await deleteSaved(token);
      setDeleted(true);
    } catch {
      setDeleteFailed(true);
    }
  }

  return (
    <section className="space-y-6" data-testid="check-my">
      <div className="space-y-1">
        <Title>{t("myTitle")}</Title>
        <p className="break-words text-muted-foreground">{t("myLead", { email: data.email })}</p>
      </div>
      {data.checks.length === 0 ? (
        <p className="text-muted-foreground" data-testid="check-my-empty">
          {t("myEmpty")}
        </p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {data.checks.map((check) => (
            <li key={check.id} className="p-4" data-testid="check-my-item" data-check-id={check.id}>
              <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
                <Link
                  href={`${myHref}/${encodeURIComponent(token)}/${check.id}`}
                  className="font-medium text-primary hover:underline"
                >
                  {check.title}
                </Link>
                {check.share_moves != null ? (
                  <span className="shrink-0 text-sm tabular-nums">
                    {t("myShare", {
                      share: format.number(check.share_moves / 100, {
                        style: "percent",
                        maximumFractionDigits: 0,
                      }),
                    })}
                  </span>
                ) : null}
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                {t("myItemMeta", {
                  date: format.dateTime(new Date(check.created_at), { dateStyle: "medium" }),
                  status: t(check.moved ? "statusMoved" : STATUS_KEYS[check.status]),
                })}
              </p>
            </li>
          ))}
        </ul>
      )}
      <MoveBlock data={data} token={token} registerHref={moveRegisterHref} importHref={moveImportHref} />
      <div className="flex flex-wrap items-center gap-3 border-t pt-4">
        <Link href={inputHref} className="text-sm text-primary hover:underline" data-testid="check-link-new">
          {t("checkAnother")}
        </Link>
        <Button
          variant="outline"
          className="ml-auto text-destructive"
          onClick={() => setAsking(true)}
          data-testid="check-my-btn-delete"
        >
          {t("myDelete")}
        </Button>
      </div>
      <FormErrorBanner message={deleteFailed ? t("errorGeneric") : null} testId="check-my-delete-error" />
      <ConfirmDialog
        open={asking}
        onOpenChange={setAsking}
        title={t("myDeleteTitle")}
        description={t("myDeleteText")}
        confirmLabel={t("myDeleteConfirm")}
        cancelLabel={tCommon("cancel")}
        destructive
        onConfirm={remove}
        testId="check-my-delete-dialog"
      />
    </section>
  );
}

/** A result opened from "my checks": read through the link of the list -
 * the check's own link token is not stored, so `/r/<token>` cannot be built. */
export function SavedResultPage({
  token,
  id,
  myHref,
  inputHref,
  registerHref,
}: {
  token: string;
  id: string;
  myHref: string;
  inputHref: string;
  registerHref: string;
}) {
  const t = useTranslations("publicCheck");
  const { data, error } = useLoad<CheckRead>(() => getSaved(token, id));
  const back = (
    <Link
      href={`${myHref}/${encodeURIComponent(token)}`}
      className="text-sm text-primary hover:underline"
      data-testid="check-saved-back"
    >
      {t("myBack")}
    </Link>
  );
  if (error === "invalid") return <LinkInvalid />;
  if (error === "missing") {
    return (
      <section className="space-y-4" data-testid="check-saved-not-found">
        <Title>{t("savedNotFoundTitle")}</Title>
        <p className="text-muted-foreground">{t("savedNotFoundText")}</p>
        {back}
      </section>
    );
  }
  if (error) return <FormErrorBanner message={t("errorUnavailable")} testId="check-my-error" />;
  if (!data) return <Loading />;
  return (
    <div className="space-y-6" data-testid="check-saved-result">
      {back}
      {data.status === "ready" && data.result ? (
        <ResultView check={data} result={data.result} inputHref={inputHref} registerHref={registerHref} />
      ) : (
        <section className="space-y-2" data-testid="check-saved-not-ready">
          <Title>{data.status === "error" ? t("runErrorTitle") : t("savedNotReadyTitle")}</Title>
          <p className="text-muted-foreground">
            {data.status === "error" ? t(runErrorKey(data.error_code)) : t("savedNotReadyText")}
          </p>
        </section>
      )}
    </div>
  );
}
