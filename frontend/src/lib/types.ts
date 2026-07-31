export interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  tenant_id: string;
  created_at: string;
  roles: string[];
  is_platform_admin?: boolean;
  avatar_url?: string | null;
  deployment_mode?: "onprem" | "saas";
  /** Demo session: only true for sandbox tenants minted by /api/demo/start. */
  tenant_is_demo?: boolean;
  /** ISO timestamp at which the demo tenant + its data are purged. */
  tenant_expires_at?: string | null;
  /** i18n (F0): personal interface locale; null → tenant/deployment default. */
  language?: string | null;
  /** Tenant-default interface locale, echoed by /auth/me. */
  tenant_default_locale?: string | null;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  redirect_to?: string;
}

export interface RegisterResponse extends TokenResponse {
  user: User;
}

export interface PendingVerificationResponse {
  pending_verification: boolean;
  email: string;
  // HRP-390: self-hosted installs without an email provider verify the
  // account at registration time — the UI can log the user straight in.
  auto_verified?: boolean;
}

export interface VerifyEmailResponse {
  user: User;
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  onboarding_completed: boolean;
  created_at: string;
}

export interface TenantInfo {
  id: string;
  name: string;
  slug: string;
  roles: string[];
}

export interface TenantSelectionRequired {
  requires_tenant_selection: true;
  tenants: TenantInfo[];
}

export interface PendingRoleDowngrade {
  employee_id: string;
  user_id: string;
  current_role: string;
  user_name: string | null;
  // HRP-196: backend now auto-downgrades the previous manager when they
  // lose their last division. `downgraded=true` means the role was
  // already stripped server-side; the UI just shows a toast.
  downgraded?: boolean;
}

export interface RoleUpgrade {
  // HRP-196: backend reports newly promoted managers so the division
  // edit dialog can confirm the role change with a toast.
  employee_id: string;
  user_id: string;
  new_role: string;
  user_name: string | null;
}

export interface Division {
  id: string;
  name: string;
  description: string | null;
  parent_id: string | null;
  manager_id: string | null;
  manager_name: string | null;
  deputy_manager_id: string | null;
  deputy_manager_name: string | null;
  tenant_id: string;
  created_at: string;
  children: Division[];
  pending_role_downgrade?: PendingRoleDowngrade[];
  role_upgrades?: RoleUpgrade[];
}

// GF7: Specialization-Division mapping
export interface SpecializationDivision {
  id: string;
  division_id: string;
  specialization_id: string;
  specialization_title: string | null;
  tenant_id: string;
  created_at: string;
}

export type PositionLifecycleStatus =
  | "active"
  | "on_hold"
  | "frozen"
  | "closed";

export interface Position {
  id: string;
  tenant_id: string;
  title: string;
  description: string | null;
  specialization_id: string | null;
  specialization_title: string | null;
  grade_id: string | null;
  grade_title: string | null;
  division_id: string | null;
  division_name: string | null;
  headcount: number | null;
  is_active: boolean;
  lifecycle_status: PositionLifecycleStatus;
  source: "manual" | "ai_draft" | "ai_approved";
  employee_count: number;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  vacancy_count: number | null;
  matrix_configured: boolean;
  created_at: string;
}

export interface PositionList {
  items: Position[];
  total: number;
}

export interface PositionMatrixIndicator {
  id: string;
  title: string;
  weight: number;
  sort_index: number;
  skill_level_id: string;
  skill_level_title: string | null;
}

export interface PositionMatrixCompetence {
  competence_id: string;
  title: string;
  description: string | null;
  group_id: string;
  group_title: string | null;
  skill_level_id: string;
  skill_level_title: string | null;
  indicators: PositionMatrixIndicator[];
}

export interface PositionMatrix {
  configured: boolean;
  specialization_id: string | null;
  grade_id: string | null;
  grade_specialization_id: string | null;
  competences: PositionMatrixCompetence[];
}

export type EmployeeAlertCode =
  | "user_inactive"
  | "profile_incomplete"
  | "assessment_overdue"
  | "assessment_pending"
  | "pdp_pending_review";

export interface EmployeeAlert {
  code: EmployeeAlertCode;
  label: string;
}

export interface Employee {
  id: string;
  user_id: string;
  division_id: string | null;
  position_id: string | null;
  position_title: string | null;
  specialization_id: string | null;
  specialization_title: string | null;
  grade_id: string | null;
  grade_title: string | null;
  hire_date: string;
  status: string;
  // HRP-246: stamped on every ``status`` mutation; nullable for rows
  // that pre-date the migration.
  status_changed_at?: string | null;
  tenant_id: string;
  created_at: string;
  user_email: string | null;
  user_name: string | null;
  // HRP-246: stamped on first successful auth; nullable for users who
  // have never logged in.
  user_first_login_at?: string | null;
  division_name: string | null;
  avatar_url?: string | null;
  alert?: EmployeeAlert | null;
}

export interface EmployeeList {
  items: Employee[];
  total: number;
}

