import { api } from "@/lib/api";

export type DictionaryItemUsagePosition = {
  id: string;
  title: string;
};

export type DictionaryItemUsageChain = {
  id: string;
  grade_id: string | null;
  grade_title: string | null;
  specialization_id: string | null;
  specialization_title: string | null;
};

export type DictionaryItemUsage = {
  positions: DictionaryItemUsagePosition[];
  chains: DictionaryItemUsageChain[];
  // Prod fix (issue 7559975192): assessment / group / PDP / exam_pass_marks
  // FKs default to RESTRICT — surfaced as aggregate counts so the confirm
  // dialog can warn the operator before the DELETE attempt.
  assessments_count: number;
  assessment_groups_count: number;
  pdps_count: number;
  exam_pass_marks_count: number;
  // HRP-286 redo: competences referencing a competence_type item.
  competences_count: number;
};

export const dictionariesApi = {
  // HRP-103 redo: preview the live references that would block delete so
  // the confirm dialog can enumerate them before the operator commits.
  usage: (itemId: string) =>
    api.get<DictionaryItemUsage>(`/dictionaries/items/${itemId}/usage`),
};
