import { api } from "./api";
import { clearLocaleCookie } from "@/i18n/config";
import type {
  TokenResponse,
  TenantInfo,
  TenantSelectionRequired,
  User,
  PendingVerificationResponse,
  VerifyEmailResponse,
} from "./types";

export type LoginResult = TokenResponse | TenantSelectionRequired;

function isTenantSelection(r: LoginResult): r is TenantSelectionRequired {
  return "requires_tenant_selection" in r && r.requires_tenant_selection === true;
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

export function isAuthenticated(): boolean {
  return !!getAccessToken();
}

function saveTokens(tokens: TokenResponse) {
  localStorage.setItem("access_token", tokens.access_token);
  localStorage.setItem("refresh_token", tokens.refresh_token);
  // Set cookie so proxy middleware knows user is authenticated
  document.cookie = "has_token=1; path=/; SameSite=Lax";
  // A real sign-in supersedes any demo sandbox — drop the marker so auth
  // pages regain their signed-in → /dashboard redirect (see proxy.ts).
  document.cookie =
    "demo_session=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
}

function clearTokens() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  document.cookie = "has_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  document.cookie =
    "demo_session=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  // i18n (F1): the locale cookie mirrors the account preference — drop
  // it on logout so the next user on a shared device starts from
  // Accept-Language instead of inheriting the previous user's language.
  clearLocaleCookie();
}

export async function login(
  email: string,
  password: string,
): Promise<LoginResult> {
  const result = await api.post<LoginResult>("/auth/login", {
    email,
    password,
  });
  if (!isTenantSelection(result)) {
    saveTokens(result);
  }
  return result;
}

/** Returns the redirect path from login result (e.g. "/platform" for platform admins). */
export function getLoginRedirect(result: LoginResult): string {
  if (!isTenantSelection(result) && result.redirect_to) {
    return result.redirect_to;
  }
  return "/dashboard";
}

export { isTenantSelection };

export async function selectTenant(
  email: string,
  password: string,
  tenantId: string,
): Promise<TokenResponse> {
  const tokens = await api.post<TokenResponse>("/auth/select-tenant", {
    email,
    password,
    tenant_id: tenantId,
  });
  saveTokens(tokens);
  return tokens;
}

export async function switchTenant(tenantId: string): Promise<TokenResponse> {
  const tokens = await api.post<TokenResponse>("/auth/switch-tenant", {
    tenant_id: tenantId,
  });
  saveTokens(tokens);
  return tokens;
}

export async function fetchUserTenants(): Promise<TenantInfo[]> {
  return api.get<TenantInfo[]>("/auth/tenants");
}

export async function register(data: {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  company_name: string;
}): Promise<PendingVerificationResponse> {
  return api.post<PendingVerificationResponse>("/auth/register", data);
}

export interface InvitationPreview {
  email: string;
  name: string;
}

/** Token-scoped invitation preview used to pre-fill the accept form (HRP-435). */
export async function fetchInvitationPreview(
  token: string,
): Promise<InvitationPreview> {
  return api.get<InvitationPreview>(
    `/auth/invitations/${encodeURIComponent(token)}`,
  );
}

export async function acceptInvitation(data: {
  token: string;
  password: string;
  first_name: string;
  last_name: string;
}): Promise<TokenResponse> {
  const resp = await api.post<TokenResponse & { user: User }>(
    "/auth/accept-invite",
    data,
  );
  saveTokens(resp);
  return resp;
}

export async function verifyEmail(
  token: string,
): Promise<VerifyEmailResponse> {
  const resp = await api.post<VerifyEmailResponse>("/auth/verify-email", {
    token,
  });
  saveTokens(resp);
  return resp;
}

export async function resendVerification(email: string): Promise<void> {
  await api.post("/auth/resend-verification", { email });
}

export function logout() {
  clearTokens();
  window.location.href = "/login";
}

export async function fetchCurrentUser(): Promise<User> {
  return api.get<User>("/auth/me");
}
