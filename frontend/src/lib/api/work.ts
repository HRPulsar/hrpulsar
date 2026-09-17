// HRP-756: the Coverage surface — work containers (a process or a
// project), their steps and the AI decomposition session that drafts them.
// Wire types mirror backend/app/modules/work/schemas.py.
import { api } from "../api";

export type ContainerType = "initiative" | "process";
export type ContainerStatus = "draft" | "active" | "archived";
export type Responsibility = "none" | "reputational" | "formal" | "regulatory";
export type Reversibility = "reversible" | "costly" | "irreversible";
export type OutputType = "draft" | "external_change";
export type StepState = "system_suggested" | "tenant_edited" | "accepted";
export type SessionStatus =
  | "pending"
  | "running"
  | "ready"
  | "error"
  | "applied"
  | "cancelled";

export type Visibility = "company" | "restricted";
/** HRP-810: what the caller may do with a process - manage (the section's
 * roles), edit (the owner), read (everyone else who sees it). */
export type AccessLevel = "manage" | "edit" | "read";
export type RuleRoleCode = "manager" | "recruiter" | "hiring_manager" | "employee";
export const RULE_ROLE_CODES: RuleRoleCode[] = ["manager", "recruiter", "hiring_manager", "employee"];

/** HRP-810: one reason a user reads a restricted process. Exactly one
 * target is set; `label` is a position's title or an employee's name. */
export interface AccessRule {
  role_code: RuleRoleCode | null;
  position_id: string | null;
  employee_id: string | null;
  label?: string | null;
}

export interface AccessLogEntry {
  action: "owner_changed" | "visibility_changed" | "rule_added" | "rule_removed";
  actor_name: string | null;
  payload: Record<string, string | null> | null;
  created_at: string;
}

export interface ContainerAccess {
  visibility: Visibility;
  owner: { user_id: string; name: string; active: boolean } | null;
  rules: AccessRule[];
  history: AccessLogEntry[];
}

/** HRP-810: someone an editor of a process can name - owner, rule or
 * assignee. `assignable` = at work, so a step can be given to them. */
export interface ProcessPerson {
  employee_id: string;
  user_id: string;
  name: string;
  email: string | null;
  position_title: string | null;
  assignable: boolean;
}

export interface WorkContainer {
  id: string;
  tenant_id: string;
  type: ContainerType;
  title: string;
  description: string | null;
  goal: string | null;
  status: ContainerStatus;
  owner_id: string | null;
  created_by_id: string | null;
  source: "manual" | "ai";
  catalog_version: string;
  gap_default_label: "hire" | "agency";
  visibility: Visibility;
  my_access: AccessLevel | null;
  created_at: string;
  updated_at: string;
}

export interface WorkStep {
  id: string;
  container_id: string;
  position: number;
  title: string;
  description: string | null;
  responsibility: Responsibility;
  reversibility: Reversibility | null;
  /** W6: the model's estimate of the step's yearly hours, corrected by the
   * company; null on a hand-typed step and on breakdowns before v2work.v7. */
  hours_per_run: number | null;
  runs_per_year: number | null;
  output_type: OutputType;
  state: StepState;
  gap_label: "hire" | "agency" | null;
  notes: string | null;
  /** HRP-809: who does the step and who checks and signs it. */
  executor_employee_id: string | null;
  accountable_employee_id: string | null;
  primitive_codes: string[];
  capabilities: StepCapability[];
  created_at: string;
  updated_at: string;
}

/** HRP-776: one capability link with the model's case for it. `confidence`
 * is null for a code the company set by hand. */
export interface StepCapability {
  code: string;
  confidence: number | null;
  quote: string | null;
  confirmed: boolean;
}

/** Below this confidence an unconfirmed chip is shown as a suggestion and
 * the step's verdict as preliminary - mirrors coverage.TENTATIVE_BELOW. */
export const TENTATIVE_BELOW = 0.8;

export function isTentative(c: StepCapability): boolean {
  return c.confidence !== null && c.confidence < TENTATIVE_BELOW && !c.confirmed;
}

/** Bounds of the hours estimate - mirror work/models.py and the CHECKs. */
export const HOURS_PER_RUN_MAX = 200;
export const RUNS_PER_YEAR_MAX = 1_000_000;

export type StepPatch = Partial<
  Pick<
    WorkStep,
    | "title"
    | "description"
    | "responsibility"
    | "reversibility"
    | "hours_per_run"
    | "runs_per_year"
    | "output_type"
    | "gap_label"
    | "notes"
    | "executor_employee_id"
    | "accountable_employee_id"
  >
>;

export interface DecompositionStep {
  title: string;
  description?: string | null;
  primitives: string[];
  responsibility: Responsibility;
  output_type: OutputType;
  hours_per_run?: number | null;
  runs_per_year?: number | null;
}

export interface DecompositionSession {
  id: string;
  container_id: string;
  status: SessionStatus;
  /** HRP-775: which of the two LLM calls is in flight while running. */
  phase: "splitting" | "classifying" | null;
  error_code: string | null;
  error_message: string | null;
  payload: { steps: DecompositionStep[] } | null;
  created_at: string;
  finished_at: string | null;
}

