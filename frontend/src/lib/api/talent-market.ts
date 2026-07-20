import { api } from "@/lib/api";
import type {
  TalentRequiredCompetence,
  TalentRequiredSpecialization,
} from "@/lib/types";

export interface RequiredSpecializationPayload {
  specialization_id: string;
  grade_id: string;
  min_experience_years: number | null;
}

export interface RequiredCompetenceBulkPayload {
  // HRP-128: "set/replace" payload — items absent from the list are removed
  // server-side. Match% moved to TalentCard.match_percent.
  items: { competence_id: string; skill_level_id: string }[];
}

export interface RequiredCompetenceUpdatePayload {
  competence_id: string;
  skill_level_id: string;
}

export const talentMarketApi = {
  addRequiredSpecialization: (
    cardId: string,
    body: RequiredSpecializationPayload,
  ) =>
    api.post<TalentRequiredSpecialization>(
      `/talent-market/${cardId}/required-specializations`,
      body,
    ),
  updateRequiredSpecialization: (
    cardId: string,
    linkId: string,
    body: RequiredSpecializationPayload,
  ) =>
    api.put<TalentRequiredSpecialization>(
      `/talent-market/${cardId}/required-specializations/${linkId}`,
      body,
    ),
  deleteRequiredSpecialization: (cardId: string, linkId: string) =>
    api.delete<void>(
      `/talent-market/${cardId}/required-specializations/${linkId}`,
    ),
  addRequiredCompetences: (
    cardId: string,
    body: RequiredCompetenceBulkPayload,
  ) =>
    api.post<TalentRequiredCompetence[]>(
      `/talent-market/${cardId}/required-competences`,
      body,
    ),
  updateRequiredCompetence: (
    cardId: string,
    linkId: string,
    body: RequiredCompetenceUpdatePayload,
  ) =>
    api.put<TalentRequiredCompetence>(
      `/talent-market/${cardId}/required-competences/${linkId}`,
      body,
    ),
  deleteRequiredCompetence: (cardId: string, linkId: string) =>
    api.delete<void>(
      `/talent-market/${cardId}/required-competences/${linkId}`,
    ),
};
