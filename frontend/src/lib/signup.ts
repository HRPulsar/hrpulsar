import { api } from "./api";
import type { VerifyEmailResponse } from "./types";

export interface SignupRequestPayload {
  email: string;
  first_name: string;
  last_name?: string | null;
  company_name?: string | null;
  role?: string | null;
  turnstile_token?: string | null;
}

export interface SignupRequestRead {
  id: string;
  email: string;
  status: string;
  created_at: string;
}

export interface SignupVerifyResponse {
  id: string;
  email: string;
  status: string;
  already_verified: boolean;
}

/** Submit a moderated signup request from the public landing form. */
export async function createSignupRequest(
  data: SignupRequestPayload,
): Promise<SignupRequestRead> {
  return api.post<SignupRequestRead>("/signup-request", data);
}

/** Confirm the visitor owns the email (clicks the verify link). */
export async function verifySignupRequest(
  token: string,
): Promise<SignupVerifyResponse> {
  return api.post<SignupVerifyResponse>("/signup-request/verify", { token });
}

/** Consume a one-time magic-login link emailed after manual approval. The
 * account's first entry sets its password (HRP-1161): without one the
 * backend answers `magic_login_password_required` and keeps the link. */
export async function magicLogin(
  token: string,
  newPassword?: string,
): Promise<VerifyEmailResponse> {
  return api.post<VerifyEmailResponse>("/auth/magic-login", {
    token,
    new_password: newPassword,
  });
}
