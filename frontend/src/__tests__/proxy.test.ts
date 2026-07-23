import { describe, it, expect, vi, beforeEach } from "vitest";

// Track calls
let redirectTarget: string | URL = "";
let redirectStatus: number | undefined;
let nextHeaders: Map<string, string> = new Map();

vi.mock("next/server", () => ({
  NextRequest: class {},
  NextResponse: {
    redirect(url: string | URL, status?: number) {
      redirectTarget = url;
      redirectStatus = status;
      const headers = new Map<string, string>();
      return {
        type: "redirect",
        url,
        status,
        headers: {
          set: (k: string, v: string) => headers.set(k, v),
          get: (k: string) => headers.get(k),
        },
      };
    },
    next() {
      nextHeaders = new Map();
      return {
        type: "next",
        headers: { set: (k: string, v: string) => nextHeaders.set(k, v), get: (k: string) => nextHeaders.get(k) },
      };
    },
  },
}));

function makeRequest(
  path: string,
  opts: { host?: string; hasToken?: boolean; demoSession?: boolean } = {},
) {
  const host = opts.host || "app.hrpulsar.com";
  const url = `https://${host}${path}`;
  return {
    nextUrl: { pathname: path, search: "" },
    // A real Headers instance — publicAssessmentResponse clones it via
    // `new Headers(request.headers)` for the nonce'd CSP path.
    headers: new Headers({ host }),
    cookies: {
      get(name: string) {
        if (name === "has_token" && opts.hasToken) return { value: "1" };
        if (name === "demo_session" && opts.demoSession) return { value: "1" };
        return undefined;
      },
    },
    url,
  };
}

let proxy: (req: unknown) => { type: string; headers?: { get: (k: string) => string | undefined } };

beforeEach(async () => {
  vi.resetModules();
  redirectTarget = "";
  redirectStatus = undefined;
  nextHeaders = new Map();
  vi.stubEnv("NEXT_PUBLIC_MARKETING_DOMAIN", "hrpulsar.com");
  vi.stubEnv("NEXT_PUBLIC_APP_DOMAIN", "app.hrpulsar.com");
  const mod = await import("../proxy");
  proxy = mod.proxy as typeof proxy;
});

// ─── App domain ─────────────────────────────────────────────

