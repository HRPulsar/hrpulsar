import { api } from "../api";

export type SessionScope =
  | "whole_base"
  | "group"
  | "competence_indicators"
  | "specialization_matrix";
export type SessionStatus =
  | "pending"
  | "running"
  | "ready"
  | "error"
  | "applied"
  | "cancelled";

export interface SessionParams {
  with_indicators?: boolean;
  refinement_prompt?: string | null;
  /** HRP-97: structured snapshot of the refinement form so the UI can
   * re-hydrate the panel on reopen. `null` (or missing keys) means the
   * field was empty. */
  refinement_form?: {
    general?: string | null;
    add?: string | null;
    change?: string | null;
    exclude?: string | null;
  } | null;
  /** HRP-102: when an indicator-generation session is launched from a
   * specialization-matrix cell we carry the source spec id so the prompt
   * can see grades and sibling competences. */
  specialization_id?: string | null;
  /** HRP-123: preflight modal lets the user drop categories from the prompt
   * context. Recognised: "specializations", "divisions", "company". */
  context_excludes?: string[];
  /** HRP-33: matrix sessions launched from a Position page carry the position
   * id so the global banner and list views can route back to the position.
   * Standalone matrix sessions (launched from the specialization page) leave
   * this null. */
  position_id?: string | null;
  /** HRP-33: title of the position the session was launched for — used so
   * list views and the AI-generate page can show "Generating matrix for
   * position 'X'" without hitting the positions endpoint. */
  position_title?: string | null;
}

export interface GeneratedIndicator {
  temp_id?: string;
  title: string;
  skill_level: string;
  snapshot_id?: string | null;
}

export interface GeneratedCompetence {
  temp_id?: string;
  title: string;
  description?: string | null;
  type?: "hard_skill" | "soft_skill" | "unique_skill";
  indicators?: GeneratedIndicator[];
  /** specialization_matrix scope: grade title → skill_level title. */
  grade_levels?: Record<string, string>;
  snapshot_id?: string | null;
}

export interface GeneratedGroup {
  temp_id?: string;
  title: string;
  description?: string | null;
  children?: GeneratedGroup[];
  competences?: GeneratedCompetence[];
  snapshot_id?: string | null;
}

export interface GeneratedTreePayload {
  groups?: GeneratedGroup[];
  indicators?: GeneratedIndicator[];
}

export interface ExistingTreeIndicator {
  id: string;
  title: string;
  skill_level?: string | null;
  skill_level_id?: string | null;
}

export interface ExistingTreeCompetence {
  id: string;
  title: string;
  description?: string | null;
  indicators?: ExistingTreeIndicator[];
}

export interface ExistingTreeGroup {
  id: string;
  title: string;
  description?: string | null;
  children?: ExistingTreeGroup[];
  competences?: ExistingTreeCompetence[];
  /** Only present on the root snapshot block (group scope). */
  ancestors?: { id: string; title: string }[];
  /** Only present on the root snapshot block (group scope). */
  descendants?: ExistingTreeGroup[];
}

export interface CompetenceGenerationSession {
  id: string;
  tenant_id: string;
  user_id: string;
  scope: SessionScope;
  target_id: string | null;
  params: SessionParams;
  payload: GeneratedTreePayload | null;
  selection_state: Record<string, boolean>;
  status: SessionStatus;
  error_code: string | null;
  error_message: string | null;
  parent_session_id: string | null;
  prompt_version: string;
  llm_model: string | null;
  tokens_used: number | null;
  cost_credits: number | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  /** HRP-114 re-spec: tree of pre-existing subgroups/competences/indicators
   * the result preview renders read-only next to the generated suggestions.
   * `null` when the scope has no notion of an existing tree (matrix). */
  existing_tree?: ExistingTreeGroup[] | null;
  /** HRP-114 re-spec: existing indicators of the target competence,
   * read-only next to the generated ones (indicators scope only). */
  existing_indicators?: ExistingTreeIndicator[] | null;
}

export interface OtherActiveSession {
  session_id: string;
  user_id: string;
  user_full_name: string;
  scope: SessionScope;
  target_id: string | null;
  status: SessionStatus;
  created_at: string;
}

export interface SessionHistorySummary {
  refinement_prompt: string | null;
  position_title: string | null;
  file_count: number;
  with_indicators: boolean;
}

export interface SessionHistoryCounts {
  grades: number;
  competences: number;
  indicators: number;
  accepted: number;
  rejected: number;
}

