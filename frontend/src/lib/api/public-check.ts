/**
 * Client of the public process check API (HRP-922) for the anonymous pages
 * of HRP-924 / HRP-925.
 *
 * Raw fetch rather than `api`: the visitor has no session, and the auth
 * pipeline (token refresh, forced logout) must never run on these pages.
 * The shapes mirror backend/app/modules/public_check/schemas.py - its
 * docstrings are the contract.
 */
import { localeRequestHeaders } from "@/i18n/config";
import { API_BASE, ApiError, api } from "@/lib/api";

// Input limits - the same numbers as backend/app/modules/public_check/
// schemas.py (DESCRIPTION_MIN, DESCRIPTION_MAX, ANSWER_MAX, UTM_MAX and the
// Answers field bounds). The backend refuses anything outside with 422.
export const DESCRIPTION_MIN = 20;
export const DESCRIPTION_MAX = 4000;
export const ANSWER_MAX = 100;
export const UTM_MAX = 200;
export const TEAM_SIZE_MAX = 100_000;
export const HOURLY_RATE_MAX = 100_000;
// The longest dictated recording, seconds: the timer stops it here. The same
// number as MAX_SECONDS in backend/app/modules/public_check/voice.py.
export const VOICE_MAX_SECONDS = 180;
// How long the page waits for a transcription: a little past the server's
// own ceiling (TRANSCRIBE_TIMEOUT_S, 120 s, in voice.py), so the server's
// 503 normally arrives first.
export const VOICE_TIMEOUT_MS = 130_000;

export const FREQUENCIES = [
  "daily",
  "weekly",
  "monthly",
  "quarterly",
  "yearly",
  "ad_hoc",
] as const;
export type Frequency = (typeof FREQUENCIES)[number];

/** The breakdown languages the backend accepts. */
export type CheckLocale = "en" | "de";
export type CheckStatus = "pending" | "running" | "ready" | "error";
export type CheckPhase = "splitting" | "classifying" | "finishing";
export type Bucket = "moves" | "to_review" | "stays";
export type StepMode =
  | "automatable"
  | "draft_then_review"
  | "review_required"
  | "blocked_judgment"
  | "blocked_physical";

export interface CheckAnswers {
  industry?: string | null;
  team_size?: number | null;
  frequency?: Frequency | null;
  hourly_rate?: number | null;
  currency?: string;
}

export interface CheckUtm {
  source?: string;
  medium?: string;
  campaign?: string;
  content?: string;
  term?: string;
}

export interface CheckCreate {
  description: string;
  answers: CheckAnswers;
  locale: CheckLocale;
  utm?: CheckUtm | null;
  /** Sent only when the captcha widget issued one (HRP-923). */
  turnstile_token?: string;
  /** The field holds dictated text (HRP-947): the model is told so. */
  dictated?: boolean;
}

export interface CheckCreated {
  token: string;
  /** Saves the check by email (HRP-926); shown once, for this browser only. */
  owner_key: string;
  status: CheckStatus;
  expires_at: string | null;
}

export interface StepReason {
  mode: StepMode | null;
  codes: string[];
  responsibility: "none" | "reputational" | "formal" | "regulatory";
  output_type: "draft" | "external_change";
}

export interface ResultStep {
  position: number;
  title: string;
  description: string | null;
  codes: string[];
  hours_per_run: number | null;
  runs_per_year: number | null;
  hours_per_year: number | null;
  reason: StepReason;
}

export interface CheckHours {
  total: number;
  moves: number;
  to_review: number;
  stays: number;
  to_review_after: number;
  freed: number;
  unestimated: number;
}

export interface CheckMoney {
  total: number;
  moves: number;
  to_review: number;
  stays: number;
  to_review_after: number;
  freed: number;
  currency: string;
}

export interface CheckResult {
  schema_version: 1;
  preliminary: boolean;
  catalog_version: string;
  shares: { moves: number; to_review: number; stays: number } | null;
  hours: CheckHours;
  money: CheckMoney | null;
  buckets: Record<Bucket, ResultStep[]>;
  out_of_scope: ResultStep[];
}

export interface CheckRead {
  status: CheckStatus;
  phase: CheckPhase | null;
  error_code: string | null;
  locale: CheckLocale;
  /** The process's name: the description's first line, cut (HRP-928). */
  title: string;
  description: string;
  answers: CheckAnswers;
  /** The visit's campaign (HRP-931): "try again" and the share beacon carry it. */
  utm?: CheckUtm | null;
  /** Dictated by voice (HRP-947): "try again" sends the input the same way. */
  dictated?: boolean;
  created_at: string;
  expires_at: string | null;
  result: CheckResult | null;
}

/** "AI takes N of my M steps" (HRP-928/930): the steps an agent takes
 * against every step in scope. By steps, not hours - a result may have no
 * shares at all (the gallery has no hours). */
export function stepCounts(result: CheckResult): { moves: number; total: number } {
  const { moves, to_review, stays } = result.buckets;
  return { moves: moves.length, total: moves.length + to_review.length + stays.length };
}

/** The breakdown language for an interface locale: en or de, else en. */
export function checkLocaleFor(uiLocale: string): CheckLocale {
  return uiLocale === "de" ? "de" : "en";
}

