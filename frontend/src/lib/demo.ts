import { api } from "./api";

// HRP-389: the demo *start* flow (startDemoSession / completeDemoSession)
// lives in the marketing app — marketing/src/lib/demo.ts is the executed
// copy. The product frontend keeps only the app-origin half of the contract:
// persisting the handed-off session (/demo-handoff) and capturing the
// visitor's email from the in-product demo banner.

export interface DemoSaveAccessPayload {
  email: string;
  first_name: string;
  last_name?: string | null;
  company_name?: string | null;
  role?: string | null;
  turnstile_token?: string | null;
  /** Convert the demo tenant into the real workspace on approve. */
  keep_demo_data?: boolean;
}

export interface DemoSaveAccessResponse {
  signup_request_id: string;
  email: string;
  status: string;
}

/** Marketing-origin copy of the demo JWT, kept under a dedicated key so
 * it can never be mistaken for a real auth session: `access_token` +
 * `has_token` drive the proxy middleware and AuthProvider, this key
 * drives exactly one thing — the resume hint sent with /demo/start.
 * Stored via localStorage (not a parent-domain cookie) so the JWT is
 * never attached to regular page requests and can't leak into access
 * logs or CF analytics — mirrors the /demo-handoff fragment rationale.
 */
const DEMO_RESUME_TOKEN_KEY = "demo_access_token";

/** Persist a freshly minted demo access token in the current origin.
 * Mirrors the lib/auth.ts contract (localStorage + has_token cookie) so
 * the proxy middleware and AuthProvider both treat the session as live.
 */
export function persistDemoSession(accessToken: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem("access_token", accessToken);
  localStorage.removeItem("refresh_token");
  // Resume hint survives a logout (which only clears the auth keys) so
  // re-clicking "Try the demo" lands back in the same sandbox instead
  // of minting a fresh credit grant.
  localStorage.setItem(DEMO_RESUME_TOKEN_KEY, accessToken);
  document.cookie = "has_token=1; path=/; SameSite=Lax";
  // Marks the session as a demo sandbox for the proxy middleware: with it
  // set, /register and /login keep serving the real forms instead of
  // bouncing to /dashboard (i.e. into the sandbox). Cleared by a real
  // login/logout in lib/auth.ts.
  document.cookie = "demo_session=1; path=/; SameSite=Lax";
}

/** Capture a demo visitor's email as a moderated signup request. */
export async function saveDemoAccess(
  data: DemoSaveAccessPayload,
): Promise<DemoSaveAccessResponse> {
  return api.post<DemoSaveAccessResponse>("/demo/save-access", data);
}

// --- Demo persona switcher (HRP-612 wave 2) ---

export type DemoPersona = "admin" | "employee";

interface DemoSwitchViewResponse {
  access_token: string;
  persona: DemoPersona;
}

/** Swap the demo session to the requested persona and reload the app on
 * /dashboard so AuthProvider re-initializes with the new identity.
 *
 * Deliberately NOT persistDemoSession: the resume hint must keep the
 * original marketing-issued token — otherwise a later "Try the demo"
 * click would resume the sandbox as the last-viewed persona. Tokens are
 * not stored per persona either; /demo/switch-view re-issues them on
 * every swap, so nothing privileged lingers in localStorage. */
export async function switchDemoPersona(persona: DemoPersona): Promise<void> {
  const res = await api.post<DemoSwitchViewResponse>("/demo/switch-view", {
    persona,
  });
  localStorage.setItem("access_token", res.access_token);
  localStorage.removeItem("refresh_token");
  document.cookie = "has_token=1; path=/; SameSite=Lax";
  document.cookie = "demo_session=1; path=/; SameSite=Lax";
  window.location.assign("/dashboard");
}
