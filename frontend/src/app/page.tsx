"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// HRP-389: the marketing site lives in the standalone marketing/ app — the
// product root is a pure entry point. Full document loads never reach this
// page (src/proxy.ts 307s "/" straight to /dashboard or /login off the
// has_token cookie); this page exists for client-side navigations to "/"
// (e.g. a logo Link), whose RSC requests bypass the proxy by design. The
// decision is made on the client from the real auth state rather than in a
// server component: RSC prefetches can fire without the SameSite=Lax
// has_token cookie (incident 2026-05-14), so a server-side redirect here
// could cache a spurious /login target for a logged-in user.
export default function RootPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace(
      localStorage.getItem("access_token") ? "/dashboard" : "/login",
    );
  }, [router]);

  return null;
}