async function send<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      // A FormData body sets its own multipart type with the boundary.
      ...(typeof init.body === "string" ? { "Content-Type": "application/json" } : {}),
      ...localeRequestHeaders(),
    },
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail;
    throw new ApiError(
      res.status,
      typeof detail === "string" ? detail : res.statusText,
      detail,
      typeof body?.code === "string" ? body.code : undefined,
    );
  }
  return body as T;
}

export function createCheck(data: CheckCreate): Promise<CheckCreated> {
  return send<CheckCreated>("/public-check/checks", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function getCheck(token: string): Promise<CheckRead> {
  return send<CheckRead>(`/public-check/checks/${encodeURIComponent(token)}`);
}

const UTM_FIELDS = ["source", "medium", "campaign", "content", "term"] as const;

/** `utm_*` of the page URL for the funnel (HRP-931), cut to the backend's
 * limit: a tracking parameter must never cost the visitor a 422. */
export function utmFrom(
  params: Record<string, string | string[] | undefined>,
): CheckUtm | null {
  const utm: CheckUtm = {};
  for (const field of UTM_FIELDS) {
    const raw = params[`utm_${field}`];
    const value = (Array.isArray(raw) ? raw[0] : raw)?.trim().slice(0, UTM_MAX);
    if (value) utm[field] = value;
  }
  return Object.keys(utm).length > 0 ? utm : null;
}

// --- Funnel beacons (HRP-931) ------------------------------------------------

/** The client steps of the funnel; the server counts the rest from checks. */
export type FunnelEvent = "opened" | "started" | "shared";

/** Fire and forget: a lost beacon is a lost count, never a broken page. */
export function trackEvent(event: FunnelEvent, utm?: CheckUtm | null): void {
  send("/public-check/events", {
    method: "POST",
    body: JSON.stringify({ event, utm: utm ?? null }),
  }).catch(() => {});
}

// --- Saved by email (HRP-926) ------------------------------------------------

export interface SaveRequest {
  email: string;
  /** The consent to process the address - the backend refuses without it. */
  consent: true;
  /** The separate, optional opt-in to product news. */
  marketing: boolean;
  /** The language of the address's letters: the interface's, en or de. */
  locale: CheckLocale;
  /** `CheckCreated.owner_key` - a shared link has none and cannot save. */
  owner_key: string;
  turnstile_token?: string;
}

/** The Turnstile ``action`` of each form - the server refuses a token solved
 * for another (``ACTION_*`` in backend public_check/router.py). */
export const TURNSTILE_ACTIONS = {
  check: "public_check",
  save: "public_check_save",
  link: "public_check_link",
} as const;

/** Always `confirm`: a letter to confirm this check is on its way, whether
 * the address was confirmed before or not - the answer never says. */
export interface SaveResult {
  status: "confirm";
}

export interface SavedCheck {
  id: string;
  created_at: string;
  title: string;
  status: CheckStatus;
  /** The headline share of a ready result with percentages. */
  share_moves: number | null;
  expires_at: string | null;
  /** A process of a workspace already (HRP-927). */
  moved: boolean;
}

export interface SavedChecks {
  email: string;
  checks: SavedCheck[];
  /** An account of this email exists: moving signs in, not registers. */
  account: boolean;
}

const enc = encodeURIComponent;

export function saveCheck(token: string, data: SaveRequest): Promise<SaveResult> {
  return send<SaveResult>(`/public-check/checks/${enc(token)}/save`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

/** "Send me my link" - always the same 202, whatever the address. */
export function requestLink(data: { email: string; turnstile_token?: string }): Promise<unknown> {
  return send(`/public-check/links`, { method: "POST", body: JSON.stringify(data) });
}

export function confirmEmail(token: string): Promise<unknown> {
  return send(`/public-check/confirm/${enc(token)}`, { method: "POST" });
}

export function unsubscribe(token: string): Promise<unknown> {
  return send(`/public-check/unsubscribe/${enc(token)}`, { method: "POST" });
}

export function listSaved(token: string): Promise<SavedChecks> {
  return send<SavedChecks>(`/public-check/mine/${enc(token)}`);
}

export function getSaved(token: string, id: string): Promise<CheckRead> {
  return send<CheckRead>(`/public-check/mine/${enc(token)}/checks/${enc(id)}`);
}

export function deleteSaved(token: string): Promise<unknown> {
  return send(`/public-check/mine/${enc(token)}`, { method: "DELETE" });
}

// --- Moved into a workspace (HRP-927) ----------------------------------------

/** `skipped` - checks that could not become a process; they stay unmoved. */
export interface Moved {
  moved: number;
  skipped: number;
}

/** The checks behind a "my checks" link become processes of the signed-in
 * user's workspace - only when the user's email is the link's address. The
 * one call of these pages with a session: through `api`, not `send`. */
export function moveSaved(token: string): Promise<Moved> {
  return api.post<Moved>(`/public-check/mine/${enc(token)}/move`);
}

// --- Dictation (HRP-947) -----------------------------------------------------

/** The text of a recording; `language` as the provider named it, if it did.
 * Empty `text` - no speech was heard. */
export interface Transcript {
  text: string;
  language: string | null;
}

/** A `MediaRecorder` recording in, its text out. Nothing is stored. */
export function transcribe(audio: Blob): Promise<Transcript> {
  const body = new FormData();
  body.append("audio", audio, "recording");
  return send<Transcript>("/public-check/transcribe", {
    method: "POST",
    body,
    signal: AbortSignal.timeout(VOICE_TIMEOUT_MS),
  });
}
