"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";

import { RequireSection } from "@/components/require-section";
import { Button, buttonVariants } from "@/components/ui/button";
import { FormErrorBanner } from "@/components/ui/form-error";
import { ApiError } from "@/lib/api";
import { type Moved, moveSaved } from "@/lib/api/public-check";

/**
 * HRP-927: "Move to HRPulsar" on the public check's "my checks" lands here
 * with the address's link in the fragment (`#link=`): a bearer token, so
 * never in the query - it would reach access logs, `/login?next=` and the
 * Referer. The browser keeps the fragment across the proxy's redirect to
 * /login, and the login page carries it back. Read once, it moves to
 * sessionStorage (a reload still works) and leaves the address bar. One
 * click moves the address's ready checks into this workspace as draft
 * processes - a button, not a call on load, so the user sees which
 * workspace they are signed in to first.
 */
const LINK_KEY = "public-check:import-link";

function readLink(): string {
  const fromHash = new URLSearchParams(window.location.hash.slice(1)).get("link");
  try {
    if (fromHash) sessionStorage.setItem(LINK_KEY, fromHash);
    return fromHash ?? sessionStorage.getItem(LINK_KEY) ?? "";
  } catch {
    return fromHash ?? ""; // storage blocked: the fragment alone still works
  }
}

function ImportChecks() {
  const t = useTranslations("publicCheck");
  // RequireSection renders this only on the client, once the user is known.
  const [link] = useState(readLink);
  useEffect(() => {
    // router.replace to the same path keeps the fragment; the history API
    // drops it (Next syncs its router with replaceState).
    if (window.location.hash) {
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }
  }, []);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Moved | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setDone(await moveSaved(link));
    } catch (err) {
      // The backend's own sentence: another account, a dead link, no right.
      setError(err instanceof ApiError ? err.message : t("errorGeneric"));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <section className="max-w-2xl space-y-4" data-testid="coverage-import-done">
        <h1 className="text-2xl font-semibold">{t("importDoneTitle")}</h1>
        {done.moved > 0 || done.skipped === 0 ? (
          <p className="text-muted-foreground">
            {done.moved > 0 ? t("importDone", { count: done.moved }) : t("importNothing")}
          </p>
        ) : null}
        {/* A check that could not become a process stays in "my checks". */}
        {done.skipped > 0 ? (
          <p className="text-muted-foreground" data-testid="coverage-import-skipped">
            {t("importSkipped", { count: done.skipped })}
          </p>
        ) : null}
        <Link href="/coverage" className={buttonVariants()} data-testid="coverage-import-open">
          {t("importOpen")}
        </Link>
      </section>
    );
  }
  return (
    <section className="max-w-2xl space-y-4" data-testid="coverage-import">
      <h1 className="text-2xl font-semibold">{t("importTitle")}</h1>
      <p className="text-muted-foreground">{t("importLead")}</p>
      {/* Without the link there is nothing to move: the banner says why. */}
      <FormErrorBanner message={link ? error : t("importNoLink")} testId="coverage-import-error" />
      <Button onClick={run} disabled={!link || busy} data-testid="coverage-import-btn">
        {busy ? <Loader2 className="animate-spin" /> : null}
        {t("importSubmit")}
      </Button>
    </section>
  );
}

export default function ImportChecksPage() {
  // The same right as creating a process (`POST /work/containers`).
  return (
    <RequireSection code="coverage" level="manage">
      <Suspense fallback={null}>
        <ImportChecks />
      </Suspense>
    </RequireSection>
  );
}
