// HRP-181 REDO Stage 4 — canonical recruitment types.
//
// Mirrors backend/app/modules/recruitment/schemas.py shapes used by the
// new candidate flow (FR-04, FR-08, FR-09, FR-17, FR-18, FR-23). Do not
// re-export legacy `Candidate` / `VacancyCandidate` shapes from
// `./types.ts` here — those go away in Stage 5.

export type AiVerdict =
  | "pending"
  | "recommended"
  | "needs_check"
  | "not_recommended";

export type AiReadiness =
  | "none"
  | "resume_only"
  | "resume_and_transcript";

export type StageType =
  | "active"
  | "terminal_positive"
  | "terminal_negative"
  | "terminal_neutral";

export interface VacancyStage {
  id: string;
  tenant_id: string | null;
  vacancy_id: string | null;
  name: string;
  code: string;
  sort_order: number;
  is_terminal: boolean;
  stage_type: StageType;
  color: string | null;
}

export interface VacancyStageReplaceItem {
  id?: string | null;
  name: string;
  code: string;
  sort_order: number;
  stage_type: StageType;
  color: string | null;
}

export interface DivergentCompetencePreview {
  competence_id: string;
  competence_name: string;
  manager_score: number | null;
  ai_score: number | null;
}

export interface CandidateVacancyEnrichedRow {
  id: string;
  candidate_id: string;
  vacancy_id: string;
  candidate_name: string;
  last_position: string | null;
  years_of_experience: number | null;
  stage_id: string | null;
  stage: VacancyStage | null;
  status: string;
  manager_score: number | null;
  ai_score: number | null;
  // HRP-274 — ``ai_score`` rebased onto [0..1] against the tenant's
  // active ScaleConfig. ``null`` when no analysis has completed or the
  // tenant has no scale yet. Drives the candidates-table normalized
  // toggle.
  ai_score_normalized?: number | null;
  score_divergence: boolean;
  // HRP-267 — Compact-matrix aggregates per candidate, tenant-threshold
  // aware. ``manager_percent`` / ``ai_percent`` are 0..100 (or null
  // when nothing has been scored on that side); ``divergence_count`` is
  // the number of cells where |Δ| ≥ tenant divergence_threshold;
  // ``divergence_top`` previews up to 5 of those cells for tooltips.
  manager_percent?: number | null;
  ai_percent?: number | null;
  divergence_count?: number;
  divergence_top?: DivergentCompetencePreview[];
  ai_readiness: AiReadiness;
  ai_verdict: AiVerdict;
  ai_verdict_summary: string | null;
  ai_key_strength: string | null;
  ai_key_risk: string | null;
  ai_risk_mitigation: string | null;
  // HRP-204 — mode of the active AIAnalysisRun. null when no run has
  // completed yet (verdict will be ``pending``).
  ai_analysis_mode?: "resume_only" | "full" | null;
  ai_data_completeness?: string | null;
  version: number;
  added_at: string;
}