describe("app domain (app.hrpulsar.com)", () => {
  const host = "app.hrpulsar.com";

  it("redirects / to /login when unauthenticated", () => {
    proxy(makeRequest("/", { host }));
    expect(redirectTarget.toString()).toContain("/login");
    expect(redirectStatus).toBe(307);
  });

  it("redirects / to /dashboard when authenticated", () => {
    proxy(makeRequest("/", { host, hasToken: true }));
    expect(redirectTarget.toString()).toContain("/dashboard");
  });

  it("serves /login for unauthenticated users", () => {
    const result = proxy(makeRequest("/login", { host }));
    expect(result.type).toBe("next");
  });

  it("redirects /login to /dashboard when authenticated", () => {
    proxy(makeRequest("/login", { host, hasToken: true }));
    expect(redirectTarget.toString()).toContain("/dashboard");
  });

  it("serves /dashboard for authenticated users", () => {
    const result = proxy(makeRequest("/dashboard", { host, hasToken: true }));
    expect(result.type).toBe("next");
  });

  it("redirects /dashboard to /login when unauthenticated", () => {
    proxy(makeRequest("/dashboard", { host }));
    expect(redirectTarget.toString()).toContain("/login");
  });

  // HRP-389: marketing routes moved to the standalone marketing/ app —
  // stray hits on the app domain bounce to the marketing domain.
  it("redirects /pricing to marketing domain", () => {
    proxy(makeRequest("/pricing", { host }));
    expect(redirectTarget).toBe("https://hrpulsar.com/pricing");
    expect(redirectStatus).toBe(307);
  });

  it("redirects /methodology/ai-fluency to marketing domain", () => {
    proxy(makeRequest("/methodology/ai-fluency", { host }));
    expect(redirectTarget).toBe("https://hrpulsar.com/methodology/ai-fluency");
    expect(redirectStatus).toBe(307);
  });

  // HRP-389: public company profiles are served by the app (no auth), not
  // bounced to the marketing site.
  it("serves /company/[slug] without auth (public company profile)", () => {
    const result = proxy(makeRequest("/company/acme", { host }));
    expect(result.type).toBe("next");
  });

  it("serves /company as app route for authenticated users", () => {
    const result = proxy(makeRequest("/company", { host, hasToken: true }));
    expect(result.type).toBe("next");
  });

  it("serves /company/divisions/* as app route for authenticated users", () => {
    const result = proxy(makeRequest("/company/divisions/abc-123", { host, hasToken: true }));
    expect(result.type).toBe("next");
  });

  it("redirects /company/profile to /login when unauthenticated (app route, not public profile)", () => {
    proxy(makeRequest("/company/profile", { host }));
    expect(redirectTarget.toString()).toContain("/login");
  });

  it("redirects /company/specializations to /login when unauthenticated (app route, not public profile)", () => {
    proxy(makeRequest("/company/specializations", { host }));
    expect(redirectTarget.toString()).toContain("/login");
  });

  it("sets X-Robots-Tag on app routes", () => {
    const result = proxy(makeRequest("/dashboard", { host, hasToken: true }));
    expect(result.headers?.get("X-Robots-Tag")).toBe("noindex, nofollow");
  });

  it("serves /robots.txt without auth (disallow-all route must be reachable)", () => {
    const result = proxy(makeRequest("/robots.txt", { host }));
    expect(result.type).toBe("next");
  });

  it("serves /platform for authenticated users", () => {
    const result = proxy(makeRequest("/platform", { host, hasToken: true }));
    expect(result.type).toBe("next");
  });

  it("serves /settings for authenticated users", () => {
    const result = proxy(makeRequest("/settings/profile", { host, hasToken: true }));
    expect(result.type).toBe("next");
  });

  it("serves /accept-invite even when authenticated", () => {
    const result = proxy(makeRequest("/accept-invite?token=abc123", { host, hasToken: true }));
    expect(result.type).toBe("next");
  });

  it("serves /register during a demo session instead of bouncing into the sandbox", () => {
    const result = proxy(
      makeRequest("/register", { host, hasToken: true, demoSession: true }),
    );
    expect(result.type).toBe("next");
  });

  it("serves /login during a demo session", () => {
    const result = proxy(
      makeRequest("/login", { host, hasToken: true, demoSession: true }),
    );
    expect(result.type).toBe("next");
  });

  it("still redirects / to /dashboard during a demo session", () => {
    proxy(makeRequest("/", { host, hasToken: true, demoSession: true }));
    expect(redirectTarget.toString()).toContain("/dashboard");
  });

  it("serves /recruitment/invite/<token> without auth (token-gated public)", () => {
    const result = proxy(makeRequest("/recruitment/invite/some-token", { host }));
    expect(result.type).toBe("next");
  });

  it("serves /recruitment/consent/<token> without auth (token-gated public)", () => {
    const result = proxy(makeRequest("/recruitment/consent/some-token", { host }));
    expect(result.type).toBe("next");
  });

  it("serves /reports/share/<token> without auth (token-gated public)", () => {
    const result = proxy(makeRequest("/reports/share/some-token", { host }));
    expect(result.type).toBe("next");
  });

  it("serves /public/assessments/<token> without auth (HRP-186 invited evaluator)", () => {
    const result = proxy(makeRequest("/public/assessments/some-token", { host }));
    expect(result.type).toBe("next");
    // HRP-359 hardening headers on the invited-evaluator page.
    const csp = result.headers?.get("Content-Security-Policy") ?? "";
    expect(csp).toContain("'nonce-");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(result.headers?.get("X-Robots-Tag")).toContain("noindex");
    expect(result.headers?.get("Referrer-Policy")).toBe("no-referrer");
  });
});

// ─── Misrouted marketing-domain traffic ─────────────────────
// No special handling: the marketing host is served by the standalone
// marketing app; if its traffic ever reaches this app, paths behave like
// any other host — auth wall for app routes, no redirect ping-pong.

