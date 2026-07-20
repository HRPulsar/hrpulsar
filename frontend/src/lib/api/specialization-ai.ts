import { api } from "../api";
import type {
  ApplyResult,
  CompetenceGenerationSession,
  SuggestionEdit,
} from "./competence-generation";

export interface MatrixGenerateInput {
  target_id?: string;
  /** HRP-33: launches the matrix flow scoped to a Position. The backend
   *  resolves `target_id` from `position.specialization_id` when omitted
   *  and folds generated competences into a single group named after the
   *  position on apply. */
  position_id?: string;
  /** HRP-57 P2/P4: grades the user picked in the brief. The backend
   *  pre-creates Spec×Grade pairs idempotently so AI can generate
   *  matrix + grades atomically against an otherwise empty
   *  specialization. */
  grade_ids?: string[];
  responsibilities?: string;
  daily_tasks?: string;
  weekly_tasks?: string;
  kpi?: string;
  requirements_text?: string;
  /** HRP-119 AC2: ask the LLM to extend every existing competence in the
   * matrix with extra indicators. Only meaningful when the spec already
   * has competences; the worker ignores the flag for an empty matrix. */
  indicators_for_existing?: boolean;
  /** HRP-159: preflight context. Each entry is either a category-wide
   *  toggle (`positions`, `divisions`, `company`, `existing_competences`,
   *  `specialization_description`) or a per-item key
   *  (`position:<uuid>`, `division:<uuid>`, `competence:<uuid>`). Empty
   *  list = use everything available. */
  context_excludes?: string[];
  /** HRP-159: free-form refinement note appended to the prompt. */
  refinement_prompt?: string;
  files: File[];
}

const BASE = "/competence-generation";

function buildMatrixForm(input: MatrixGenerateInput): FormData {
  const fd = new FormData();
  if (input.target_id) fd.append("target_id", input.target_id);
  if (input.position_id) fd.append("position_id", input.position_id);
  if (input.grade_ids && input.grade_ids.length > 0) {
    // Backend expects a JSON-encoded list — keeps the multipart form flat
    // (one field) and avoids tripping over FastAPI's `Form(List[UUID])`
    // edge cases on repeated fields.
    fd.append("grade_ids", JSON.stringify(input.grade_ids));
  }
  if (input.responsibilities) fd.append("responsibilities", input.responsibilities);
  if (input.daily_tasks) fd.append("daily_tasks", input.daily_tasks);
  if (input.weekly_tasks) fd.append("weekly_tasks", input.weekly_tasks);
  if (input.kpi) fd.append("kpi", input.kpi);
  if (input.requirements_text)
    fd.append("requirements_text", input.requirements_text);
  if (input.indicators_for_existing) {
    fd.append("indicators_for_existing", "true");
  }
  if (input.context_excludes && input.context_excludes.length > 0) {
    fd.append("context_excludes", JSON.stringify(input.context_excludes));
  }
  if (input.refinement_prompt && input.refinement_prompt.trim().length > 0) {
    fd.append("refinement_prompt", input.refinement_prompt);
  }
  for (const file of input.files) {
    fd.append("files", file);
  }
  return fd;
}

export const specializationAiApi = {
  start: (input: MatrixGenerateInput) =>
    api.postForm<CompetenceGenerationSession>(
      `${BASE}/specialization-matrix-sessions`,
      buildMatrixForm(input),
    ),
  get: (sessionId: string) =>
    api.get<CompetenceGenerationSession>(`${BASE}/sessions/${sessionId}`),
  refine: (sessionId: string, body: { general?: string; add?: string; change?: string; exclude?: string }) =>
    api.post<CompetenceGenerationSession>(`${BASE}/sessions/${sessionId}/refine`, {
      general: body.general ?? null,
      add: body.add ?? null,
      change: body.change ?? null,
      exclude: body.exclude ?? null,
    }),
  regenerate: (sessionId: string) =>
    api.post<CompetenceGenerationSession>(
      `${BASE}/sessions/${sessionId}/regenerate`,
    ),
  apply: (sessionId: string, body: { publish: boolean; idempotency_key: string }) =>
    api.post<ApplyResult>(`${BASE}/sessions/${sessionId}/apply`, body),
  cancel: (sessionId: string) =>
    api.delete<CompetenceGenerationSession>(`${BASE}/sessions/${sessionId}`),
  updateSelection: (
    sessionId: string,
    body: { node_id: string; selected: boolean },
  ) =>
    api.patch<CompetenceGenerationSession>(
      `${BASE}/sessions/${sessionId}/selection`,
      body,
    ),
  replaceSelection: (
    sessionId: string,
    selection_state: Record<string, boolean>,
    edits: Record<string, SuggestionEdit> = {},
  ) =>
    api.put<CompetenceGenerationSession>(
      `${BASE}/sessions/${sessionId}/selection-state`,
      { selection_state, edits },
    ),
};
