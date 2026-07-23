"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Turnstile,
  type TurnstileInstance,
} from "@marsidev/react-turnstile";

/**
 * How long the invisible widget may stay unresolved before we surface a
 * failure. CF normally issues a token within a couple of seconds; the
 * usual reason it never resolves is an ad blocker or privacy extension
 * cutting off ``challenges.cloudflare.com``.
 */
const VERIFY_TIMEOUT_MS = 15_000;

/** User-facing explanation shown by consumers when ``failed`` is true. */
export const TURNSTILE_FAILED_MESSAGE =
  "Browser verification could not load. This is usually caused by an ad " +
  "blocker or privacy extension — allow challenges.cloudflare.com for " +
  "this site and retry.";

/**
 * Site key resolution order:
 *   1. ``window.__ENV__.NEXT_PUBLIC_TURNSTILE_SITE_KEY`` — injected by
 *      ``<RuntimeEnvScript/>`` on every SSR pass. Lets a single root
 *      ``.env`` on the prod VPS change the value without rebuilding
 *      the CI-published frontend image.
 *   2. ``process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY`` — baked at build
 *      time. Picks up local dev (``frontend/.env.local``) and any
 *      build that ships the key as a build-arg.
 */
function readSiteKey(): string {
  if (typeof window !== "undefined") {
    const runtime = window.__ENV__?.NEXT_PUBLIC_TURNSTILE_SITE_KEY;
    if (runtime) return runtime;
  }
  return process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "";
}

export interface TurnstileGate {
  /** React node that mounts the Cloudflare widget (invisible iframe). */
  widget: React.ReactNode;
  /** Latest token issued by CF. ``null`` until the widget resolves. */
  token: string | null;
  /**
   * True when the caller is allowed to proceed: either no site key is
   * configured (dev / E2E bypass — mirrors the backend's empty-secret
   * branch) or a token has been issued by Cloudflare.
   */
  isReady: boolean;
  /**
   * True when the widget reported an error or stayed unresolved past
   * ``VERIFY_TIMEOUT_MS``. Callers must surface
   * ``TURNSTILE_FAILED_MESSAGE`` and offer a retry (``reset()``) instead
   * of waiting on ``isReady`` forever. Cleared automatically if a token
   * does eventually arrive.
   */
  failed: boolean;
  /**
   * Cloudflare tokens are single-use. Call ``reset()`` after submitting
   * so a retry path doesn't get rejected as a replay. Also clears the
   * ``failed`` flag and restarts the widget.
   */
  reset: () => void;
}

/**
 * Hook wrapping the Cloudflare Turnstile widget for our demo-start +
 * signup-request flows. The widget uses the ``interaction-only``
 * appearance: it takes no visual space while Cloudflare verifies
 * silently, but materializes in place when Cloudflare escalates to an
 * interactive challenge. Do NOT switch this to ``size: "invisible"`` —
 * a 0x0 hidden container leaves an escalated challenge nowhere to
 * render, so every visitor Cloudflare chooses to challenge dead-ends in
 * the watchdog timeout (2026-07-23 prod incident: demo/signup blocked
 * for everyone while CF was in an escalating mood).
 *
 * Usage:
 *
 *   const ts = useTurnstileGate();
 *   // ...
 *   {ts.widget}
 *   <button
 *     disabled={!ts.isReady}
 *     onClick={async () => {
 *       try { await api(...ts.token); }
 *       finally { ts.reset(); }
 *     }}>
 *     Submit
 *   </button>
 */
export function useTurnstileGate(): TurnstileGate {
  const instanceRef = useRef<TurnstileInstance | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [interactive, setInteractive] = useState(false);

  const reset = useCallback(() => {
    setToken(null);
    setFailed(false);
    setInteractive(false);
    instanceRef.current?.reset();
  }, []);

  const siteKey = readSiteKey();

  // Watchdog: if the widget neither succeeds nor errors within the
  // timeout (script blocked before it could even report an error), flip
  // to failed so the UI stops showing an eternal "Verifying...". Paused
  // while an interactive challenge is on screen — solving it may
  // legitimately take longer than the timeout.
  useEffect(() => {
    if (!siteKey || token !== null || failed || interactive) return;
    const id = window.setTimeout(() => setFailed(true), VERIFY_TIMEOUT_MS);
    return () => window.clearTimeout(id);
  }, [siteKey, token, failed, interactive]);

  if (!siteKey) {
    return { widget: null, token: null, isReady: true, failed: false, reset };
  }

  const widget = (
    <Turnstile
      ref={instanceRef}
      siteKey={siteKey}
      options={{ appearance: "interaction-only" }}
      onBeforeInteractive={() => setInteractive(true)}
      onSuccess={(value) => {
        setToken(value);
        setFailed(false);
        setInteractive(false);
      }}
      onError={() => {
        setToken(null);
        setFailed(true);
      }}
      onExpire={() => setToken(null)}
    />
  );

  return { widget, token, isReady: token !== null, failed, reset };
}

/** Helper for places that just need to know whether CF is configured. */
export const isTurnstileEnabled = (): boolean => Boolean(readSiteKey());
