// Frontend i18n shim for answer-scale level labels.
//
// Origin/seeded levels carry a stable `system_code` and a NULL
// `system_title` — they render through the dictionary below. Tenant-
// custom levels carry `system_code = null` and an HR-authored
// `system_title`, which renders verbatim. Until Phase F ships real
// i18next/react-intl, this dictionary is the single source of truth for
// localized labels of seeded levels.
//
// When real i18n lands, replace `SCALE_LEVEL_I18N[code]` lookups with
// `t(`scale.level.${code}`)` — the backend schema and DB stay the same.

export const SCALE_LEVEL_I18N: Record<string, string> = {
  below_expectations: "Below expectations",
  meets_with_growth: "Meets expectations with growth areas",
  fully_meets: "Fully meets expectations",
};

interface ScaleLevelLike {
  system_code: string | null;
  system_title: string | null;
}

export function scaleLevelLabel(level: ScaleLevelLike): string {
  if (level.system_code) {
    // Unknown code = bug or unmigrated tenant — surface the key so it's
    // obvious in screenshots and logs instead of silently falling back.
    return SCALE_LEVEL_I18N[level.system_code] ?? level.system_code;
  }
  return level.system_title ?? "";
}