/** The capability catalog as `GET /primitives` returns it; the UI shows
 * `reference.primitive.{i18n_key}.label`, never the code. */
export interface Primitive {
  id: string;
  code: string;
  kind: "cognitive" | "boundary";
  i18n_key: string;
  sort_index: number;
}

// HRP-758 / HRP-759: coverage of a breakdown and its gaps. Wire types
// mirror the Coverage* / Gap* / HireNeed* schemas.
export type Verdict = "agent" | "human" | "gap" | "out_of_scope";
export type AutomationMode =
  | "automatable"
  | "draft_then_review"
  | "review_required"
  | "blocked_judgment"
  | "blocked_physical";
export type GapLabel = "hire" | "agency";
/** W6 (§5.3): how well an agent does the step - its weakest capability. */
export type Quality = "no" | "draft" | "strong" | "better_than_human";

export interface CoveragePerson {
  employee_id: string;
  name: string;
  position: string | null;
}

export interface CoverageStep {
  step_id: string;
  position: number;
  title: string;
  state: StepState;
  codes: string[];
  required_codes: string[];
  in_scope: boolean;
  mode: AutomationMode | null;
  /** Null for a step out of scope, which has no cognitive capability. */
  quality: Quality | null;
  verdict: Verdict;
  agent: {
    pack_id: string | null;
    pack_code: string | null;
    agent_id: string | null;
    agent_name: string | null;
  } | null;
  human: CoveragePerson & {
    /** `assigned` (HRP-809): named on the step by the company. */
    label: "assessed" | "expected" | "assigned";
    /** The step's capabilities the person does not hold; only an assigned
     * executor can have any. */
    missing_codes: string[];
  } | null;
  human_backup: boolean;
  /** HRP-809: who checks and signs the step. */
  accountable: CoveragePerson | null;
  /** An agent drafts or needs review here, or somebody answers for the
   * step - and nobody is named to check it. */
  needs_accountable: boolean;
  gap_label: GapLabel | null;
  /** hours_per_run x runs_per_year; null when either is unset. */
  hours_per_year: number | null;
  /** The newest hire need of this step that still points at a vacancy. */
  hire_need: { id: string; vacancy_id: string | null; label: GapLabel } | null;
  skill_status: SkillStatus;
  /** HRP-776: not accepted yet, or resting on an unconfirmed low-confidence code. */
  tentative: boolean;
}

export type SkillStatus = "none" | "generating" | "ready" | "failed";

export interface StepSkill {
  id: string;
  step_id: string;
  pack_id: string | null;
  status: "generating" | "ready" | "failed";
  skill_name: string | null;
  content: string | null;
  error_message: string | null;
  generated_at: string | null;
}

/** Yearly hours of the in-scope steps that carry an estimate, by bucket;
 * `unestimated` counts the in-scope steps without one. */
export interface CoverageHours {
  total: number;
  moves: number;
  to_review: number;
  stays: number;
  unestimated: number;
}

/** How many in-scope steps sit at each quality (§5.3). */
export type CoverageQuality = Record<Quality, number>;

export interface Coverage {
  container_id: string;
  status: ContainerStatus;
  mapping_pending: boolean;
  candidate_step_ids: string[];
  /** Percentages of `hours` by bucket; null on a breakdown shorter than four
   * steps in scope, or while no candidate step carries an estimate. */
  shares: { moves: number; to_review: number; stays: number } | null;
  hours: CoverageHours;
  quality: CoverageQuality;
  /** The tenant's own hourly rate for the ROI in money; null until set. */
  hourly_rate: number | null;
  hourly_rate_currency: string | null;
  steps: CoverageStep[];
}

/** W6 (§5.10): which To do section the row belongs to. */
export type GapKind = "no_owner" | "not_automated_yet";

export interface Gap {
  step_id: string;
  position: number;
  title: string;
  kind: GapKind;
  mode: AutomationMode | null;
  /** Only a `no_owner` row is routed to hiring; the other kind has none. */
  gap_label: GapLabel | null;
  required_codes: string[];
  /** The agent type covering a `not_automated_yet` row, so the screen can
   * register the agent the company already runs for it. */
  agent: {
    pack_id: string | null;
    pack_code: string | null;
    agent_id: string | null;
    agent_name: string | null;
  } | null;
  skill_status: SkillStatus;
  hire_need: { id: string; vacancy_id: string | null; label: GapLabel } | null;
}

export interface HireNeed {
  id: string;
  container_id: string;
  vacancy_id: string | null;
  step_ids: string[];
  label: GapLabel;
  created_at: string;
}

/** 409 on apply: the draft would delete steps with a ready SKILL.md or the
 * company's own edits. `force` applies anyway. */
export const APPLY_WOULD_DISCARD = "work_apply_would_discard";

export const DECOMPOSITION_ACTION = "work_decomposition.start";
export const SKILL_ACTION = "work_skill.generate";
export const RECLASSIFY_ACTION = "work_step.reclassify";
const ACTIVE_SESSION_STATUSES: SessionStatus[] = ["pending", "running"];

