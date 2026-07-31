// HRP-479 (i18n F5): localized labels for origin reference data.
//
// Origin/seeded rows carry a stable key (`i18n_key` on dictionary items,
// skill levels and answer scales; `code` on answer options; `system_code`
// on answer-scale levels) and resolve through the `reference` namespace.
// Tenant-authored rows either have no key or a key that is absent from
// the catalog — every helper falls back to the stored text, so custom
// labels render verbatim (in the author's language).
//
// Callers pass the `reference` namespace translator:
//   const tRef = useTranslations("reference");
// The `has()` guard keeps unknown keys from throwing and doubles as the
// origin/custom discriminator, so callers never branch on tenant_id.

// NOTE: this hand-rolled shape only stays assignable from
// useTranslations("reference") because the project declares no typed
// next-intl messages (no IntlMessages augmentation) — keys widen to
// string. If typed messages are ever enabled, revisit this contract.
export interface ReferenceTranslator {
  (key: string): string;
  has(key: string): boolean;
}

function resolve(
  t: ReferenceTranslator,
  key: string,
  fallback: string | null,
): string | null {
  return t.has(key) ? t(key) : fallback;
}

export function dictionaryItemLabel(
  t: ReferenceTranslator,
  item: { type: string; title: string; i18n_key?: string | null },
): string {
  if (!item.i18n_key) return item.title;
  return (
    resolve(t, `dictionary.${item.type}.${item.i18n_key}.label`, item.title) ??
    item.title
  );
}

export function dictionaryItemDescription(
  t: ReferenceTranslator,
  item: { type: string; description: string | null; i18n_key?: string | null },
): string | null {
  if (!item.i18n_key) return item.description;
  return resolve(
    t,
    `dictionary.${item.type}.${item.i18n_key}.description`,
    item.description,
  );
}

export function skillLevelLabel(
  t: ReferenceTranslator,
  level: { title: string; i18n_key?: string | null; tenant_id?: string | null },
): string {
  // Tenant-authored levels render verbatim even when they carry a
  // catalog-colliding key: i18n_key was client-writable before HRP-479
  // closed the schema, so existing rows may be stamped.
  if (level.tenant_id) return level.title;
  if (!level.i18n_key) return level.title;
  return resolve(t, `skillLevel.${level.i18n_key}`, level.title) ?? level.title;
}

// Replaces lib/scale-levels-i18n.ts (the pre-i18n shim). Same contract:
// origin levels carry `system_code` and a NULL `system_title`; an unknown
// code surfaces itself so a missing catalog entry is visible in
// screenshots and logs instead of silently blanking the label.
export function scaleLevelLabel(
  t: ReferenceTranslator,
  level: { system_code: string | null; system_title: string | null },
): string {
  if (level.system_code) {
    return (
      resolve(t, `scaleLevel.${level.system_code}`, level.system_code) ??
      level.system_code
    );
  }
  return level.system_title ?? "";
}

// Answer-option codes are server-generated: semantic codes (na, below, …)
// exist only on the seeded default scale, tenant scales get opt_N/neutral
// — those are absent from the catalog and fall back to the stored title,
// so no origin check is needed. Snapshots copy codes, so finished
// assessments localize the same way.
export function scaleOptionLabel(
  t: ReferenceTranslator,
  option: { code: string; title: string },
): string {
  return resolve(t, `scaleOption.${option.code}.label`, option.title) ?? option.title;
}

export function scaleOptionDescription(
  t: ReferenceTranslator,
  option: { code: string; description: string | null },
): string | null {
  return resolve(t, `scaleOption.${option.code}.description`, option.description);
}

// Denormalized assessment payloads ship code + title pairs. The
// reference.* values mirror the seeded DB titles byte-for-byte (the F2
// keys in the `assessments` namespace use different casing — filters and
// table cells were already inconsistent pre-i18n, so both catalogs stay).
export function assessmentStatusTitle(
  t: ReferenceTranslator,
  a: { status_code: string; status_title: string },
): string {
  return (
    resolve(t, `assessmentStatus.${a.status_code}`, a.status_title) ??
    a.status_title
  );
}

export function assessmentTypeTitle(
  t: ReferenceTranslator,
  a: { type_code: string; type_title: string },
): string {
  return resolve(t, `assessmentType.${a.type_code}`, a.type_title) ?? a.type_title;
}

export function answerScaleLabel(
  t: ReferenceTranslator,
  scale: { title: string; i18n_key?: string | null },
): string {
  if (!scale.i18n_key) return scale.title;
  return resolve(t, `scale.${scale.i18n_key}.label`, scale.title) ?? scale.title;
}

export function answerScaleDescription(
  t: ReferenceTranslator,
  scale: { description: string | null; i18n_key?: string | null },
): string | null {
  if (!scale.i18n_key) return scale.description;
  return resolve(t, `scale.${scale.i18n_key}.description`, scale.description);
}
