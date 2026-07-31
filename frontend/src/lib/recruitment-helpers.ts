// HRP-181 REDO Stage 4 — pure helpers shared between recruitment UI
// pieces. Kept dependency-free so vitest can exercise them without a
// jsdom environment.

import {
  BULK_UPLOAD_ALLOWED_MIME,
  BULK_UPLOAD_MAX_FILES,
  BULK_UPLOAD_MAX_FILE_BYTES,
  BULK_UPLOAD_MAX_TOTAL_BYTES,
  type ManualCandidatePayload,
  type ParsedResumeCertificate,
  type ParsedResumeEducation,
  type ParsedResumeExperience,
  type ParsedResumeLanguage,
  type ParsedResumePayload,
  type StageType,
  type VacancyStage,
  type VacancyStageReplaceItem,
} from "./recruitment-types";

interface PickedFileMeta {
  name: string;
  size: number;
  type: string;
}

/** Translator handed in by the calling component — `useTranslations(
 *  "recruitment")`. Kept structural so vitest can pass a stub that echoes
 *  the key back (HRP-476: tests pin keys, not wording). */
export type RecruitmentTranslate = (
  key: string,
  values?: Record<string, string | number>,
) => string;

const MAX_MB = Math.round(BULK_UPLOAD_MAX_FILE_BYTES / (1024 * 1024));
const MAX_TOTAL_MB = Math.round(BULK_UPLOAD_MAX_TOTAL_BYTES / (1024 * 1024));

export function validateBulkUploadSelection(
  t: RecruitmentTranslate,
  files: ReadonlyArray<PickedFileMeta>,
): string | null {
  if (files.length === 0) return t("bulkUploadPickFile");
  if (files.length > BULK_UPLOAD_MAX_FILES) {
    return t("bulkUploadTooManyFiles", { max: BULK_UPLOAD_MAX_FILES });
  }
  let totalBytes = 0;
  for (const f of files) {
    if (f.size > BULK_UPLOAD_MAX_FILE_BYTES) {
      return t("bulkUploadFileTooLarge", { name: f.name, max: MAX_MB });
    }
    totalBytes += f.size;
    if (f.type) {
      if (!BULK_UPLOAD_ALLOWED_MIME.has(f.type)) {
        return t("bulkUploadUnsupportedType", { name: f.name });
      }
    } else if (!/\.(pdf|docx)$/i.test(f.name)) {
      // Empty MIME means the browser couldn't determine the type — fall
      // back to the extension. The backend re-checks magic bytes anyway.
      return t("bulkUploadUnsupportedType", { name: f.name });
    }
  }
  if (totalBytes > BULK_UPLOAD_MAX_TOTAL_BYTES) {
    return t("bulkUploadBatchTooLarge", { max: MAX_TOTAL_MB });
  }
  return null;
}

interface ManualFormInput {
  full_name: string;
  email: string;
  phone: string;
  linkedin_url: string;
  location: string;
  current_position: string;
  years_of_experience: string;
  source: string;
  notes: string;
}

export function buildManualPayload(
  form: ManualFormInput,
  linkCandidateId?: string | null,
): ManualCandidatePayload {
  const yoe = form.years_of_experience.trim();
  const yoeNum = yoe ? Number.parseInt(yoe, 10) : null;
  return {
    full_name: form.full_name.trim(),
    email: form.email.trim() || null,
    phone: form.phone.trim() || null,
    linkedin_url: form.linkedin_url.trim() || null,
    location: form.location.trim() || null,
    current_position: form.current_position.trim() || null,
    years_of_experience:
      yoeNum !== null && Number.isFinite(yoeNum) ? yoeNum : null,
    source: form.source.trim() || null,
    notes: form.notes.trim() || null,
    link_candidate_id: linkCandidateId ?? null,
  };
}

export function manualPayloadValidationError(
  t: RecruitmentTranslate,
  form: ManualFormInput,
): string | null {
  if (!form.full_name.trim()) return t("candidateFullNameRequired");
  if (!form.email.trim() && !form.phone.trim()) {
    return t("candidateContactRequired");
  }
  return null;
}

// ---------------------------------------------------------------------------
// Stages drawer helpers
// ---------------------------------------------------------------------------

export interface StageDraftRow {
  key: string;
  id: string | null;
  name: string;
  code: string;
  color: string;
  stage_type: StageType;
}

export function stageFromServer(stage: VacancyStage): StageDraftRow {
  return {
    key: stage.id,
    id: stage.id,
    name: stage.name,
    code: stage.code,
    color: stage.color ?? "",
    stage_type: stage.stage_type,
  };
}

export function stageFromDefault(
  stage: VacancyStage,
  genKey: () => string,
): StageDraftRow {
  return {
    key: genKey(),
    id: null,
    name: stage.name,
    code: stage.code,
    color: stage.color ?? "",
    stage_type: stage.stage_type,
  };
}

export function buildStagesPayload(
  draft: ReadonlyArray<StageDraftRow>,
): VacancyStageReplaceItem[] {
  return draft.map((s, idx) => ({
    id: s.id,
    name: s.name.trim(),
    code: s.code.trim(),
    sort_order: idx,
    stage_type: s.stage_type,
    color: s.color.trim() || null,
  }));
}

