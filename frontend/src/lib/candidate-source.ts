// HRP-476 (i18n F2): candidate `source` wording.
//
// The list page used to title-case the raw code on the fly
// (`resume_upload` → "Resume Upload") while the create form carried its own
// labelKey list. Both now share this dictionary, so a source reads the same
// everywhere and translators only see one string per code.

export type CandidateSourceCode =
  | "manual"
  | "resume_upload"
  | "job_board"
  | "referral"
  | "agency"
  | "other";

/** Sources offered by the create form and the list filter, in display order. */
export const CANDIDATE_SOURCE_OPTIONS = [
  "manual",
  "resume_upload",
  "job_board",
  "referral",
  "agency",
  "other",
] as const satisfies readonly CandidateSourceCode[];

/** Keys in the `recruitment` i18n namespace. */
const CANDIDATE_SOURCE_KEYS: Record<CandidateSourceCode, string> = {
  manual: "candidateSourceManual",
  resume_upload: "candidateSourceResumeUpload",
  job_board: "candidateSourceJobBoard",
  referral: "candidateSourceReferral",
  agency: "candidateSourceAgency",
  other: "candidateSourceOther",
};

/** i18n key for a known source code, or `null` for anything unexpected. */
export function candidateSourceKey(
  source: string | null | undefined,
): string | null {
  if (!source) return null;
  return CANDIDATE_SOURCE_KEYS[source as CandidateSourceCode] ?? null;
}

/** Translated source label; unknown codes fall back to the pre-i18n
 *  rendering (underscores turned into spaces). */
export function candidateSourceLabel(
  t: (key: string) => string,
  source: string | null | undefined,
): string {
  if (!source) return "";
  const key = candidateSourceKey(source);
  return key ? t(key) : source.replace(/_/g, " ");
}
