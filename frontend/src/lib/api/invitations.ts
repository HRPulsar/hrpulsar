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

/** One address `POST /invitations/bulk` refused, with the backend error code. */
export type InvitationBulkFailure = {
  email: string;
  error_code: string;
};

/**
 * Multi-status answer of the bulk create (HRP-593). It used to be a plain
 * `Invitation[]` of whatever made it through, so a refused address just
 * vanished from the response — callers must render `failed` (translating
 * `error_code`), not report the whole batch as sent.
 */
export type InvitationBulkResult = {
  created: Invitation[];
  failed: InvitationBulkFailure[];
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
    api.post<InvitationBulkResult>("/invitations/bulk", { invitations }),
  cancel: (id: string) => api.post<Invitation>(`/invitations/${id}/cancel`),
  resend: (id: string) => api.post<Invitation>(`/invitations/${id}/resend`),
  update: (id: string, payload: InvitationUpdate) =>
    api.patch<Invitation>(`/invitations/${id}`, payload),
  updateEmail: (id: string, payload: InvitationEmailUpdate) =>
    api.patch<Invitation>(`/invitations/${id}/email`, payload),
};