export interface EmployeeEvent {
  id: string;
  employee_id: string;
  event_type: string;
  description: string | null;
  event_date: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

// GF1: Work Experience & Previous Employment

export interface CompetenceRef {
  id: string;
  title: string;
}

export interface WorkExperience {
  id: string;
  employee_id: string;
  division_id: string | null;
  position_id: string | null;
  division_name: string | null;
  position_title: string | null;
  title: string | null;
  role: string | null;
  description: string | null;
  start_date: string;
  end_date: string | null;
  duration: string | null;
  competences: CompetenceRef[];
  created_at: string;
}

export interface PreviousEmployment {
  id: string;
  employee_id: string;
  company_name: string;
  position: string;
  description: string | null;
  start_date: string;
  end_date: string | null;
  created_at: string;
}

// HRP-153: Employee competence overview

export interface EmployeeCompetenceLevelBreakdown {
  skill_level_id: string;
  skill_level_title: string;
  skill_level_sort_index: number;
  percent: number;
}

export interface EmployeeCompetenceRow {
  competence_id: string;
  competence_title: string;
  group_id: string | null;
  skill_level_id: string;
  skill_level_title: string;
  skill_level_sort_index: number;
  percent: number | null;
  assessment_id: string | null;
  completed_at: string | null;
  level_breakdown: EmployeeCompetenceLevelBreakdown[];
}

export interface EmployeeCompetenceOverview {
  current_position: EmployeeCompetenceRow[];
  other: EmployeeCompetenceRow[];
}

// GF2: Education & Courses

export interface Education {
  id: string;
  employee_id: string;
  institution: string;
  degree: string;
  field_of_study: string;
  start_date: string;
  end_date: string | null;
  created_at: string;
}

export interface Course {
  id: string;
  employee_id: string;
  title: string;
  provider: string | null;
  certificate_url: string | null;
  completed_date: string | null;
  expiry_date: string | null;
  competences: CompetenceRef[];
  created_at: string;
}

// GF5: Compensation

export interface Compensation {
  id: string;
  employee_id: string;
  type: string;
  amount: number;
  currency: string;
  effective_date: string;
  end_date: string | null;
  notes: string | null;
  created_at: string;
}

// GF3: Invitations

export interface Invitation {
  id: string;
  email: string;
  name: string;
  role_code: string;
  invited_by: string;
  inviter_name: string | null;
  division_id: string | null;
  division_name: string | null;
  position_id: string | null;
  position_title: string | null;
  status: string;
  expires_at: string;
  accepted_at: string | null;
  created_at: string;
}

export interface InvitationList {
  items: Invitation[];
  total: number;
}

export interface InvitationUpdate {
  role_code?: string;
  division_id?: string | null;
  position_id?: string | null;
}

export interface InvitationEmailUpdate {
  email: string;
}

export interface Role {
  id: string;
  name: string;
  code: string;
  description: string | null;
  is_system: boolean;
  tenant_id: string | null;
  permissions: string[];
}

export interface DictionaryItem {
  id: string;
  type: string;
  title: string;
  description: string | null;
  // HRP-479: set on origin rows only; render via reference.dictionary.*
  // with the stored title as fallback (see lib/reference-labels.ts).
  i18n_key: string | null;
  is_active: boolean;
  sort_index: number;
  tenant_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface CompetenceGroup {
  id: string;
  title: string;
  description: string | null;
  parent_id: string | null;
  tenant_id: string | null;
  sort_index: number;
  is_active: boolean;
  can_deactivate: boolean;
  is_root_origin: boolean;
  created_at: string;
}

export interface CompetenceGroupTree extends CompetenceGroup {
  children: CompetenceGroupTree[];
  competences: Competence[];
  competences_count: number;
  // HRP-118: backend rollup — true when any descendant competence is
  // referenced by matrices / IDPs / employee cards / assessments.
  is_used: boolean;
}

export interface CompetenceLevelsCompletion {
  // Backend (`_levels_completion_map`) returns one entry per competence,
  // each carrying two flags rolled up across the expected skill levels.
  has_uncovered_indicators: boolean;
  has_uncovered_materials: boolean;
}

export interface Competence {
  id: string;
  title: string;
  description: string | null;
  group_id: string;
  competence_type_id: string | null;
  tenant_id: string | null;
  is_active: boolean;
  is_published: boolean;
  is_origin: boolean;
  is_used: boolean;
  levels_completion: CompetenceLevelsCompletion | null;
  created_at: string;
}

export interface Indicator {
  id: string;
  title: string;
  weight: number;
  sort_index: number;
  skill_level_id: string;
  skill_level_title: string | null;
  competence_id: string;
  is_active: boolean;
  tenant_id: string | null;
  created_at: string;
}

export interface Material {
  id: string;
  title: string;
  format: string | null;
  link: string | null;
  study_time: number | null;
  comment: string | null;
  material_type: string | null;
  sort_index: number;
  skill_level_id: string;
  skill_level_title: string | null;
  competence_id: string;
  is_active: boolean;
  tenant_id: string | null;
  created_at: string;
}

export interface CompetenceDetail extends Competence {
  indicators: Indicator[];
  materials: Material[];
}

export interface MaterialInContext extends Material {
  source: "base" | "added";
}

export interface MaterialOverride {
  id: string;
  tenant_id: string;
  material_id: string;
  specialization_id: string;
  mode: "hide" | "add";
  created_at: string;
}

export interface CompetenceUsage {
  matrix: boolean;
  employee_card: boolean;
  assessment: boolean;
  idp: boolean;
  talent_market: boolean;
  is_used: boolean;
}

export interface Assessment {
  id: string;
  title: string | null;
  employee_id: string;
  employee_name: string;
  // HRP-333: EmployeeSummaryLine inputs for the assessee.
  employee_position_title?: string | null;
  employee_status?: string | null;
  type_code: string;
  type_title: string;
  status_code: string;
  status_title: string;
  group_id: string | null;
  passing_score: number | null;
  created_at: string;
  // HRP-161: stamped on transitions to ``done`` and ``cancelled``. The
  // detail page surfaces this in place of the deadline once the assessment
  // is in a terminal status.
  finished_at: string | null;
  // HRP-185: true while a reviewer is editing per-indicator Totals.
  calibration_in_progress?: boolean;
  // HRP-329: true once a calibration was saved — the questionnaire is
  // closed for good (the server rejects submissions with 409).
  has_calibrated_totals?: boolean;
}

export interface AssessmentList {
  items: Assessment[];
  total: number;
}

export interface AssessmentGroup {
  id: string;
  title: string;
  initiator_id: string;
  assessment_count: number;
  status_summary: Record<string, number>;
  type_code: string | null;
  type_title: string | null;
  created_at: string;
}

export interface AssessmentCompetence {
  competence_id: string;
  competence_title: string;
  skill_level_id: string | null;
  skill_level_title: string | null;
  // HRP-479: origin levels localize via reference.skillLevel.*.
  skill_level_i18n_key?: string | null;
}

export type CriteriaType = "current_positions" | "target_position" | "competences";

export interface CriteriaUpdate {
  criteria_type: CriteriaType;
  specialization_id?: string | null;
  grade_id?: string | null;
  competences?: AssessmentCompetence[];
  passing_score?: number | null;
}

// HRP-479: options are dictionary rows; origin ones carry i18n_key and
// localize via reference.dictionary.* (dictionaryItemLabel).
export interface SpecializationOption {
  id: string;
  title: string;
  // Optional: legacy saved values are injected client-side without it.
  i18n_key?: string | null;
}

export interface GradeOption {
  id: string;
  title: string;
  i18n_key?: string | null;
}

export interface SkillLevel {
  id: string;
  title: string;
  sort_index: number;
  i18n_key: string | null;
  is_active: boolean;
  tenant_id: string | null;
}

export interface AssessmentGroupDetail extends AssessmentGroup {
  assessments: Assessment[];
  criteria_type: CriteriaType | null;
  specialization_id: string | null;
  specialization_title: string | null;
  specialization_i18n_key?: string | null;
  grade_id: string | null;
  grade_title: string | null;
  grade_i18n_key?: string | null;
  passing_score: number | null;
  competences: AssessmentCompetence[];
  scale_id: string | null;
  scale: AnswerScaleDetail | null;
  // HRP-37: present only on POST /assessment-groups when the per-employee
  // cap caused a partial creation; absent for plain reads.
  created_count?: number;
  requested_count?: number;
  skipped_capped_count?: number;
}

export interface GradeRecommendationItem {
  grade_id: string;
  grade_title: string | null;
  sort_index: number;
  percent: number;
  passed: boolean;
  missing_percent: number | null;
  excluded: boolean;
}

export interface AssessmentRecommendation {
  passing_score: number | null;
  recommended_grade_id: string | null;
  recommended_grade_title: string | null;
  recommended_grade_passed: boolean;
  grades: GradeRecommendationItem[];
  computed_at: string | null;
}

export interface GradeSpecializationLink {
  competence_id: string;
  competence_title: string | null;
  skill_level_id: string;
  skill_level_title: string | null;
  id: string;
}

export interface GradeSpecialization {
  id: string;
  grade_id: string;
  grade_title: string;
  specialization_id: string;
  description: string | null;
  sort_index: number;
  passing_score: number | null;
  tenant_id: string;
  created_at: string;
  competence_links: GradeSpecializationLink[];
}

export interface GroupedAssessmentListItem {
  kind: "single" | "group";
  assessment?: Assessment;
  group?: AssessmentGroup;
}

export interface GroupedAssessmentList {
  items: GroupedAssessmentListItem[];
  total: number;
}

export interface MassExam {
  id: string;
  title: string;
  description: string | null;
  status: string;
  created_at: string;
  ended_at: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface TalentCard {
  id: string;
  title: string;
  description: string | null;
  card_type: string;
  status: string;
  is_published: boolean;
  division_id: string | null;
  published_at: string | null;
  closed_at: string | null;
  /** HRP-92 REDO: terminal-status dates surfaced as "Completed: yyyy-mm-dd". */
  completed_at: string | null;
  /** HRP-92 REDO: terminal-status date surfaced as "Cancelled: yyyy-mm-dd". */
  cancelled_at: string | null;
  start_date: string;
  end_date: string | null;
  // HRP-128: card-level Match% (50..100) used by the Required-competences matcher.
  match_percent: number;
  created_at: string;
  /** HRP-242: stamp of the last Candidates auto-pool recompute. */
  last_matched_at?: string | null;
  /** HRP-213: True when the viewing employee has already reacted on this card. */
  reacted_by_me?: boolean;
}

export interface PDP {
  id: string;
  title: string;
  employee_id: string;
  employee_name: string | null;
  // HRP-333: EmployeeSummaryLine inputs for the plan's employee.
  employee_position_title?: string | null;
  employee_status?: string | null;
  specialization_id: string | null;
  specialization_title: string | null;
  grade_id: string | null;
  grade_title: string | null;
  status: string;
  total_progress: number;
  deadline: string | null;
  // HRP-132: ``finished_at`` is set both when the plan completes and when
  // it is cancelled — the status tells the renderer which label to show.
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

// Answer scales
export interface AnswerOption {
  id: string;
  title: string;
  code: string;
  weight: number | null;
  description: string | null;
  sort_index: number;
  is_neutral: boolean;
}

export interface AnswerScaleLevel {
  id: string;
  percent_from: number;
  percent_to: number;
  system_code: string | null;
  system_title: string | null;
  description: string | null;
  sort_index: number;
}

export interface AnswerScale {
  id: string;
  title: string;
  description: string | null;
  // HRP-479: 'standard_5point' on the seeded default scale and its
  // snapshots; null on tenant scales.
  i18n_key: string | null;
  tenant_id: string | null;
  is_default: boolean;
  options: AnswerOption[];
}

export interface AnswerScaleDetail extends AnswerScale {
  levels: AnswerScaleLevel[];
  is_snapshot: boolean;
  deleted_at: string | null;
}

export interface AnswerScaleDeleteResult {
  deleted: boolean;
  reassigned_drafts: number;
}

export interface AnswerOptionInput {
  title: string;
  description?: string | null;
  sort_index: number;
  is_neutral: boolean;
}

export interface AnswerScaleLevelInput {
  percent_from: number;
  percent_to: number;
  system_title: string;
  description?: string | null;
  sort_index: number;
}

export interface AnswerScalePayload {
  title: string;
  description?: string | null;
  options: AnswerOptionInput[];
  levels: AnswerScaleLevelInput[];
}

// Indicator
export interface Indicator {
  id: string;
  title: string;
  weight: number;
  sort_index: number;
  skill_level_id: string;
  skill_level_title: string | null;
  competence_id: string;
  is_active: boolean;
  tenant_id: string | null;
  created_at: string;
}

// Competence detail (with indicators)
export interface CompetenceDetail extends Competence {
  indicators: Indicator[];
}

// Assessment detail types
export interface AssessmentParticipant {
  id: string;
  user_id: string;
  user_name: string | null;
  /** HRP-85: employee row matching the participant — `null` for externals. */
  employee_id: string | null;
  // HRP-333: EmployeeSummaryLine inputs (null for external reviewers).
  position_title?: string | null;
  employee_status?: string | null;
  /** HRP-85: viewer is permitted to open /employees/{employee_id}. */
  can_view_profile: boolean;
  role: string;
  is_completed: boolean;
}

export interface PerLevelResult {
  skill_level_id: string;
  skill_level_title: string | null;
  // HRP-479: origin levels localize via reference.skillLevel.*.
  skill_level_i18n_key?: string | null;
  sort_index: number;
  percent: number | null;
}

export interface AssessmentResult {
  competence_id: string;
  avg_score: number;
  calibrated_score: number | null;
  percent: number | null;
  level: AnswerScaleLevel | null;
  per_level_results: PerLevelResult[];
}

// HRP-154: per-competence/skill-level/indicator breakdown returned by
// GET /assessments/{id}/detailed-results.
// HRP-479: answer_code / overall_answer_code carry the stable option
// code next to the denormalized titles so seeded-scale answers localize
// via reference.scaleOption.* (tenant codes fall back to the title).
export interface DetailedRoleAnswer {
  role: string;
  answer_title: string | null;
  answer_code: string | null;
  answer_weight: number | null;
  is_neutral: boolean;
  answers_count: number;
}

export interface DetailedQuestionComment {
  role: string;
  user_name: string | null;
  created_at: string;
  text: string;
}

export interface DetailedQuestion {
  indicator_id: string;
  indicator_title: string;
  roles: DetailedRoleAnswer[];
  comments: DetailedQuestionComment[];
  overall_avg_weight: number | null;
  overall_percent: number | null;
  overall_answer_title: string | null;
  overall_answer_code: string | null;
  // HRP-185 REDO: id of the auto-computed Total's answer option so the
  // calibration Select can pre-fill with what's currently shown.
  overall_answer_option_id: string | null;
  all_dont_know: boolean;
  // HRP-185: set when a reviewer has pinned this indicator's Total.
  is_calibrated: boolean;
  calibrated_answer_option_id: string | null;
}

export interface DetailedSkillLevel {
  skill_level_id: string | null;
  skill_level_title: string | null;
  // HRP-479: origin levels localize via reference.skillLevel.*.
  skill_level_i18n_key?: string | null;
  sort_index: number;
  percent_for_skill_level: number | null;
  all_dont_know: boolean;
  questions: DetailedQuestion[];
}

export interface DetailedCompetenceResult {
  competence_id: string;
  competence_title: string;
  competence_type_id: string | null;
  competence_type_title: string | null;
  // HRP-479: stable keys next to the denormalized titles.
  competence_type_i18n_key?: string | null;
  required_skill_level_id: string | null;
  required_skill_level_title: string | null;
  required_skill_level_i18n_key?: string | null;
  percent: number | null;
  level_id: string | null;
  level_title: string | null;
  // Origin scale levels have system_title NULL — the code labels them.
  level_code?: string | null;
  all_dont_know: boolean;
  skill_levels: DetailedSkillLevel[];
}

export interface DetailedResultsResponse {
  assessment_id: string;
  competences: DetailedCompetenceResult[];
}

export interface AssessmentDetail extends Assessment {
  initiator_id: string;
  specialization_id: string | null;
  grade_id: string | null;
  scale_id: string | null;
  approver_id: string | null;
  cpa_id: string | null;
  ended_at: string | null;
  participants: AssessmentParticipant[];
  competence_ids: string[];
  competences: AssessmentCompetence[];
  criteria_type: CriteriaType | null;
  specialization_title: string | null;
  grade_title: string | null;
  // HRP-479: reference.dictionary.* keys for the criteria header.
  specialization_i18n_key?: string | null;
  grade_i18n_key?: string | null;
  recommendation: AssessmentRecommendation | null;
  results: AssessmentResult[];
  overall_percent: number | null;
  scale: AnswerScaleDetail | null;
}

// GF8: CPA comparison types
export interface CPAComparisonRound {
  id: string;
  title: string;
}

export interface CPAComparisonEntry {
  employee_id: string;
  employee_name: string;
  round_1_score: number;
  round_2_score: number;
  delta: number;
}

export interface CPAComparisonResult {
  round_1: CPAComparisonRound;
  round_2: CPAComparisonRound;
  comparisons: CPAComparisonEntry[];
}

// GF12: PDP progress timeline
export interface PDPProgressEntry {
  version: number;
  status: string;
  progress: number;
  total_items: number;
  passed_items: number;
  created_at: string | null;
}

// PDP detail types
export interface PDPMaterial {
  id: string;
  material_id: string | null;
  title: string;
  format: string | null;
  link: string | null;
  study_time: number | null;
  is_passed: boolean;
  sort_index: number;
  file_id?: string | null;
  file_url?: string | null;
  file_name?: string | null;
}

export interface PDPItem {
  id: string;
  competence_id: string | null;
  title: string;
  description: string | null;
  is_passed: boolean;
  entity_type: string | null;
  sort_index: number;
  materials: PDPMaterial[];
}

export interface PDPComment {
  id: string;
  pdp_id: string;
  item_id: string | null;
  user_id: string;
  user_name: string | null;
  text: string;
  file_id?: string | null;
  file_url?: string | null;
  file_name?: string | null;
  created_at: string;
}

export interface PDPDetail extends PDP {
  author_id: string;
  reviewer_id: string | null;
  reviewer_name: string | null;
  assessment_id: string | null;
  items: PDPItem[];
  comments: PDPComment[];
  is_owner: boolean;
  is_reviewer: boolean;
}

export interface PDPUpdate {
  title?: string;
  deadline?: string | null;
  specialization_id?: string | null;
  grade_id?: string | null;
}

// Exam detail types
export interface ExamOption {
  id: string;
  title: string;
  sort_index: number;
  is_correct: boolean;
}

export interface ExamQuestion {
  id: string;
  title: string;
  description: string | null;
  question_type: string;
  sort_index: number;
  weight: number;
  is_active: boolean;
  image_file_id?: string | null;
  image_url?: string | null;
  options: ExamOption[];
}

export interface MassExamDetail extends MassExam {
  initiator_id: string;
  tenant_id: string;
  started_at: string | null;
  finished_at: string | null;
  questions: ExamQuestion[];
  pass_marks: { id: string; grade_id: string | null; specialization_id: string | null; min_score_percent: number | null; min_score_points: number | null }[];
  assigned_count: number;
}

// Talent market detail types
export interface TalentRequirement {
  id: string;
  description: string;
  min_experience_years: number | null;
}

export interface TalentCandidate {
  id: string;
  employee_id: string;
  employee_name: string | null;
  /** HRP-149: viewer is permitted to open /employees/{employee_id}. */
  can_view_profile: boolean;
  status: string;
  match_score: number | null;
  response_at: string | null;
  appointed_at: string | null;
  /** HRP-173: per-axis breakdown mirroring CandidatePoolItem. */
  comp_match?: number | null;
  comp_qualifies?: boolean;
  exp_months?: number | null;
  exp_qualifies?: boolean;
  has_comp_requirement?: boolean;
  has_spec_requirement?: boolean;
  /** HRP-210: current Position lined up with a Required spec but no
   * matching WorkExperience entry — drawer / chip show "has experience"
   * / "Current position" in muted text. */
  exp_via_current_position?: boolean;
  /** HRP-209: True when this candidate row belongs to the viewer.
   * Drives "it's me" copy and gates the drawer-arrow / Appoint
   * affordances for the Employee role. */
  is_me?: boolean;
  /** HRP-258: feeds ``EmployeeSummaryLine`` on the Candidates table —
   * position is shown beneath the name; ``employee_status`` only
   * renders a chip when it is not ``active``. */
  position_title?: string | null;
  employee_status?: string | null;
}

// HRP-87 — structured Requirements rows.
export interface TalentRequiredSpecialization {
  id: string;
  specialization_id: string;
  grade_id: string | null;
  min_experience_years: number | null;
}

export interface TalentRequiredCompetence {
  id: string;
  competence_id: string;
  skill_level_id: string | null;
  match_percent: number | null;
}

export interface TalentCardDetail extends TalentCard {
  author_id: string;
  tenant_id: string;
  requirements: TalentRequirement[];
  specializations: TalentRequiredSpecialization[];
  competences: TalentRequiredCompetence[];
  candidates: TalentCandidate[];
}

export interface Notification {
  id: string;
  template_id: string;
  status: string;
  context: Record<string, unknown> | null;
  is_read: boolean;
  sent_at: string | null;
  created_at: string;
}

export interface ImportJobList {
  items: ImportJob[];
  total: number;
}

export interface ExamResult {
  id: string;
  employee_id: string;
  employee_name: string | null;
  // HRP-333: EmployeeSummaryLine inputs; `status` is the exam's own state.
  position_title?: string | null;
  employee_status?: string | null;
  can_view_profile?: boolean;
  status: string;
  score: number | null;
  max_score: number | null;
  passed: boolean | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface ImportJob {
  id: string;
  import_type: string;
  file_name: string;
  status: string;
  total_rows: number;
  processed_rows: number;
  error_rows: number;
  errors: { rows: { row: number; error: string }[] } | null;
  initiated_by: string;
  tenant_id: string;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

// Billing / Credits

export interface CreditBalance {
  free_credits: number;
  paid_credits: number;
  bonus_credits: number;
  total: number;
  billing_status: string;
  credits_reset_day: number;
  credit_warning_threshold: number;
}

// Per-site billing profile (HRP-451) — GET /billing/profile

export interface BillingPackage {
  id: string;
  credits: number;
  label: string;
  badge?: string | null;
  price: number;
}

export interface BillingLegalEntity {
  name?: string;
  inn?: string;
  bank_details?: string;
  vat_mode?: string;
  vat_rate?: number;
}

export interface BillingProfile {
  currency: string;
  locale: string;
  payment_provider: "manual_invoice" | "stripe" | "yookassa" | "none";
  legal_entity: BillingLegalEntity | null;
  packages: BillingPackage[];
}

export interface PurchaseCheckoutResult {
  provider: string;
  intent_id?: string;
  status?: string;
  package_id?: string;
  credits?: number;
  amount?: number;
  currency?: string;
  legal_entity?: BillingLegalEntity | null;
  checkout_url?: string;
}

export interface CreditTransaction {
  id: string;
  amount: number;
  credit_type: string;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  balance_after_free: number;
  balance_after_paid: number;
  balance_after_bonus: number;
  created_at: string;
}

export interface CreditHistoryList {
  items: CreditTransaction[];
  total: number;
}

// Billing Analytics

export interface SpendingByCategory {
  category: string;
  amount: number;
}

export interface SpendingByDay {
  date: string;
  amount: number;
}

export interface TopAction {
  action: string;
  total: number;
  count: number;
}

export interface SpendingForecast {
  credits_remaining: number;
  avg_daily_spend: number;
  estimated_days_remaining: number;
  estimated_depletion_date: string;
}

export interface BillingAnalytics {
  period_days: number;
  total_spent: number;
  avg_daily: number;
  by_category: SpendingByCategory[];
  by_day: SpendingByDay[];
  top_actions: TopAction[];
  forecast: SpendingForecast;
}

// Platform Admin

export interface PlatformTenantItem {
  id: string;
  name: string;
  slug: string;
  billing_status: string;
  is_active: boolean;
  users_count: number;
  employees_count: number;
  created_at: string;
}

export interface PlatformTenantDetail extends PlatformTenantItem {
  industry: string | null;
  company_size: string | null;
  website: string | null;
  description: string | null;
  free_credits: number;
  paid_credits: number;
  total_credits: number;
  credits_reset_day: number;
  credit_warning_threshold: number;
  last_activity: string | null;
  admin_email: string | null;
}

export interface PlatformTenantList {
  items: PlatformTenantItem[];
  total: number;
}

export interface PlatformStats {
  total_tenants: number;
  active_tenants: number;
  total_users: number;
  total_employees: number;
  total_credits_free: number;
  total_credits_paid: number;
}

export interface PlatformRecentRegistration {
  tenant_id: string;
  tenant_name: string;
  tenant_slug: string;
  admin_email: string | null;
  billing_status: string;
  created_at: string;
}

export interface PlatformDashboard {
  stats: PlatformStats;
  recent_registrations: PlatformRecentRegistration[];
  credits_by_tenant: {
    tenant_id: string;
    tenant_name: string;
    free_credits: number;
    paid_credits: number;
    total_credits: number;
    billing_status: string;
  }[];
}

export interface ImpersonateResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  tenant_name: string;
  tenant_slug: string;
}

// --- Recruitment ---

export interface Person {
  id: string;
  first_name: string;
  last_name: string;
  middle_name?: string | null;
  email?: string | null;
  phone?: string | null;
}

export interface VacancyDictionaryRef {
  id: string;
  title?: string | null;
}

export interface Vacancy {
  id: string;
  title: string;
  description?: string | null;
  // HRP-180
  position_id?: string | null;
  position_title?: string | null;
  specializations?: VacancyDictionaryRef[];
  grades?: VacancyDictionaryRef[];
  specialization_id?: string | null;
  grade_id?: string | null;
  division_id?: string | null;
  status: string;
  owner_id?: string | null;
  // HRP-360
  hiring_manager_id?: string | null;
  hiring_manager_name?: string | null;
  tasks_main?: Record<string, unknown> | null;
  tasks_additional?: Record<string, unknown> | null;
  tasks_kpi?: Record<string, unknown> | null;
  employment_type?: string | null;
  location?: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
  language?: string;
  close_resolution?: string | null;
  close_reason?: string | null;
  closed_at?: string | null;
  created_at: string;
  updated_at: string;
  owner_name?: string | null;
  specialization_title?: string | null;
  grade_title?: string | null;
  division_name?: string | null;
  candidates_count?: number;
  archived_at?: string | null;
  archived_by?: string | null;
  version?: number;
  has_profile?: boolean;
  active_invites_count?: number;
  // HRP-131
  library_refs?: {
    position_ids?: string[];
    specialization_grade_pairs?: Array<{
      specialization_id: string;
      grade_ids: string[];
    }>;
    division_ids?: string[];
  } | null;
  // HRP-135
  requirements?: string | null;
  responsibilities?: string | null;
  conditions?: string | null;
}

export interface VacancyAttachment {
  id: string;
  vacancy_id: string;
  file_id?: string | null;
  filename: string;
  mime_type: string;
  size_bytes: number;
  uploaded_at: string;
}

export interface VacancyCompetenceLink {
  id: string;
  vacancy_id: string;
  competence_id: string;
  skill_level_ids: string[];
  source: "manual" | "library" | "ai";
}

export interface VacancyList {
  items: Vacancy[];
  total: number;
  page: number;
  page_size: number;
}

export interface Candidate {
  id: string;
  /** HRP-181 REDO: nullable for externally-sourced candidates. */
  person_id: string | null;
  /** Null when no Person row backs this candidate (manual add / bulk import). */
  person: Person | null;
  /** Denormalised display name; canonical even when ``person`` is null. */
  full_name: string;
  email?: string | null;
  phone?: string | null;
  source?: string | null;
  notes?: string | null;
  resumes_count?: number;
  is_employee?: boolean;
  created_at: string;
}

export interface CandidateList {
  items: Candidate[];
  total: number;
  page: number;
  page_size: number;
}

export interface CandidateVacancy {
  id: string;
  candidate_id: string;
  vacancy_id: string;
  stage_id?: string | null;
  status: string;
  status_history?: Array<Record<string, unknown>>;
  ranking_score?: number | null;
  stage_name?: string | null;
  candidate_name?: string | null;
  vacancy_title?: string | null;
  created_at: string;
}

export interface Resume {
  id: string;
  candidate_id: string;
  file_id?: string | null;
  original_filename: string;
  mime_type: string;
  file_size: number;
  parsed_data?: Record<string, unknown> | null;
  raw_text?: string | null;
  parse_status: string;
  created_at: string;
}

export interface VacancyProfile {
  id: string;
  vacancy_id: string;
  profile_data?: Record<string, unknown> | null;
  version: number;
  language: string;
  coverage_note?: string | null;
  generated_by?: string | null;
  created_at: string;
}

export interface CompetenceQuestion {
  text: string;
  good_answer?: string;
  acceptable_answer?: string;
  poor_answer?: string;
}

export interface CompetenceItem {
  id?: string;
  group: string;
  subgroup: string;
  name: string;
  criticality: "critical" | "important" | "desirable";
  why_important: string;
  how_manifests: string;
  indicator_question: string;
  good_answer: string;
  acceptable_answer: string;
  poor_answer: string;
  // HRP-134 REDO: the canonical matrix the prompt now produces — at
  // least 3 observable indicators and at least 3 interview questions
  // per competence. ``indicator_question`` / ``good_answer`` / etc.
  // stay as legacy mirrors of ``questions[0]`` for older readers.
  indicators?: string[];
  questions?: CompetenceQuestion[];
}

export interface FunnelStage {
  id: string;
  tenant_id?: string | null;
  vacancy_id?: string | null;
  name: string;
  code: string;
  sort_order: number;
  is_terminal: boolean;
  color?: string | null;
}

export type QuestionPriority = "must" | "should" | "nice_to_ask";
export type QuestionPurpose =
  | "clarification"
  | "depth"
  | "risk"
  | "motivation"
  | "fit";

export interface CandidateQuestion {
  id: string;
  candidate_id: string;
  vacancy_id: string;
  competence_id?: string | null;
  question_text: string;
  good_answer: string;
  acceptable_answer: string;
  poor_answer: string;
  resume_fragment?: string | null;
  purpose: QuestionPurpose;
  priority: QuestionPriority;
  is_manual: boolean;
  sort_order: number;
  created_at: string;
}

export interface AssessmentInvite {
  id: string;
  candidate_vacancy_id: string;
  token: string;
  email: string;
  evaluator_name?: string | null;
  status: string;
  expires_at: string;
  created_at: string;
}

export interface AssessmentScore {
  id: string;
  candidate_vacancy_id: string;
  competence_id: string;
  evaluator_id: string;
  score?: number | null;
  comment?: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface CanvasEvaluator {
  id: string;
  name: string;
}

export interface CanvasCandidate {
  candidate_vacancy_id: string;
  candidate_id: string;
  name: string;
  status: string;
  human_scores: Record<string, Record<string, number | null>>;
  ai_scores: Record<string, number | null>;
}

export interface CanvasData {
  competences: CompetenceItem[];
  candidates: CanvasCandidate[];
  evaluators: CanvasEvaluator[];
}

// --- Recruitment HRP-265 (Assessment matrix / Compact view) ---

export type AssessmentMatrixAIStatus =
  | "ready"
  | "not_covered"
  | "missing"
  | string;

export interface AssessmentMatrixCompetence {
  id: string;
  name: string;
  group: string | null;
  criticality: string | null;
}

export interface AssessmentMatrixCell {
  competence_id: string;
  manager_score: number | null;
  manager_evaluator_count: number;
  ai_score: number | null;
  ai_status: AssessmentMatrixAIStatus;
  divergence: boolean;
}

export interface AssessmentMatrixCandidate {
  candidate_vacancy_id: string;
  candidate_id: string;
  name: string;
  status: string;
  stage_id: string | null;
  stage_name?: string | null;
  manager_percent: number | null;
  ai_percent: number | null;
  divergence_count: number;
  manager_scored_competences: number;
  ai_scored_competences: number;
  ai_not_covered_competences: number;
  cells: AssessmentMatrixCell[];
}

export interface AssessmentMatrixData {
  vacancy_id: string;
  divergence_threshold: number;
  max_score: number;
  scale_name: string | null;
  total_competences: number;
  competences: AssessmentMatrixCompetence[];
  candidates: AssessmentMatrixCandidate[];
}

export interface AssessmentMatrixManagerEntry {
  evaluator_label: string;
  evaluator_id: string | null;
  invite_id: string | null;
  score: number | null;
  comment: string | null;
  updated_at: string | null;
  version: number;
}

export interface AssessmentMatrixAIEntry {
  score: number | null;
  status: AssessmentMatrixAIStatus;
  reasoning: string | null;
  // CompetenceAssessment citations are persisted as
  // ``{competence, quote, verdict}`` on the canonical Pydantic schema;
  // ``text`` is kept as a fallback so older payloads still render.
  citations: { text?: string; quote?: string; competence?: string }[];
  interview_id: string;
  updated_at: string | null;
}

export interface AssessmentMatrixCellDetail {
  candidate_vacancy_id: string;
  candidate_name: string;
  competence_id: string;
  manager_entries: AssessmentMatrixManagerEntry[];
  ai_latest: AssessmentMatrixAIEntry | null;
  ai_history: AssessmentMatrixAIEntry[];
}

export interface MatrixSettings {
  divergence_threshold: number;
}

// --- Recruitment HRP-266 (Versions panel + Revert + ETag 412) ---

export type AssessmentHistoryOperation = "upsert" | "update" | "revert";

export interface AssessmentHistoryEvent {
  id: string;
  action:
    | "assessment.create"
    | "assessment.update"
    | "assessment.revert"
    | string;
  operation: AssessmentHistoryOperation | null;
  candidate_vacancy_id: string;
  competence_id: string;
  evaluator_id: string | null;
  invite_id: string | null;
  user_id: string | null;
  user_name: string | null;
  old_score: number | null;
  new_score: number | null;
  old_comment: string | null;
  new_comment: string | null;
  version: number | null;
  reverted_from_event_id: string | null;
  created_at: string;
}

export interface AssessmentHistoryResponse {
  items: AssessmentHistoryEvent[];
  total: number;
}

export interface AssessmentConflictState {
  cellKey: string;
  candidateVacancyId: string;
  competenceId: string;
  evaluatorId: string;
  mine: number | null;
  expectedVersion: number | null;
  serverMessage: string;
}

// --- Recruitment R3 (interview + consent) ---

export type InterviewStatus =
  | "planned"
  | "scheduled"
  | "uploading"
  | "uploaded"
  | "upload_failed"
  | "archived"
  | "in_progress"
  | "completed"
  | "cancelled";

export type InterviewType =
  | "audio"
  | "video"
  | "text_transcript"
  | "undecided";

export type InterviewAVStatus =
  | "pending"
  | "clean"
  | "infected"
  | "skipped"
  | "error";

export type InterviewProcessingStatus =
  | "pending"
  | "processing"
  | "completed"
  | "failed";

export interface InterviewSegment {
  id: string;
  interview_id: string;
  speaker: string;
  start_sec: number;
  end_sec: number;
  text: string;
  confidence?: number | null;
}

export interface InterviewAIAssessment {
  id: string;
  interview_id: string;
  competence_id: string;
  score?: number | null;
  status: string;
  citations?: Array<Record<string, unknown>>;
  reasoning?: string | null;
}

export interface InterviewAnalysisCompetence {
  competence_id: string;
  score: number | null;
  status: string;
  citations?: Array<{ start_sec?: number; speaker?: string; quote?: string }>;
  reasoning?: string;
}

export interface InterviewAnalysisBlindSpot {
  competence_id?: string;
  topic?: string;
  reason?: string;
  suggested_question?: string;
}

export interface InterviewAnalysisFinding {
  finding_type: string;
  severity?: string;
  detail?: string;
  positive_reframe?: string;
}

export interface InterviewAnalysisVerdict {
  recommendation: string;
  key_strength?: string;
  key_risk?: string;
  risk_mitigation?: string;
}

export interface InterviewAnalysis {
  competence_assessments?: InterviewAnalysisCompetence[];
  blind_spots?: InterviewAnalysisBlindSpot[];
  process_findings?: InterviewAnalysisFinding[];
  red_flags?: InterviewAnalysisFinding[];
  verdict?: InterviewAnalysisVerdict;
}

export interface Interview {
  id: string;
  candidate_vacancy_id: string;
  title?: string | null;
  type?: InterviewType | null;
  timezone?: string | null;
  duration_minutes?: number | null;
  interviewer_id?: string | null;
  interviewer_ids?: string[];
  interview_date?: string | null;
  duration_seconds?: number | null;
  audio_file_id?: string | null;
  video_file_id?: string | null;
  transcript_file_id?: string | null;
  file_s3_key?: string | null;
  file_size_bytes?: number | null;
  file_mime?: string | null;
  transcript?: string | null;
  notes?: string | null;
  status: InterviewStatus;
  av_status?: InterviewAVStatus | null;
  av_scanned_at?: string | null;
  version?: number;
  archived_at?: string | null;
  created_by?: string | null;
  transcription_provider?: string | null;
  transcription_status: InterviewProcessingStatus;
  analysis_status: InterviewProcessingStatus;
  transcription_error?: string | null;
  analysis_error?: string | null;
  /** HRP-202 REDO: upload was submitted with auto transcribe+analyze. */
  auto_process?: boolean;
  consent_signed_at?: string | null;
  consent_template_id?: string | null;
  segments: InterviewSegment[];
  ai_assessments: InterviewAIAssessment[];
  analysis?: InterviewAnalysis | null;
}

export interface InterviewMediaURL {
  url: string;
  expires_in: number;
  kind: "audio" | "video" | "text_transcript";
  mime_type: string;
  filename: string;
}

export interface InitUploadResponse {
  upload_id: string;
  session_id?: string | null;
  path: string;
  part_size: number;
  total_parts: number;
}

export interface PartUrlResponse {
  part_number: number;
  url: string;
  expires_in: number;
}

export type ConsentStatus =
  | "pending"
  | "signed"
  | "expired"
  | "superseded";

export interface ConsentRequest {
  id: string;
  candidate_id: string;
  template_id: string;
  email: string;
  status: ConsentStatus;
  expires_at: string;
  signed_at: string | null;
  created_at: string;
}

export interface ConsentTemplate {
  id: string;
  name: string;
  body: string;
  language: string;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ConsentTokenView {
  candidate_id: string;
  candidate_name: string;
  template_name: string;
  template_body: string;
  template_language: string;
  status: ConsentStatus;
  expires_at: string;
  signed_at: string | null;
}

// --- Recruitment R4a (reports + comparison) ---

export type ReportSectionCode =
  | "vacancy_summary"
  | "competence_profile"
  | "candidates_summary"
  | "comparison_grid"
  | "interview_analysis"
  | "human_assessments"
  | "process_findings"
  | "red_flags"
  | "verdict";

export const REPORT_SECTION_CODES: ReportSectionCode[] = [
  "vacancy_summary",
  "competence_profile",
  "candidates_summary",
  "comparison_grid",
  "interview_analysis",
  "human_assessments",
  "process_findings",
  "red_flags",
  "verdict",
];

// HRP-476 (i18n F2): the section wording lives in the `recruitment` i18n
// namespace — this map only owns the code → key relation (same shape as
// `lib/assessment-status.ts`). Consumers: the reports list, the report
// detail page, the report-templates settings page, the report wizard and
// the vacancy Reports tab.
export const REPORT_SECTION_LABEL_KEYS: Record<ReportSectionCode, string> = {
  vacancy_summary: "reportSectionVacancySummary",
  competence_profile: "reportSectionCompetenceProfile",
  candidates_summary: "reportSectionCandidatesSummary",
  comparison_grid: "reportSectionComparisonGrid",
  interview_analysis: "reportSectionInterviewAnalysis",
  human_assessments: "reportSectionHumanAssessments",
  process_findings: "reportSectionProcessFindings",
  red_flags: "reportSectionRedFlags",
  verdict: "reportSectionVerdict",
};

/** i18n key for a known report section code, or `null` for anything else. */
export function reportSectionKey(section: string): string | null {
  return REPORT_SECTION_LABEL_KEYS[section as ReportSectionCode] ?? null;
}

/** Translated section label; unknown codes fall back to the raw code, which
 *  is what the pre-i18n `REPORT_SECTION_LABELS[s] || s` rendered. */
export function reportSectionLabel(
  t: (key: string) => string,
  section: string,
): string {
  const key = reportSectionKey(section);
  return key ? t(key) : section;
}

export type ReportStatus =
  | "pending"
  | "processing"
  | "completed"
  | "failed";

export interface ReportTemplate {
  id: string;
  name: string;
  sections: ReportSectionCode[];
  is_active: boolean;
  is_default: boolean;
  template_data?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface ReportTemplateCreate {
  name: string;
  sections: ReportSectionCode[];
  is_active?: boolean;
  is_default?: boolean;
  template_data?: Record<string, unknown> | null;
}

export interface ReportTemplateUpdate {
  name?: string;
  sections?: ReportSectionCode[];
  is_active?: boolean;
  is_default?: boolean;
  template_data?: Record<string, unknown> | null;
}

export interface ReportExport {
  id: string;
  vacancy_id: string;
  template_id: string | null;
  template_name: string | null;
  sections: ReportSectionCode[];
  status: ReportStatus;
  error: string | null;
  file_id: string | null;
  download_url: string | null;
  requested_by: string | null;
  requested_by_name: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface ReportExportList {
  items: ReportExport[];
  total: number;
}

export interface ReportPreviewSheet {
  name: string;
  cells: (string | number | boolean | null)[][];
}

export interface ReportPreview {
  export_id: string;
  sheets: ReportPreviewSheet[];
  truncated: boolean;
}

export interface ReportGenerateRequest {
  template_id?: string | null;
  sections?: ReportSectionCode[];
  // HRP-268 — when audience='hiring_manager' the Detail sheet replaces
  // raw process findings with a neutral reframe; default is recruiter.
  audience?: "recruiter" | "hiring_manager";
  // HRP-268 — optional whitelist; empty / omitted means every active
  // candidate-vacancy row on the vacancy.
  candidate_vacancy_ids?: string[];
}

export interface ReportGenerateResponse {
  export_id: string;
  task_id: string;
}

export interface ComparisonCell {
  candidate_id: string;
  score: number | null;
  source: "human" | "ai" | "missing";
}

export interface ComparisonCompetence {
  competence_id: string;
  name: string;
  group?: string | null;
  criticality?: string | null;
  cells: ComparisonCell[];
  divergence: number | null;
}

export interface ComparisonCandidate {
  id: string;
  candidate_vacancy_id: string;
  name: string;
  status?: string | null;
  ranking_score?: number | null;
}

export interface ComparisonResponse {
  vacancy_id: string;
  candidates: ComparisonCandidate[];
  competences: ComparisonCompetence[];
}

// --- R4c: Onboarding ---

export type OnboardingStep =
  | "welcome"
  | "vacancy_created"
  | "candidate_invited"
  | "interview_scheduled"
  | "report_reviewed"
  | "done";

export interface RecruitmentOnboardingState {
  step: OnboardingStep;
  dismissed_at: string | null;
  demo_seeded_at: string | null;
}

// --- R4c: Report sharing ---

export interface ReportShare {
  id: string;
  report_id: string;
  token: string;
  share_url: string;
  expires_at: string;
  recipients: string[];
  message: string | null;
  open_count: number;
  last_opened_at: string | null;
  revoked_at: string | null;
  created_at: string;
  created_by: string | null;
}

export interface ReportSharePublicView {
  report_id: string;
  vacancy_title: string | null;
  generated_at: string | null;
  expires_at: string;
  download_url: string | null;
}

// --- R4c: Analytics ---

export interface FunnelStageStat {
  stage_id: string | null;
  stage_name: string | null;
  candidate_count: number;
  median_seconds_in_stage: number | null;
}

export interface VacancyAnalytics {
  vacancy_id: string;
  funnel: FunnelStageStat[];
  win_loss: { hired: number; rejected: number; withdrew: number; in_progress: number };
  total_candidates: number;
}

export interface AnalyticsSummary {
  top_velocity: { vacancy_id: string; title: string; metric_value: number | null }[];
  top_drop_off: { vacancy_id: string; title: string; metric_value: number | null }[];
  ai_variance_by_recruiter: {
    recruiter_id: string;
    sample_size: number;
    score_stddev: number | null;
  }[];
}

export interface RadarCandidate {
  candidate_id: string;
  name: string | null;
  scores: { competence_id: string; competence_name: string | null; score: number | null }[];
}

export interface ComparisonRadar {
  vacancy_id: string;
  candidates: RadarCandidate[];
  competences: ComparisonCompetence[];
}
