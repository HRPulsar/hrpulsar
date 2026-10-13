/** HRP-854: `error_code` of a failed decomposition session or step skill →
 * key in the `coverage` catalog. The map owns the code → key relation only;
 * the wording lives in the catalog. */
const ERROR_KEYS: Record<string, string> = {
  credits_limit_reached: "genErrorCredits",
  credits_demo_quota_exhausted: "genErrorDemoQuota",
  no_allowed_processor: "genErrorNoProcessor",
  ai_no_allowed_processor: "genErrorNoProcessor",
  ai_model_unavailable: "genErrorModelUnavailable",
  output_truncated: "genErrorTruncated",
  overload: "genErrorOverload",
  insufficient_data: "genErrorInsufficientData",
  parse_error: "genErrorParse",
  reaped_stuck: "genErrorNotFinished",
  work_skill_not_applicable: "genErrorNotApplicable",
  work_skill_pack_unavailable: "genErrorPackUnavailable",
};

/** The failure line in the reader's locale: a known code renders from the
 * catalog, an unknown one (`service_error` among them) as the surface's
 * generic failure, and a row from before the codes existed falls back to
 * its stored text. */
export function generationErrorText(
  t: (key: string) => string,
  code: string | null,
  message: string | null,
  fallbackKey: string,
): string {
  if (code) {
    const key = ERROR_KEYS[code];
    return key ? t(key) : t(fallbackKey);
  }
  return message ?? t(fallbackKey);
}