export function stagesValidationError(
  t: RecruitmentTranslate,
  draft: ReadonlyArray<StageDraftRow>,
): string | null {
  if (draft.length === 0) return t("stagesAtLeastOne");
  for (const s of draft) {
    if (!s.name.trim() || !s.code.trim()) {
      return t("stageNameCodeRequired");
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Parsed-resume section editors (HRP-181 REDO Stage 5)
//
// The candidate card lets a recruiter touch up parsed sections without
// re-running the LLM. The backend PATCH endpoint takes the whole
// ``parsed_resume_jsonb`` payload, so each Save replaces one section
// inside a copy of the current payload and ships the result back.
// ---------------------------------------------------------------------------

export type ParsedResumeSectionKey =
  | "summary"
  | "skills"
  | "experience"
  | "education"
  | "languages"
  | "certificates";

type SectionValue<K extends ParsedResumeSectionKey> = K extends "summary"
  ? string | null
  : K extends "skills"
    ? string[]
    : K extends "experience"
      ? ParsedResumeExperience[]
      : K extends "education"
        ? ParsedResumeEducation[]
        : K extends "languages"
          ? ParsedResumeLanguage[]
          : K extends "certificates"
            ? ParsedResumeCertificate[]
            : never;

/** Trim a string field and collapse empty values to ``null`` for the PATCH. */
export function cleanStringField(value: string | null | undefined): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

/** Drop empty trailing items so the saved payload never carries blanks.
 *
 * Stage 5: the LLM parser emits ``position`` (canonical) plus ``role``
 * (back-compat) per experience entry. The recruiter-facing editor mirrors
 * the same value to ``title`` for now so any consumer still reading the
 * legacy alias keeps working. Emit all three keys on save.
 */
function pruneExperience(items: ParsedResumeExperience[]): ParsedResumeExperience[] {
  return items
    .map((e) => {
      const position = cleanStringField(e.position ?? e.title ?? e.role);
      return {
        position,
        role: position,
        title: position,
        company: cleanStringField(e.company),
        start_date: cleanStringField(e.start_date),
        end_date: cleanStringField(e.end_date),
        description: cleanStringField(e.description),
      };
    })
    .filter(
      (e) =>
        e.position ||
        e.company ||
        e.start_date ||
        e.end_date ||
        e.description,
    );
}

function pruneEducation(items: ParsedResumeEducation[]): ParsedResumeEducation[] {
  return items
    .map((e) => ({
      institution: cleanStringField(e.institution),
      degree: cleanStringField(e.degree),
      field: cleanStringField(e.field),
      start_date: cleanStringField(e.start_date),
      end_date: cleanStringField(e.end_date),
    }))
    .filter(
      (e) =>
        e.institution ||
        e.degree ||
        e.field ||
        e.start_date ||
        e.end_date,
    );
}

function pruneLanguages(items: ParsedResumeLanguage[]): ParsedResumeLanguage[] {
  return items
    .map((l) => ({
      name: cleanStringField(l.name),
      level: cleanStringField(l.level),
    }))
    .filter((l) => l.name || l.level);
}

function pruneCertificates(
  items: ParsedResumeCertificate[],
): ParsedResumeCertificate[] {
  return items
    .map((c) => ({
      name: cleanStringField(c.name),
      issuer: cleanStringField(c.issuer),
      issued_at: cleanStringField(c.issued_at),
    }))
    .filter((c) => c.name || c.issuer || c.issued_at);
}

function pruneSkills(items: string[]): string[] {
  const cleaned = items
    .map((s) => (typeof s === "string" ? s.trim() : ""))
    .filter((s) => s.length > 0);
  // Dedupe while preserving order — recruiters can paste a chip list and
  // we should not turn a single typo into two near-duplicate entries.
  return Array.from(new Set(cleaned));
}

/**
 * Produce a new ``parsed_resume_jsonb`` payload with one section
 * replaced by the supplied value. The previous payload is treated as
 * read-only; the function returns a shallow copy so the caller can drop
 * the result straight into ``PATCH /candidates/{id}`` without worrying
 * about state aliasing.
 */
export function updateParsedResumeSection<K extends ParsedResumeSectionKey>(
  payload: ParsedResumePayload | null | undefined,
  section: K,
  value: SectionValue<K>,
): ParsedResumePayload {
  const base: ParsedResumePayload = payload ? { ...payload } : {};
  switch (section) {
    case "summary":
      base.summary = cleanStringField(value as string | null);
      break;
    case "skills":
      base.skills = pruneSkills(value as string[]);
      break;
    case "experience":
      base.experience = pruneExperience(value as ParsedResumeExperience[]);
      break;
    case "education":
      base.education = pruneEducation(value as ParsedResumeEducation[]);
      break;
    case "languages":
      base.languages = pruneLanguages(value as ParsedResumeLanguage[]);
      break;
    case "certificates":
      base.certificates = pruneCertificates(value as ParsedResumeCertificate[]);
      break;
  }
  return base;
}

export const emptyExperience: () => ParsedResumeExperience = () => ({
  position: "",
  role: "",
  title: "",
  company: "",
  start_date: "",
  end_date: "",
  description: "",
});

export const emptyEducation: () => ParsedResumeEducation = () => ({
  institution: "",
  degree: "",
  field: "",
  start_date: "",
  end_date: "",
});

export const emptyLanguage: () => ParsedResumeLanguage = () => ({
  name: "",
  level: "",
});

export const emptyCertificate: () => ParsedResumeCertificate = () => ({
  name: "",
  issuer: "",
  issued_at: "",
});
