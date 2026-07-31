import { api } from "@/lib/api";

export type SpecializationListItem = {
  id: string;
  title: string;
  description: string | null;
  is_active: boolean;
  grade_count: number;
  position_count: number;
  assigned_count: number;
  headcount_total: number;
  created_at: string | null;
};

export type SpecializationGrade = {
  id: string;
  grade_id: string;
  grade_title: string;
  // HRP-479: origin grades localize via reference.dictionary.grade.*.
  grade_i18n_key?: string | null;
  description: string | null;
  requirements: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
  passing_score: number | null;
  sort_index: number;
  matrix_status: "empty" | "configured";
  competence_count: number;
  // HRP-288: effective tenant-scoped is_active for the underlying grade
  // dictionary item. The spec detail page and matrix header render an
  // "Inactive" chip when false so reviewers can see the grade was
  // deactivated after the chain was already built.
  grade_is_active: boolean;
};

export type SpecializationDetail = SpecializationListItem & {
  grades: SpecializationGrade[];
};

export type PositionInDivision = {
  id: string;
  title: string;
  grade_id: string | null;
  grade_title: string | null;
  headcount: number | null;
  assigned: number;
  vacant: number;
  lifecycle_status: "active" | "on_hold" | "frozen" | "closed";
};

export type DivisionPositionsBlock = {
  division_id: string | null;
  division_name: string | null;
  positions: PositionInDivision[];
};

export type MatrixCell = {
  competence_id: string;
  competence_title: string | null;
  skill_level_id: string;
  skill_level_title: string | null;
};

export type MatrixBulkGrade = {
  grade_id: string;
  grade_title: string | null;
  grade_sort_index: number;
  links: MatrixCell[];
};

export type MatrixBulk = {
  grades: MatrixBulkGrade[];
};

export type MatrixBulkWriteGrade = {
  grade_id: string;
  links: { competence_id: string; skill_level_id: string }[];
};

export type IndicatorByLevel = {
  id: string;
  title: string;
  weight: number;
  skill_level_id: string;
  skill_level_title: string;
  skill_level_i18n_key: string | null;
  skill_level_sort_index: number;
};

import type { EmployeeAlert } from "@/components/employees/EmployeeListRow";

export type SpecializationEmployee = {
  id: string;
  user_id: string;
  user_name: string | null;
  user_email: string | null;
  position_title: string | null;
  specialization_title: string | null;
  grade_title: string | null;
  // HRP-175: division_id surfaces so the unified EmployeeList renders
  // the Division cell as a clickable deep-link.
  division_id: string | null;
  division_name: string | null;
  hire_date: string;
  status: string;
  avatar_url: string | null;
  alert: EmployeeAlert | null;
};

export type GradesReorderEntry = { grade_id: string; sort_index: number };

export type GradePatchInput = {
  description?: string | null;
  requirements?: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
  passing_score?: number | null;
};

export const specializationsApi = {
  list: () => api.get<SpecializationListItem[]>("/specializations"),
  get: (id: string) => api.get<SpecializationDetail>(`/specializations/${id}`),
  grades: (id: string) =>
    api.get<SpecializationGrade[]>(`/specializations/${id}/grades`),
  addGrades: (id: string, gradeIds: string[]) =>
    api.post<SpecializationGrade[]>(`/specializations/${id}/grades`, {
      grade_ids: gradeIds,
    }),
  reorderGrades: (id: string, orders: GradesReorderEntry[]) =>
    api.patch<SpecializationGrade[]>(`/specializations/${id}/grades/reorder`, {
      orders,
    }),
  patchGrade: (id: string, gradeId: string, body: GradePatchInput) =>
    api.patch<SpecializationGrade>(
      `/specializations/${id}/grades/${gradeId}`,
      body,
    ),
  deleteGrade: (id: string, gradeId: string) =>
    api.delete<void>(`/specializations/${id}/grades/${gradeId}`),
  positions: (id: string) =>
    api.get<DivisionPositionsBlock[]>(`/specializations/${id}/positions`),
  employees: (id: string, withAlerts = false) =>
    api.get<SpecializationEmployee[]>(
      `/specializations/${id}/employees${withAlerts ? "?with_alerts=true" : ""}`,
    ),
  matrix: (id: string, gradeId: string) =>
    api.get<MatrixCell[]>(`/specializations/${id}/matrix?grade_id=${gradeId}`),
  upsertMatrix: (
    id: string,
    gradeId: string,
    links: { competence_id: string; skill_level_id: string }[],
  ) =>
    api.put<MatrixCell[]>(
      `/specializations/${id}/matrix?grade_id=${gradeId}`,
      { links },
    ),
  matrixBulk: (id: string) =>
    api.get<MatrixBulk>(`/specializations/${id}/matrix-bulk`),
  upsertMatrixBulk: (id: string, grades: MatrixBulkWriteGrade[]) =>
    api.put<MatrixBulk>(`/specializations/${id}/matrix-bulk`, { grades }),
  indicatorsByLevel: (competenceId: string) =>
    api.get<IndicatorByLevel[]>(
      `/competences/${competenceId}/indicators-by-level`,
    ),
};
