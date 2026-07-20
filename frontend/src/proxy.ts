import { NextRequest, NextResponse } from "next/server";

const MARKETING_DOMAIN = process.env.NEXT_PUBLIC_MARKETING_DOMAIN || "";

// HRP-389: the marketing site is a standalone app (marketing/). The product
// frontend no longer serves any marketing route — these paths are only used
// to bounce stray hits on the app domain back to the marketing domain in the
// SaaS domain split, so old links keep working.
const MARKETING_PATHS = [
  "/pricing",
  "/docs",
  "/tour",
  "/changelog",
  "/blog",
  "/personal-brand",
  "/privacy",
  "/terms",
  "/security",
  "/demo",
];
const MARKETING_PREFIXES = ["/docs/", "/methodology/", "/blog/"];

const AUTH_PATHS = [
  "/login",
  "/register",
  "/forgot-password",
  "/reset-password",
  "/verify-email",
  "/accept-invite",
];

function isMarketingPath(pathname: string): boolean {
  if (MARKETING_PATHS.includes(pathname)) return true;
  return MARKETING_PREFIXES.some((p) => pathname.startsWith(p));
}

// /company/[slug] — public company profiles served by the app without auth.
// Single-segment paths under /company that match an app route (positions,
// divisions, profile, specializations) stay behind auth; everything else is
// treated as a public company slug.
function isPublicCompanyPath(pathname: string): boolean {
  const APP_COMPANY_SEGMENTS = ["positions", "divisions", "profile", "specializations"];
  if (/^\/company\/([^/]+)$/.test(pathname)) {
    const segment = pathname.split("/")[2];
    if (!APP_COMPANY_SEGMENTS.includes(segment)) return true;
  }
  return false;
}

function isAuthPath(pathname: string): boolean {
  return AUTH_PATHS.some((p) => pathname.startsWith(p));
}

const TOKEN_PUBLIC_PREFIXES = [
  "/recruitment/invite/",
  "/recruitment/consent/",
  "/reports/share/",
  // HRP-186 invited evaluator form — token in URL, no JWT.
  "/public/assessments/",
  // Cross-domain demo handoff: JWT travels in the URL fragment from
  // marketing /demo so localStorage lands on the app origin.
  "/demo-handoff",
];

function isTokenPublicPath(pathname: string): boolean {
  return TOKEN_PUBLIC_PREFIXES.some((p) => pathname.startsWith(p));
}

// HRP-359: the invited-evaluator page is a token-authenticated contact
// surface for outsiders — it ships with a stricter CSP than the rest of
// the app (nonce'd scripts, whitelisted frames for the resume viewer),
// plus noindex and a no-referrer policy so the token never leaks through
// the Referer header of outbound clicks.
function isPublicAssessmentPath(pathname: string): boolean {
  return pathname.startsWith("/public/assessments/");
}