export function isSessionRunning(s: DecompositionSession | null): boolean {
  return s !== null && ACTIVE_SESSION_STATUSES.includes(s.status);
}

export const workApi = {
  // ponytail: one page at the API ceiling; add paging when a workspace
  // approaches 200 breakdowns.
  listContainers: (type?: ContainerType) =>
    api.get<{ items: WorkContainer[]; total: number }>(
      `/work/containers?limit=200${type ? `&type=${type}` : ""}`,
    ),
  getContainer: (id: string) => api.get<WorkContainer>(`/work/containers/${id}`),
  createContainer: (body: {
    type: ContainerType;
    title: string;
    description?: string | null;
    goal?: string | null;
  }) => api.post<WorkContainer>("/work/containers", body),
  updateContainer: (
    id: string,
    body: Partial<Pick<WorkContainer, "title" | "description" | "goal">> & {
      status?: "draft" | "archived";
      owner_id?: string | null;
    },
  ) => api.patch<WorkContainer>(`/work/containers/${id}`, body),
  deleteContainer: (id: string) => api.delete<void>(`/work/containers/${id}`),
  accept: (id: string) => api.post<WorkContainer>(`/work/containers/${id}/accept`),
  getAccess: (id: string) => api.get<ContainerAccess>(`/work/containers/${id}/access`),
  listPeople: (id: string) => api.get<ProcessPerson[]>(`/work/containers/${id}/people`),
  setAccess: (id: string, body: { visibility: Visibility; rules: AccessRule[] }) =>
    api.put<ContainerAccess>(`/work/containers/${id}/access`, body),

  listSteps: (containerId: string) =>
    api.get<WorkStep[]>(`/work/containers/${containerId}/steps`),
  createStep: (containerId: string, body: { title: string }) =>
    api.post<WorkStep>(`/work/containers/${containerId}/steps`, body),
  updateStep: (id: string, body: StepPatch) =>
    api.patch<WorkStep>(`/work/steps/${id}`, body),
  deleteStep: (id: string) => api.delete<void>(`/work/steps/${id}`),
  reorderSteps: (containerId: string, stepIds: string[]) =>
    api.put<WorkStep[]>(`/work/containers/${containerId}/steps/order`, {
      step_ids: stepIds,
    }),
  setStepPrimitives: (id: string, codes: string[]) =>
    api.put<WorkStep>(`/work/steps/${id}/primitives`, { codes }),
  // HRP-775: one classification call with the company's comment in
  // context; replaces the step's capabilities, responsibility and output.
  reclassifyStep: (id: string, comment: string) =>
    api.post<WorkStep>(`/work/steps/${id}/reclassify`, { comment }),
  // HRP-776: the company vouches for a code the model was unsure of, or
  // drops one code - the other chips are untouched either way.
  confirmCapability: (id: string, code: string) =>
    api.post<WorkStep>(`/work/steps/${id}/primitives/${encodeURIComponent(code)}/confirm`),
  removeCapability: (id: string, code: string) =>
    api.delete<WorkStep>(`/work/steps/${id}/primitives/${encodeURIComponent(code)}`),

  listPrimitives: () => api.get<Primitive[]>("/primitives"),

  getCoverage: (containerId: string) =>
    api.get<Coverage>(`/work/containers/${containerId}/coverage`),
  listGaps: (containerId: string) => api.get<Gap[]>(`/work/containers/${containerId}/gaps`),
  createHireNeed: (
    containerId: string,
    body: {
      step_ids: string[];
      label: GapLabel;
      /** Search inside the company before the vacancy goes out (§5.9). */
      internal_search_allowed?: boolean;
      title?: string;
      division_id?: string;
    },
  ) => api.post<HireNeed>(`/work/containers/${containerId}/gaps/hire-need`, body),

  generateSkill: (stepId: string) => api.post<StepSkill>(`/work/steps/${stepId}/skill`),
  getSkill: (stepId: string) => api.get<StepSkill>(`/work/steps/${stepId}/skill`),
  downloadSkill: (stepId: string) => api.fetchBlob(`/work/steps/${stepId}/skill/download`),
  // O8-b: "I already use this" registers an agent of the matched pack in
  // the (otherwise headless) AI workforce registry.
  registerAgent: (body: { name: string; pack_id: string }) =>
    api.post<{ id: string }>("/ai-workforce/agents", body),

  startDecomposition: (containerId: string) =>
    api.post<DecompositionSession>("/work/decomposition/sessions", {
      container_id: containerId,
    }),
  latestDecomposition: (containerId: string) =>
    api.get<DecompositionSession | null>(
      `/work/containers/${containerId}/decomposition/latest`,
    ),
  // `force` overrides the 409 the backend answers when the apply would
  // delete a step with a ready SKILL.md or one the company edited.
  applyDecomposition: (sessionId: string, idempotencyKey: string, force = false) =>
    api.post<{ created_steps: string[] }>(
      `/work/decomposition/sessions/${sessionId}/apply${force ? "?force=true" : ""}`,
      { idempotency_key: idempotencyKey },
    ),
  cancelDecomposition: (sessionId: string) =>
    api.delete<DecompositionSession>(`/work/decomposition/sessions/${sessionId}`),
};
