"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { api } from "@/lib/api";
import { useAuth } from "@/context/auth-context";
import { useIsSaas } from "@/hooks/use-is-saas";
import { saveDemoAccess } from "@/lib/demo";
import { TURNSTILE_FAILED_MESSAGE, useTurnstileGate } from "@/lib/turnstile";
import type { CreditBalance } from "@/lib/types";

const REFRESH_EVERY_MS = 60_000;

function formatRemaining(target: Date | null): string {
  if (!target) return "—";
  const ms = target.getTime() - Date.now();
  if (ms <= 0) return "expired";
  const totalMinutes = Math.floor(ms / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours <= 0) return `${minutes}m`;
  return `${hours}h ${minutes.toString().padStart(2, "0")}m`;
}

function SaveAccessModal({
  defaultEmail,
  defaultFirstName,
  onClose,
  onSaved,
}: {
  defaultEmail: string;
  defaultFirstName: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    email: defaultEmail,
    first_name: defaultFirstName,
    last_name: "",
    company_name: "",
    role: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const turnstile = useTurnstileGate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!turnstile.isReady) return;
    setError(null);
    setSubmitting(true);
    try {
      await saveDemoAccess({
        email: form.email,
        first_name: form.first_name,
        last_name: form.last_name || null,
        company_name: form.company_name || null,
        role: form.role || null,
        turnstile_token: turnstile.token,
      });
      setDone(true);
      onSaved();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not save access — please try again.",
      );
      // Single-use token was burned; refresh for the next retry.
      turnstile.reset();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      data-testid="demo-save-access-modal"
    >
      <div className="w-full max-w-md rounded-lg border border-white/10 bg-zinc-950 p-6 shadow-xl">
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-lg font-semibold text-white">Save access</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-white/50 hover:text-white"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        {done ? (
          <div className="mt-4 space-y-3 text-sm text-white/80">
            <p>
              Thanks — we&apos;ll email you once a moderator approves the
              request. Until then, feel free to keep exploring the demo.
            </p>
            <button
              type="button"
              onClick={onClose}
              className="mt-2 w-full rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover"
            >
              Got it
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="mt-4 space-y-3">
            <p className="text-sm text-white/60">
              Tell us where to send a permanent sign-in link. The demo keeps
              running in the meantime — your data isn&apos;t migrated, this is
              just a way to come back into a real account once a moderator
              approves you.
            </p>
            {error && (
              <div className="rounded-md bg-red-500/10 px-3 py-2 text-sm text-red-300">
                {error}
              </div>
            )}
            <input
              type="email"
              required
              placeholder="you@company.com"
              value={form.email}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, email: e.target.value }))
              }
              className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder:text-white/30"
              data-testid="demo-save-access-input-email"
            />
            <input
              type="text"
              required
              placeholder="First name"
              value={form.first_name}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, first_name: e.target.value }))
              }
              className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder:text-white/30"
            />
            <input
              type="text"
              placeholder="Company (optional)"
              value={form.company_name}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, company_name: e.target.value }))
              }
              className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder:text-white/30"
            />
            {turnstile.failed && (
              <div
                className="rounded-md bg-red-500/10 px-3 py-2 text-sm text-red-300"
                data-testid="demo-save-access-verify-error"
              >
                {TURNSTILE_FAILED_MESSAGE}{" "}
                <button
                  type="button"
                  onClick={turnstile.reset}
                  className="font-semibold underline"
                  data-testid="demo-save-access-verify-retry"
                >
                  Retry
                </button>
              </div>
            )}
            <button
              type="submit"
              disabled={submitting || !turnstile.isReady}
              className="w-full rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-60"
              data-testid="demo-save-access-submit"
            >
              {submitting
                ? "Sending..."
                : !turnstile.isReady && !turnstile.failed
                  ? "Verifying..."
                  : "Save access"}
            </button>
            {turnstile.widget}
          </form>
        )}
      </div>
    </div>
  );
}

export function DemoBanner() {
  const { user } = useAuth();
  const router = useRouter();
  const [credits, setCredits] = useState<CreditBalance | null>(null);
  const [tick, setTick] = useState(0);
  const [showModal, setShowModal] = useState(false);

  const isDemo = !!user?.tenant_is_demo;
  const expiresAt = user?.tenant_expires_at
    ? new Date(user.tenant_expires_at)
    : null;

  // Credits exist only on SaaS — community demo stacks have no /billing/*
  // routes, so skip the request there entirely (HRP-397).
  const isSaas = useIsSaas();

  useEffect(() => {
    if (!isDemo || !isSaas) return;
    api
      .get<CreditBalance>("/billing/credits")
      .then(setCredits)
      .catch(() => {});
  }, [isDemo, isSaas]);

  useEffect(() => {
    if (!isDemo) return;
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_EVERY_MS);
    return () => clearInterval(id);
  }, [isDemo]);

  if (!isDemo || !user) return null;

  const remaining = formatRemaining(expiresAt);
  const expired = remaining === "expired";
  const creditsLeft = credits ? credits.total : null;
  // tick is consumed only to trigger a re-render so formatRemaining recomputes.
  void tick;

  if (expired) {
    return (
      <div
        className="border-b border-amber-400/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-100"
        data-testid="demo-banner-expired"
      >
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3">
          <span>
            This demo session has expired. Sign up for an account to keep
            exploring.
          </span>
          <button
            type="button"
            onClick={() => router.push("/register")}
            className="rounded-md bg-amber-300 px-4 py-1.5 text-sm font-semibold text-zinc-950 hover:bg-amber-200"
          >
            Create account
          </button>
        </div>
      </div>
    );
  }

  return (
    <>
      <div
        className="border-b border-brand/40 bg-brand/10 px-4 py-2 text-sm text-white"
        data-testid="demo-banner"
      >
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span className="font-semibold uppercase tracking-wider text-brand">
              Demo session
            </span>
            <span data-testid="demo-banner-remaining">
              {remaining} remaining
            </span>
            {creditsLeft !== null && (
              <span data-testid="demo-banner-credits">
                {creditsLeft} credits left
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={() => setShowModal(true)}
            className="rounded-md border border-white/30 px-3 py-1 text-sm hover:bg-white/10"
            data-testid="demo-banner-save-access"
          >
            Save access
          </button>
        </div>
      </div>
      {showModal && (
        <SaveAccessModal
          defaultEmail=""
          defaultFirstName={user.first_name || ""}
          onClose={() => setShowModal(false)}
          onSaved={() => {
            /* leave modal open to show the confirmation card */
          }}
        />
      )}
    </>
  );
}
