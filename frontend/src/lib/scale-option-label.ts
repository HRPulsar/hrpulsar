// Suffix in parentheses for an answer option, e.g. "(3)" or "(not counted)".
//
// Two display contexts:
//   - Admin view: weights are visible — a non-neutral option renders as
//     "{title} ({weight})".
//   - Participant view (`showScore: false`): weights are hidden — only the
//     neutral option keeps a suffix to flag that picking it is harmless.
//
// Neutral options always render "(not counted)" regardless of context, so an
// `is_neutral` option with NULL weight no longer leaks an empty "()".
//
// HRP-476: the neutral suffix is translated — callers pass the `assessments`
// namespace translator (weights stay numeric and locale-independent).

interface ScaleOptionLike {
  is_neutral: boolean;
  weight: number | null;
}

export function scaleOptionSuffix(
  t: (key: string) => string,
  opt: ScaleOptionLike,
  { showScore }: { showScore: boolean } = { showScore: true },
): string | null {
  if (opt.is_neutral) return t("scaleOptionNotCounted");
  if (!showScore) return null;
  if (opt.weight === null || opt.weight === undefined) return null;
  return `(${opt.weight})`;
}