describe("marketing domain traffic reaching the app frontend", () => {
  const host = "hrpulsar.com";

  it("does not bounce marketing paths back to the marketing domain (no redirect loop)", () => {
    proxy(makeRequest("/pricing", { host }));
    expect(redirectTarget.toString()).toContain("/login");
  });

  it("puts app deep links behind the auth wall", () => {
    proxy(makeRequest("/dashboard", { host }));
    expect(redirectTarget.toString()).toContain("/login");
  });

  it("still serves /login (auth pages exist on the app frontend)", () => {
    const result = proxy(makeRequest("/login", { host }));
    expect(result.type).toBe("next");
  });

  it("still serves public company profiles", () => {
    const result = proxy(makeRequest("/company/acme", { host }));
    expect(result.type).toBe("next");
  });

  it("redirects / to /login (root is a product entry point everywhere)", () => {
    proxy(makeRequest("/", { host }));
    expect(redirectTarget.toString()).toContain("/login");
  });
});

// ─── Self-hosted fallback ───────────────────────────────────

describe("self-hosted (no domain env vars)", () => {
  beforeEach(async () => {
    vi.resetModules();
    redirectTarget = "";
    redirectStatus = undefined;
    vi.stubEnv("NEXT_PUBLIC_MARKETING_DOMAIN", "");
    vi.stubEnv("NEXT_PUBLIC_APP_DOMAIN", "");
    const mod = await import("../proxy");
    proxy = mod.proxy as typeof proxy;
  });

  // HRP-389: no marketing site in the product frontend — the root is a
  // product entry point in every deployment mode.
  it("redirects / to /login when unauthenticated", () => {
    proxy(makeRequest("/", { host: "localhost:3000" }));
    expect(redirectTarget.toString()).toContain("/login");
  });

  it("redirects / to /dashboard when authenticated", () => {
    proxy(makeRequest("/", { host: "localhost:3000", hasToken: true }));
    expect(redirectTarget.toString()).toContain("/dashboard");
  });

  it("redirects unauthenticated users to /login", () => {
    proxy(makeRequest("/dashboard", { host: "localhost:3000" }));
    expect(redirectTarget.toString()).toContain("/login");
  });

  it("preserves the deep link via ?next= on the login redirect", () => {
    proxy(makeRequest("/assessments/abc", { host: "localhost:3000" }));
    expect(redirectTarget.toString()).toContain("next=%2Fassessments%2Fabc");
  });

  it("redirects authenticated users from /login to /dashboard", () => {
    proxy(makeRequest("/login", { host: "localhost:3000", hasToken: true }));
    expect(redirectTarget.toString()).toContain("/dashboard");
  });

  it("serves /accept-invite even when authenticated", () => {
    const result = proxy(makeRequest("/accept-invite?token=abc123", { host: "localhost:3000", hasToken: true }));
    expect(result.type).toBe("next");
  });

  it("serves /login for unauthenticated users", () => {
    const result = proxy(makeRequest("/login", { host: "localhost:3000" }));
    expect(result.type).toBe("next");
  });

  it("serves /company/[slug] without auth (public company profile)", () => {
    const result = proxy(makeRequest("/company/acme", { host: "localhost:3000" }));
    expect(result.type).toBe("next");
  });

  it("serves /public/assessments/<token> without auth (HRP-186 invited evaluator)", () => {
    const result = proxy(
      makeRequest("/public/assessments/some-token", { host: "localhost:3000" }),
    );
    expect(result.type).toBe("next");
  });
});

// ─── Local dev with domains ─────────────────────────────────

describe("local dev (*.local domains)", () => {
  beforeEach(async () => {
    vi.resetModules();
    redirectTarget = "";
    redirectStatus = undefined;
    vi.stubEnv("NEXT_PUBLIC_MARKETING_DOMAIN", "hrpulsar.local:3000");
    vi.stubEnv("NEXT_PUBLIC_APP_DOMAIN", "app.hrpulsar.local:3000");
    const mod = await import("../proxy");
    proxy = mod.proxy as typeof proxy;
  });

  it("uses http for local domains", () => {
    proxy(makeRequest("/pricing", { host: "app.hrpulsar.local:3000" }));
    expect(redirectTarget).toBe("http://hrpulsar.local:3000/pricing");
    expect(redirectStatus).toBe(307);
  });
});
