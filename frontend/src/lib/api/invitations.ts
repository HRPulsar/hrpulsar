import { api } from "@/lib/api";
import type {
  Invitation,
  InvitationEmailUpdate,
  InvitationList,
  InvitationUpdate,
} from "@/lib/types";

export type InvitationCreatePayload = {
  name: string;
  email: string;
  role_code: string;
  division_id?: string | null;
  position_id?: string | null;
};

export type InvitationListParams = {
  status?: string;
  skip?: number;
  limit?: number;
};

export const invitationsApi = {
  list: (params: InvitationListParams = {}) => {
    const qs = new URLSearchParams();
    if (params.status) qs.set("status", params.status);
    if (params.skip !== undefined) qs.set("skip", String(params.skip));
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    const suffix = qs.toString();
    return api.get<InvitationList>(
      suffix ? `/invitations?${suffix}` : "/invitations",
    );
  },
  create: (payload: InvitationCreatePayload) =>
    api.post<Invitation>("/invitations", payload),
  bulkCreate: (invitations: InvitationCreatePayload[]) =>
    api.post<Invitation[]>("/invitations/bulk", { invitations }),
  cancel: (id: string) => api.post<Invitation>(`/invitations/${id}/cancel`),
  resend: (id: string) => api.post<Invitation>(`/invitations/${id}/resend`),
  update: (id: string, payload: InvitationUpdate) =>
    api.patch<Invitation>(`/invitations/${id}`, payload),
  updateEmail: (id: string, payload: InvitationEmailUpdate) =>
    api.patch<Invitation>(`/invitations/${id}/email`, payload),
};
