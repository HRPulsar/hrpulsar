"use client";

import { useEffect } from "react";

import { persistDemoSession } from "@/lib/demo";

// Cross-domain demo handoff: marketing /demo mints a JWT on the
// marketing origin, then redirects here with `#token=...&next=...`. We
// persist the token on the app origin (where localStorage and the
// has_token cookie need to live) and continue to the original target.
// The fragment never reaches the server, so the JWT does not land in
// access logs or CF analytics.

function parseHandoffFragment(hash: string): {
  token: string | null;
  next: string;
} {
  const trimmed = hash.startsWith("#") ? hash.slice(1) : hash;
  const params = new URLSearchParams(trimmed);
  const token = params.get("token");
  const rawNext = params.get("next") || "";
  // Same-origin paths only. Mirrors proxy.ts loginRedirectFor — leading
  // slash + non-slash/backslash second char keeps protocol-relative
  // `//evil.com` and `/\evil.com` out.
  const safeNext = /^\/[^/\\]/.test(rawNext) ? rawNext : "/dashboard";
  return { token, next: safeNext };
}

// Mounted via dynamic({ssr: false}) so the fragment is read once on
// the client and we render directly into the final state — no setState
// inside useEffect, no hydration mismatch.
export default function DemoHandoffClient() {
  const { token, next } = parseHandoffFragment(window.location.hash);
  const error = token ? null : "Demo handoff link is missing or invalid.";

  useEffect(() => {
    if (!token) return;
    persistDemoSession(token);
    // Replace the current entry so a Back navigation cannot re-trigger
    // the handoff with a stale token.
    window.location.replace(next);
  }, [token, next]);

  return (
    <div className="flex flex-col items-center gap-6 text-center">
      <h1 className="text-2xl font-semibold text-white">
        {error ? "Could not start the demo" : "Loading your demo..."}
      </h1>
      {error ? (
        <>
          <p
            data-testid="demo-handoff-error"
            className="max-w-sm text-sm text-white/70"
          >
            {error}
          </p>
          <a href="/demo" className="text-sm text-brand hover:underline">
            Start a new demo
          </a>
        </>
      ) : (
        <div className="flex flex-col items-center gap-3">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-brand" />
          <p className="text-sm text-white/60">Signing you in...</p>
        </div>
      )}
    </div>
  );
}