function publicAssessmentResponse(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const isDev = process.env.NODE_ENV === "development";
  // In dev the API lives on another origin (NEXT_PUBLIC_API_URL); in prod
  // it is same-origin behind /api, so connect-src stays 'self'.
  let apiOrigin = "";
  const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
  if (apiBase.startsWith("http")) {
    try {
      apiOrigin = new URL(apiBase).origin;
    } catch {
      apiOrigin = "";
    }
  }
  // Resume PDFs render from presigned object-storage URLs; a deployment
  // can pin the exact origin via NEXT_PUBLIC_FILES_ORIGIN. Local MinIO
  // serves over plain http, so dev also allows http:.
  const filesOrigin =
    process.env.NEXT_PUBLIC_FILES_ORIGIN || (isDev ? "https: http:" : "https:");
  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self'",
    `connect-src 'self'${apiOrigin ? ` ${apiOrigin}` : ""}`,
    `frame-src 'self' ${filesOrigin}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });
  response.headers.set("Content-Security-Policy", csp);
  response.headers.set("X-Robots-Tag", "noindex, nofollow");
  response.headers.set("Referrer-Policy", "no-referrer");
  return response;
}

function getProtocol(host: string): string {
  // Local dev uses http, production uses https
  return host.includes("localhost") || host.includes(".local") ? "http" : "https";
}

// Middleware redirects MUST be 307 (temporary) + no-store, never 308 (permanent)
// or 301. 308/301 are cached by browsers indefinitely — once a routing rule
// changes, affected clients are stuck following the stale rule until they
// manually clear cache. no-store also keeps a stale auth-state redirect
// (e.g. logged-out `/` → `/login`) from sticking after the user signs in.
function safeRedirect(target: string | URL) {
  const response = NextResponse.redirect(target, 307);
  response.headers.set("Cache-Control", "no-store");
  return response;
}

function crossDomainRedirect(target: string) {
  return safeRedirect(target);
}

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const host =
    request.headers.get("x-forwarded-host") ||
    request.headers.get("host") ||
    "";
  // ``has_token`` is a non-authenticating SSR render hint only — it gates
  // which shell renders first, never grants API access (auth is Bearer-token
  // in the Authorization header, so the backend stays CSRF-safe; see the CSRF
  // invariant note in backend/app/main.py). Do not start authenticating off
  // this cookie without adding CSRF defense first.
  const hasToken = request.cookies.get("has_token")?.value === "1";

  // Next.js RSC prefetch / segment requests can fire without forwarding
  // the SameSite=Lax has_token cookie. Letting them through prevents a
  // spurious 307→/login that the client then follows as a real
  // navigation — see incident 2026-05-14 (vacancy create CRUD e2e).
  // The full document navigation that follows still carries the cookie
  // and goes through the normal auth checks below, so RSC data without
  // an access token simply renders an empty client-side state instead
  // of bouncing the whole tab to /login. The root "/" needs no special
  // case here: src/app/page.tsx owns the dashboard/login redirect at the
  // page level, so RSC navigations to "/" resolve correctly too (HRP-389).
  const isRscRequest =
    request.headers.get("rsc") === "1" ||
    request.headers.get("next-router-prefetch") === "1" ||
    request.headers.get("next-router-segment-prefetch") !== null;
  if (isRscRequest) {
    return NextResponse.next();
  }

  const proto = getProtocol(host);

  // Root → dashboard or login (src/app/page.tsx duplicates this for RSC
  // navigations; the proxy answers full document loads without rendering).
  if (pathname === "/") {
    return safeRedirect(
      new URL(hasToken ? "/dashboard" : "/login", request.url),
    );
  }

  // robots.txt must reach the disallow-all app/robots.ts route — bouncing a
  // crawler to /login reads as "no robots.txt at all". /sitemap.xml has no
  // route in the product frontend; an honest 404 beats a login redirect.
  if (pathname === "/robots.txt" || pathname === "/sitemap.xml") {
    return NextResponse.next();
  }

  // Marketing paths on the app frontend → redirect to the marketing site
  // when one is configured (SaaS domain split). Self-hosted installs have
  // no marketing site — the request falls through to a 404.
  if (MARKETING_DOMAIN && host !== MARKETING_DOMAIN && isMarketingPath(pathname)) {
    return crossDomainRedirect(
      `${proto}://${MARKETING_DOMAIN}${pathname}${search}`,
    );
  }

  // Auth paths
  if (isAuthPath(pathname)) {
    // /accept-invite carries its own invitation token — always serve the form
    if (hasToken && !pathname.startsWith("/accept-invite")) {
      return safeRedirect(new URL("/dashboard", request.url));
    }
    return NextResponse.next();
  }

  // Public and token-gated public paths (company profiles, recruiting
  // evaluator invite, demo handoff, etc.)
  if (isPublicCompanyPath(pathname) || isTokenPublicPath(pathname)) {
    if (isPublicAssessmentPath(pathname)) {
      return publicAssessmentResponse(request);
    }
    return NextResponse.next();
  }

  // All other paths (app routes) — require auth.
  // HRP-84 REDO: preserve the original deep link via ?next= so a
  // participant who clicked an email link lands on the assessment
  // page right after signing in.
  if (!hasToken) {
    return safeRedirect(loginRedirectFor(request));
  }

  const response = NextResponse.next();
  response.headers.set("X-Robots-Tag", "noindex, nofollow");
  return response;
}

// HRP-84 REDO: build the /login URL preserving the original destination
// (path + query) as `next=` so the login page can bounce the user back.
// Pure same-origin, leading-slash paths only — anything else (absolute
// URL, missing /) falls back to /login with no `next`.
function loginRedirectFor(request: NextRequest): URL {
  const url = new URL("/login", request.url);
  const dest = request.nextUrl.pathname + request.nextUrl.search;
  // Same-origin, leading-slash paths only. Reject `/` (anything that lets the
  // second character be a slash or backslash slips a protocol-relative URL
  // past the front check — Chrome and a few proxies treat `/\evil.com` as
  // `//evil.com`).
  if (dest && /^\/[^/\\]/.test(dest)) {
    url.searchParams.set("next", dest);
  }
  return url;
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|site\\.webmanifest|.*\\.(?:jpg|jpeg|png|svg|gif|ico|webp|webmanifest)$).*)"],
};