export interface SessionHistoryItem {
  id: string;
  user_id: string;
  user_full_name: string;
  scope: SessionScope;
  target_id: string | null;
  status: SessionStatus;
  error_code: string | null;
  error_message: string | null;
  parent_session_id: string | null;
  prompt_version: string;
  llm_model: string | null;
  cost_credits: number | null;
  summary: SessionHistorySummary;
  counts: SessionHistoryCounts;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

export interface SessionHistoryListParams {
  target_id?: string;
  scope?: SessionScope;
  limit?: number;
  offset?: number;
}

export interface ApplyResult {
  created_groups: string[];
  created_competences: string[];
  created_indicators: string[];
  created_grade_links: string[];
  idempotency_key: string;
}

export interface RefinementInput {
  general?: string;
  add?: string;
  change?: string;
  exclude?: string;
}

const BASE = "/competence-generation/sessions";

export const competenceGenerationApi = {
  create(input: {
    scope: SessionScope;
    target_id?: string | null;
    params?: SessionParams;
  }) {
    return api.post<CompetenceGenerationSession>(BASE, {
      scope: input.scope,
      target_id: input.target_id ?? null,
      params: input.params ?? {},
    });
  },

  getActive() {
    return api.get<CompetenceGenerationSession | null>(`${BASE}/active`);
  },

  list(params: SessionHistoryListParams = {}) {
    const qs = new URLSearchParams();
    if (params.target_id) qs.set("target_id", params.target_id);
    if (params.scope) qs.set("scope", params.scope);
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    if (params.offset !== undefined) qs.set("offset", String(params.offset));
    const suffix = qs.toString();
    return api.get<SessionHistoryItem[]>(suffix ? `${BASE}?${suffix}` : BASE);
  },

  getActiveOthers() {
    return api.get<OtherActiveSession[]>(`${BASE}/active-others`);
  },

  get(sessionId: string) {
    return api.get<CompetenceGenerationSession>(`${BASE}/${sessionId}`);
  },

  cancel(sessionId: string) {
    return api.delete<CompetenceGenerationSession>(`${BASE}/${sessionId}`);
  },

  clear(sessionId: string) {
    return api.post<CompetenceGenerationSession>(`${BASE}/${sessionId}/clear`);
  },

  refine(sessionId: string, input: RefinementInput) {
    return api.post<CompetenceGenerationSession>(`${BASE}/${sessionId}/refine`, {
      general: input.general ?? null,
      add: input.add ?? null,
      change: input.change ?? null,
      exclude: input.exclude ?? null,
    });
  },

  regenerate(sessionId: string) {
    return api.post<CompetenceGenerationSession>(
      `${BASE}/${sessionId}/regenerate`,
    );
  },

  apply(sessionId: string, body: { publish: boolean; idempotency_key: string }) {
    return api.post<ApplyResult>(`${BASE}/${sessionId}/apply`, body);
  },

  updateSelection(
    sessionId: string,
    body: { node_id: string; selected: boolean },
  ) {
    return api.patch<CompetenceGenerationSession>(
      `${BASE}/${sessionId}/selection`,
      body,
    );
  },

  /** HRP-143: tenant data the preflight modal renders as per-item chips
   * (specializations / divisions / company description / source tree). */
  contextOptions(scope: SessionScope, targetId: string | null = null) {
    const qs = new URLSearchParams({ scope });
    if (targetId) qs.set("target_id", targetId);
    return api.get<ContextOptions>(
      `/competence-generation/context-options?${qs.toString()}`,
    );
  },
};

export interface ContextOptionItem {
  id: string;
  title?: string;
  name?: string;
}

export interface ContextSourceTreeNode {
  id: string;
  title: string;
  description?: string | null;
  children?: ContextSourceTreeNode[];
  competences?: { id: string; title: string }[];
}

export interface ContextOptions {
  /** HRP-114 re-spec: `is_linked` is populated for `group` / `competence_indicators`
   * scope (true when the spec backs one of the scope's competences). For
   * `whole_base` / `specialization_matrix` it stays undefined. */
  specializations: { id: string; title: string; is_linked?: boolean }[];
  /** HRP-114 re-spec: `is_linked` mirrors `specializations` — true when one
   * of the linked specs has an active position in this division. */
  divisions: { id: string; name: string; is_linked?: boolean }[];
  company_description: string | null;
  source_tree: ContextSourceTreeNode[];
  /** HRP-114: subset of tenant specs linked via matrix to a competence
   * in the target group / target competence. Empty for whole_base. */
  related_specializations?: { id: string; title: string }[];
  /** HRP-114: chain of parent groups in root → leaf order (group scope). */
  ancestors?: { id: string; title: string }[];
  /** HRP-114: descendant groups + their competences (group scope). */
  descendants?: ContextSourceTreeNode[];
  /** HRP-114: other competences in the same group as the target
   * competence (indicators scope). */
  sibling_competences?: { id: string; title: string }[];
  /** HRP-159: positions linked to the target specialization
   * (specialization_matrix scope). */
  positions?: { id: string; title: string; description: string | null }[];
  /** HRP-159: tenant divisions with a `related` flag set when any of the
   * specialization's positions live in that division (pre-checked by
   * default in the preflight modal). */
  matrix_divisions?: { id: string; name: string; related: boolean }[];
  /** HRP-159: competences already present in the target specialization's
   * matrix (specialization_matrix scope). */
  existing_competences?: { id: string; title: string; description: string }[];
  /** HRP-159: text description of the target specialization. */
  specialization_description?: string | null;
}

/** HRP-71 phase 3: per-suggestion title override applied at materialisation. */
export interface SuggestionEdit {
  title: string;
}