export interface CandidateCanonical {
  id: string;
  tenant_id: string;
  full_name: string;
  email: string | null;
  phone: string | null;
  linkedin_url: string | null;
  location: string | null;
  current_position: string | null;
  years_of_experience: number | null;
  source: string | null;
  notes: string | null;
  parsed_resume_jsonb: ParsedResumePayload | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CandidateVacancyApplication {
  cv_id: string;
  vacancy_id: string;
  vacancy_title: string | null;
  stage_id: string | null;
  stage_name: string | null;
  stage_type: StageType | null;
  status: string;
  manager_score: number | null;
  ai_score: number | null;
  ai_verdict: AiVerdict;
  ai_verdict_summary: string | null;
  // HRP-204 — mode of the active AI analysis run; null when nothing
  // has completed yet.
  ai_analysis_mode?: "resume_only" | "full" | null;
  ai_data_completeness?: string | null;
  added_at: string;
}

export interface CandidateFileSummary {
  id: string;
  file_type: string;
  original_filename: string;
  mime_type: string;
  file_size: number;
  parse_status: string;
  created_at: string;
}

export interface CandidateCanonicalCard extends CandidateCanonical {
  vacancy_applications: CandidateVacancyApplication[];
  candidate_files: CandidateFileSummary[];
}

// ---------------------------------------------------------------------------
// Bulk-resume flow shapes — match Stage 3 endpoints exactly.
// ---------------------------------------------------------------------------

export interface BulkResumeAck {
  file_id: string;
  original_filename: string;
  mime_type: string;
  file_size: number;
  parse_status: string;
}

export interface ResumeParseStatusItem {
  file_id: string;
  parse_status: string;
  original_filename: string;
  full_name: string | null;
  email: string | null;
  last_position: string | null;
  error: string | null;
}

export interface ResumeParseStatusResponse {
  counts: Record<string, number>;
  files: ResumeParseStatusItem[];
}

export interface ResumeDedupPreviewItem {
  file_id: string;
  parsed_email: string | null;
  existing_candidate_id: string | null;
  existing_candidate_full_name: string | null;
}

export interface BatchFinalizeFile {
  file_id: string;
  link_candidate_id?: string | null;
}

export interface BatchFinalizeResponse {
  created: Array<{
    file_id: string;
    candidate_id: string;
    candidate_vacancy_id: string;
    full_name: string;
  }>;
  linked: Array<{
    file_id: string;
    candidate_id: string;
    candidate_vacancy_id: string;
    full_name: string;
  }>;
  skipped: Array<{
    file_id: string;
    reason: string;
    existing_candidate_id?: string;
    email?: string;
  }>;
}

export interface ManualCandidatePayload {
  full_name: string;
  email?: string | null;
  phone?: string | null;
  linkedin_url?: string | null;
  location?: string | null;
  current_position?: string | null;
  years_of_experience?: number | null;
  source?: string | null;
  notes?: string | null;
  link_candidate_id?: string | null;
}

export interface ManualCandidateResponse extends CandidateCanonical {
  candidate_vacancy_id: string;
  etag: string;
}

// ---------------------------------------------------------------------------
// Parsed resume payload — shape produced by the Stage 3 LLM extractor.
// Read-only on the candidate card in Stage 4; per-section editing lands
// in Stage 5.
// ---------------------------------------------------------------------------

export interface ParsedResumeExperience {
  /** Canonical job title field emitted by the LLM parser (Stage 3). */
  position?: string | null;
  /** Legacy alias kept for back-compat with pre-Stage 5 payloads. */
  title?: string | null;
  /**
   * Mirror of ``position`` written alongside it by the parser so older
   * consumers (interview prompt builder, indicator-coverage check) keep
   * resolving the role name.
   */
  role?: string | null;
  company?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  description?: string | null;
}

export interface ParsedResumeEducation {
  institution?: string | null;
  degree?: string | null;
  field?: string | null;
  start_date?: string | null;
  end_date?: string | null;
}

export interface ParsedResumeLanguage {
  name?: string | null;
  level?: string | null;
}

export interface ParsedResumeCertificate {
  name?: string | null;
  issuer?: string | null;
  issued_at?: string | null;
}

export interface ParsedResumePayload {
  full_name?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  summary?: string | null;
  current_position?: string | null;
  years_of_experience?: number | null;
  location?: string | null;
  contacts?: {
    email?: string | null;
    phone?: string | null;
    linkedin?: string | null;
    location?: string | null;
  } | null;
  experience?: ParsedResumeExperience[];
  education?: ParsedResumeEducation[];
  skills?: string[];
  languages?: ParsedResumeLanguage[];
  certificates?: ParsedResumeCertificate[];
}

// ---------------------------------------------------------------------------
// Bulk-upload UI limits (mirror backend MAX_BULK_RESUME_FILES /
// MAX_BULK_RESUME_BYTES). Single source of truth so client validation
// matches the server's 413 boundary.
// ---------------------------------------------------------------------------

export const BULK_UPLOAD_MAX_FILES = 50;
export const BULK_UPLOAD_MAX_FILE_BYTES = 10 * 1024 * 1024;
// Single-batch total cap mirrors backend ``MAX_BULK_TOTAL_BYTES``.
export const BULK_UPLOAD_MAX_TOTAL_BYTES = 100 * 1024 * 1024;
export const BULK_UPLOAD_ACCEPT = ".pdf,.docx";
export const BULK_UPLOAD_ALLOWED_MIME = new Set<string>([
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]);

// ---------------------------------------------------------------------------
// HRP-204: resume-only / full / top-up AI analysis runs.
// ---------------------------------------------------------------------------

export type AiAnalysisMode = "resume_only" | "full";

export type AiAnalysisRunStatus =
  | "pending"
  | "processing"
  | "completed"
  | "failed"
  // HRP-270: operator-initiated cancel of an in-flight run.
  | "cancelled";

// HRP-270: pipeline stage taxonomy. Resume-only mode greys
// ``process_findings`` + ``citations`` with a "skipped" reason.
export type AiAnalysisStage =
  | "pre_check"
  | "competences"
  | "blind_spots"
  | "process_findings"
  | "citations"
  | "verdict";

export const AI_ANALYSIS_STAGES: readonly AiAnalysisStage[] = [
  "pre_check",
  "competences",
  "blind_spots",
  "process_findings",
  "citations",
  "verdict",
] as const;

// HRP-476 (i18n F2): the stage wording lives in the `recruitment` i18n
// namespace — this map only owns the stage → key relation, the in-flight
// card resolves it with its own `t` (same shape as `lib/assessment-status.ts`).
export const AI_ANALYSIS_STAGE_LABEL_KEYS: Record<AiAnalysisStage, string> = {
  pre_check: "aiStagePreCheck",
  competences: "aiStageCompetences",
  blind_spots: "aiStageBlindSpots",
  process_findings: "aiStageProcessFindings",
  citations: "aiStageCitations",
  verdict: "aiStageVerdict",
};

/** Translated pipeline-stage label with a raw-code fallback. */
export function aiAnalysisStageLabel(
  t: (key: string) => string,
  stage: string,
): string {
  const key = AI_ANALYSIS_STAGE_LABEL_KEYS[stage as AiAnalysisStage];
  return key ? t(key) : stage;
}

// HRP-271: verbatim resume quote anchored to a parsed-resume section.
// Mirrors backend ``ResumeExcerptRead`` (schemas.py) — keep the section
// union and field names in sync.
export type ResumeExcerptSection =
  | "experience"
  | "education"
  | "skills"
  | "projects"
  | "summary";

export interface ResumeExcerpt {
  section: ResumeExcerptSection;
  excerpt_text: string;
  source_company: string | null;
  source_period: string | null;
}

export interface AiAnalysisRun {
  id: string;
  candidate_vacancy_id: string;
  mode: AiAnalysisMode;
  status: AiAnalysisRunStatus;
  data_completeness: "partial" | "full" | "insufficient" | null;
  interview_id: string | null;
  verdict: string | null;
  verdict_summary: string | null;
  key_strength: string | null;
  key_risk: string | null;
  risk_mitigation: string | null;
  recommendation_for_next_step: string | null;
  ai_score: number | null;
  vacancy_profile_version: number | null;
  archived_at: string | null;
  replaced_by_id: string | null;
  supersedes_id: string | null;
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
  // HRP-270: per-stage progress + cancel bookkeeping.
  current_stage: AiAnalysisStage | null;
  cancelled_at: string | null;
  cancelled_by_id: string | null;
  // HRP-271: backend-extracted resume citations (resume-only mode only;
  // ``null`` for full mode or when no excerpts were produced). The raw
  // ``analysis_data`` payload is intentionally kept server-side so
  // role-filtered fields (red flags, process findings) don't leak.
  resume_excerpts: ResumeExcerpt[] | null;
  // HRP-272: True when the candidate uploaded a fresh resume after this
  // run was enqueued. Resume-only mode only; legacy rows without a
  // stamped snapshot hash and full-mode runs stay False.
  resume_outdated: boolean;
}

// HRP-271: trivial accessor kept for symmetry with the prior shape and
// to centralise the "full-mode runs have no citations" rule.
export function extractResumeExcerpts(run: AiAnalysisRun): ResumeExcerpt[] {
  if (run.mode !== "resume_only") return [];
  return run.resume_excerpts ?? [];
}

export interface TopupEligibility {
  eligible: boolean;
  reason: string | null;
  active_run_id: string | null;
  interview_id: string | null;
  // HRP-269 — id of the latest transcribed interview for this
  // candidate-vacancy pair. Independent of ``eligible`` (which only
  // covers the top-up baseline path) so the candidate-card split-button
  // can offer a direct ``Resume + interview`` run.
  transcribed_interview_id: string | null;
  age_days: number | null;
  window_days: number | null;
  stored_version: number | null;
  current_version: number | null;
}

export interface BulkAnalyzeResponse {
  queued: {
    candidate_vacancy_id: string;
    task_id: string | null;
    run_id: string | null;
    status: string;
  }[];
  failed: {
    candidate_vacancy_id: string;
    error: string;
    status_code: number;
  }[];
}

// Pricing must stay in sync with backend/ee/credits.yaml.
export const AI_ANALYSIS_PRICING = {
  resume_only: 20,
  full: 40,
  topup_to_full: 20,
} as const;
