"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { API_BASE } from "@/lib/api";
import type { ConsentTokenView } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2, ShieldCheck, ShieldAlert } from "lucide-react";
import { formatDateTime } from "@/lib/date-format";
import { ALERT_TONE } from "@/lib/badge-tones";

interface SignResult {
  signed_at: string;
  status: string;
}

// Mirror of api.ts ``formatApiError`` — but inlined here because the
// public consent page must not import the auth-aware api client (it would
// kick the user to /login on 401, which is wrong for a public link).
// FastAPI returns a string for HTTPException, an array of
// ``{msg, loc, type}`` for 422 validation errors, or an object for
// custom shapes — render each into a readable line.
function formatDetail(detail: unknown, fallback: string): string {
  if (detail == null || detail === "") return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const joined = detail
      .map((entry) => {
        if (entry && typeof entry === "object") {
          const e = entry as { msg?: unknown; loc?: unknown };
          if (typeof e.msg === "string") return e.msg;
        }
        return "";
      })
      .filter(Boolean)
      .join("; ");
    return joined || fallback;
  }
  if (typeof detail === "object") {
    const o = detail as { msg?: unknown; message?: unknown };
    if (typeof o.msg === "string") return o.msg;
    if (typeof o.message === "string") return o.message;
  }
  return fallback;
}

export default function ConsentSignPage() {
  const { token } = useParams<{ token: string }>();
  const [view, setView] = useState<ConsentTokenView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [signing, setSigning] = useState(false);
  const [signed, setSigned] = useState<SignResult | null>(null);
  const [signError, setSignError] = useState<string | null>(null);

  // Public endpoints — no Authorization header. Using fetch directly to
  // avoid the api client's auth-on-401 redirect.
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/recruitment/consent/${token}`);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(
          formatDetail(data.detail, "Link unavailable"),
        );
      }
      const data = (await res.json()) as ConsentTokenView;
      setView(data);
      if (data.status === "signed") {
        setSigned({
          signed_at: data.signed_at || new Date().toISOString(),
          status: "signed",
        });
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load the page",
      );
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleSign() {
    setSigning(true);
    setSignError(null);
    try {
      const res = await fetch(
        `${API_BASE}/recruitment/consent/${token}/sign`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        },
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(
          formatDetail(data.detail, "Failed to save consent"),
        );
      }
      const result = (await res.json()) as SignResult;
      setSigned(result);
    } catch (err) {
      // Don't set the page-level ``error`` — the user already loaded the
      // template successfully, we just want an inline error next to the
      // sign button so they can retry without losing the body text.
      setSignError(err instanceof Error ? err.message : "Error");
    } finally {
      setSigning(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" />
        Loading…
      </div>
    );
  }

  if (error || !view) {
    return (
      <div
        data-testid="consent-page-error"
        className="rounded-lg border border-dashed p-12 text-center text-sm"
      >
        <ShieldAlert className="mx-auto mb-3 size-10 text-amber-500" />
        <p className="text-base font-medium">Link unavailable</p>
        <p className="mt-2 text-muted-foreground">
          {error || "The link has expired or is invalid."}
        </p>
      </div>
    );
  }

  if (signed) {
    return (
      <div
        data-testid="consent-page-signed"
        className={`rounded-lg border p-12 text-center text-sm ${ALERT_TONE.emerald}`}
      >
        <ShieldCheck className="mx-auto mb-3 size-10 text-emerald-600 dark:text-emerald-400" />
        <p className="text-base font-medium">Thank you, your consent has been recorded</p>
        <p className="mt-2">
          Signed on: {formatDateTime(signed.signed_at)}
        </p>
      </div>
    );
  }

  const isExpired = view.status === "expired";

  return (
    <div data-testid="consent-page" className="space-y-4">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          Personal data processing consent
        </h1>
        <p className="text-sm text-muted-foreground">
          Candidate: {view.candidate_name}
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{view.template_name}</CardTitle>
        </CardHeader>
        <CardContent>
          <div
            className="prose prose-sm max-w-none whitespace-pre-wrap text-sm leading-relaxed"
            data-testid="consent-page-body"
          >
            {view.template_body}
          </div>
        </CardContent>
      </Card>

      {isExpired ? (
        <div className={`rounded-md border p-3 text-xs ${ALERT_TONE.amber}`}>
          The link has expired. Ask HR for a new confirmation link.
        </div>
      ) : (
        <div className="space-y-2">
          {signError && (
            <div
              data-testid="consent-page-sign-error"
              role="alert"
              className={`rounded-md border p-2 text-xs ${ALERT_TONE.rose}`}
            >
              {signError}
            </div>
          )}
          <div className="flex items-center justify-between gap-3 rounded-md border bg-card p-3">
            <p className="text-xs text-muted-foreground">
              By signing this consent, you confirm that you have read the terms
              for processing personal data and recording the interview.
            </p>
            <Button
              onClick={handleSign}
              disabled={signing}
              data-testid="consent-page-btn-sign"
            >
              {signing ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <ShieldCheck className="size-4" />
              )}
              Sign consent
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
