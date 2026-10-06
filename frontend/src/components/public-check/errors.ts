import { ApiError } from "@/lib/api";

/** `publicCheck` catalog keys for a refused `POST /public-check/checks`, by
 * the error codes of the HRP-923 contract. 404 there means the service is
 * off - for the visitor that is "unavailable". */
const CREATE_ERROR_KEYS: Record<string, string> = {
  public_check_rate_limited: "errorRateLimited",
  public_check_captcha_failed: "errorCaptcha",
  public_check_daily_limit: "errorDailyLimit",
  public_check_unavailable: "errorUnavailable",
  public_check_not_found: "errorUnavailable",
};

/** The input field a 422 names: the last named segment of the first
 * error's `loc` (`["body", "answers", "team_size"]` → `team_size`). */
export function invalidField(err: unknown): string | null {
  if (!(err instanceof ApiError) || err.status !== 422) return null;
  const first: unknown = Array.isArray(err.detail) ? err.detail[0] : null;
  const loc = (first as { loc?: unknown } | null)?.loc;
  if (!Array.isArray(loc)) return null;
  const named = loc.filter((s): s is string => typeof s === "string" && s !== "body");
  return named.at(-1) ?? null;
}

/** `publicCheck` catalog key for a failed create; unknown codes and network
 * failures get the general one. */
export function createErrorKey(err: unknown): string {
  if (!(err instanceof ApiError)) return "errorGeneric";
  if (err.status === 422) {
    return invalidField(err) === "description" ? "errorDescriptionLength" : "errorInvalid";
  }
  return (err.code && CREATE_ERROR_KEYS[err.code]) || "errorGeneric";
}

/** `publicCheck` catalog key for a check that ended in `error`, by the
 * engine's `error_code`. */
const RUN_ERROR_KEYS: Record<string, string> = {
  overload: "runErrorOverload",
  output_truncated: "runErrorTooLong",
};

export function runErrorKey(code: string | null): string {
  return (code && RUN_ERROR_KEYS[code]) || "runErrorGeneric";
}

/** `publicCheck` key for a refused save or link request (HRP-926). A 422
 * there can only be the address; a 404 is the check gone (on a save) or
 * the service off (`notFoundKey` for the link request). */
const SAVE_ERROR_KEYS: Record<string, string> = {
  public_check_rate_limited: "saveErrorRateLimited",
  public_check_captcha_failed: "errorCaptcha",
  public_check_already_saved: "saveErrorAlreadySaved",
  public_check_not_owner: "saveErrorNotOwner",
};

export function saveErrorKey(err: unknown, notFoundKey = "saveErrorExpired"): string {
  if (!(err instanceof ApiError)) return "errorGeneric";
  if (err.status === 422) return "saveErrorEmail";
  if (err.code === "public_check_not_found") return notFoundKey;
  return (err.code && SAVE_ERROR_KEYS[err.code]) || "errorGeneric";
}
