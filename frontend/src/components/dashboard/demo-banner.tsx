"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { useAuth } from "@/context/auth-context";
import { useIsSaas } from "@/hooks/use-is-saas";
import { saveDemoAccess, switchDemoPersona, type DemoPersona } from "@/lib/demo";
import { cn } from "@/lib/utils";
import { TURNSTILE_FAILED_MESSAGE_KEY, useTurnstileGate } from "@/lib/turnstile";
import type { CreditBalance } from "@/lib/types";

const REFRESH_EVERY_MS = 60_000;

/** Sentinel returned when the session is over — never rendered (the caller
 * swaps in the expired banner), so it stays out of the message catalog. */
const EXPIRED = "expired";

function formatRemaining(target: Date | null): string {
  if (!target) return "—";
  const ms = target.getTime() - Date.now();
  if (ms <= 0) return EXPIRED;
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
    keep_demo_data: false,
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const turnstile = useTurnstileGate();
  const t = useTranslations("dashboard");
  // The Turnstile failure copy is shared with the signup form, so it lives
  // in the `auth` namespace (HRP-476).
  const tAuth = useTranslations("auth");

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
        keep_demo_data: form.keep_demo_data,
      });
      setDone(true);
      onSaved();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t("demoSaveFailed"),
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
          <h2 className="text-lg font-semibold text-white">
            {t("demoSaveAccess")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-white/50 hover:text-white"
            aria-label={t("demoClose")}
          >
            ✕
          </button>
        </div>
        {done ? (
          <div className="mt-4 space-y-3 text-sm text-white/80">
            <p>{t("demoSavedThanks")}</p>
            <button
              type="button"
              onClick={onClose}
              className="mt-2 w-full rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover"
            >
              {t("demoGotIt")}
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="mt-4 space-y-3">
            <p className="text-sm text-white/60">{t("demoSaveIntro")}</p>
            {error && (
              <div className="rounded-md bg-red-500/10 px-3 py-2 text-sm text-red-300">
                {error}
              </div>
            )}
            <input
              type="email"
              required
              placeholder={t("demoEmailPlaceholder")}
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
              placeholder={t("demoFirstNamePlaceholder")}
              value={form.first_name}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, first_name: e.target.value }))
              }
              className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder:text-white/30"
            />
            <input
              type="text"
              placeholder={t("demoCompanyPlaceholder")}
              value={form.company_name}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, company_name: e.target.value }))
              }
              className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder:text-white/30"
            />
            <label className="flex items-start gap-2 text-sm text-white/80">
              <input
                type="checkbox"
                checked={form.keep_demo_data}
                onChange={(e) =>
                  setForm((prev) => ({
                    ...prev,
                    keep_demo_data: e.target.checked,
                  }))
                }
                className="mt-0.5"
                data-testid="demo-save-access-keep-data"
              />
              {t("demoKeepData")}
            </label>
            {turnstile.failed && (
              <div
                className="rounded-md bg-red-500/10 px-3 py-2 text-sm text-red-300"
                data-testid="demo-save-access-verify-error"
              >
                {tAuth(TURNSTILE_FAILED_MESSAGE_KEY)}{" "}
                <button
                  type="button"
                  onClick={turnstile.reset}
                  className="font-semibold underline"
                  data-testid="demo-save-access-verify-retry"
                >
                  {t("demoRetry")}
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
                ? t("demoSending")
                : !turnstile.isReady && !turnstile.failed
                  ? t("demoVerifying")
                  : t("demoSaveAccess")}
            </button>
            {turnstile.widget}
          </form>
        )}
      </div>
    </div>
  );
}

/** The demo admin persona's throw-away user lives on this domain (see
 * backend ``_create_demo_user``); seeded employees use demo.example.com. */
const DEMO_ADMIN_EMAIL_DOMAIN = "@demo.hrpulsar.local";

function PersonaSwitch({ activePersona }: { activePersona: DemoPersona }) {
  const t = useTranslations("dashboard");
  const [switching, setSwitching] = useState(false);

  async function handleSwitch(persona: DemoPersona) {
    if (persona === activePersona || switching) return;
    setSwitching(true);
    try {
      await switchDemoPersona(persona);
    } catch {
      // A failed swap otherwise looks like a dead button — say so.
      toast.error(t("demoPersonaSwitchFailed"));
      setSwitching(false);
    }
  }

  const personas: DemoPersona[] = ["admin", "employee"];
  return (
    <span className="flex items-center gap-1.5">
      <span className="text-foreground/60">{t("demoViewAs")}</span>
      <span className="flex overflow-hidden rounded-md border border-foreground/30">
        {personas.map((p) => (
          <button
            key={p}
            type="button"
            disabled={switching}
            onClick={() => handleSwitch(p)}
            className={cn(
              "px-2.5 py-0.5 text-sm",
              p === activePersona
                ? "bg-brand text-white"
                : "hover:bg-foreground/10",
            )}
            data-testid={`demo-banner-view-${p}`}
          >
            {t(p === "admin" ? "demoPersonaAdmin" : "demoPersonaEmployee")}
          </button>
        ))}
      </span>
    </span>
  );
}

export function DemoBanner() {
  const { user } = useAuth();
  const router = useRouter();
  const t = useTranslations("dashboard");
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
  const expired = remaining === EXPIRED;
  // HRP-547: quote what can actually be spent — credits held by an upload
  // in flight are subtracted from `available`, and the gate reads the same
  // field, so the banner must not promise a number the next action refuses.
  const creditsLeft = credits ? (credits.available ?? credits.total) : null;
  // tick is consumed only to trigger a re-render so formatRemaining recomputes.
  void tick;

  if (expired) {
    return (
      <div
        className="border-b border-amber-400/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-700 dark:text-amber-400"
        data-testid="demo-banner-expired"
      >
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3">
          <span>{t("demoExpired")}</span>
          <button
            type="button"
            onClick={() => router.push("/register")}
            className="rounded-md bg-amber-300 px-4 py-1.5 text-sm font-semibold text-zinc-950 hover:bg-amber-200"
          >
            {t("demoCreateAccount")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <>
      <div
        className="border-b border-brand/40 bg-brand/10 px-4 py-2 text-sm text-foreground"
        data-testid="demo-banner"
      >
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span className="font-semibold uppercase tracking-wider text-brand">
              {t("demoSessionLabel")}
            </span>
            <span data-testid="demo-banner-remaining">
              {t("demoRemaining", { time: remaining })}
            </span>
            {creditsLeft !== null && (
              <span data-testid="demo-banner-credits">
                {t("demoCreditsLeft", { count: creditsLeft })}
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <PersonaSwitch
              activePersona={
                user.email?.endsWith(DEMO_ADMIN_EMAIL_DOMAIN)
                  ? "admin"
                  : "employee"
              }
            />
            <button
              type="button"
              onClick={() => setShowModal(true)}
              className="rounded-md border border-foreground/30 px-3 py-1 text-sm hover:bg-foreground/10"
              data-testid="demo-banner-save-access"
            >
              {t("demoSaveAccess")}
            </button>
          </div>
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
