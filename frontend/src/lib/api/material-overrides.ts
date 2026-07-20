import { api } from "@/lib/api";
import type { MaterialInContext, MaterialOverride } from "@/lib/types";

export const materialOverridesApi = {
  listMaterials: (competenceId: string, specializationId?: string | null) => {
    const qs = specializationId ? `?specialization_id=${specializationId}` : "";
    return api.get<MaterialInContext[]>(
      `/competences/${competenceId}/materials${qs}`,
    );
  },
  listOverrides: (competenceId: string, specializationId?: string | null) => {
    const qs = specializationId ? `?specialization_id=${specializationId}` : "";
    return api.get<MaterialOverride[]>(
      `/competences/${competenceId}/material-overrides${qs}`,
    );
  },
  create: (
    competenceId: string,
    payload: {
      material_id: string;
      specialization_id: string;
      mode: "hide" | "add";
    },
  ) =>
    api.post<MaterialOverride>(
      `/competences/${competenceId}/material-overrides`,
      payload,
    ),
  remove: (competenceId: string, overrideId: string) =>
    api.delete(`/competences/${competenceId}/material-overrides/${overrideId}`),
};
