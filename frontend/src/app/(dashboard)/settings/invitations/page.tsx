"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { DeepLinkInviteOpener } from "@/components/settings/deep-link-invite-opener";
import { useTranslations } from "next-intl";
import { api, ApiError } from "@/lib/api";
import { invitationsApi } from "@/lib/api/invitations";
import { useAuth } from "@/context/auth-context";
import type {
  Division,
  Invitation,
  InvitationUpdate,
  Role,
} from "@/lib/types";
import { flattenTree } from "@/lib/utils";
import { formatDate } from "@/lib/date-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PositionCombobox } from "@/components/position-combobox";
import { RequireRole } from "@/components/require-role";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import { Mail, Pencil, Plus, RotateCw, X } from "lucide-react";
import { BADGE_COLOR } from "@/lib/badge-tones";

const statusColors: Record<string, string> = {
  pending: BADGE_COLOR.yellow,
  accepted: BADGE_COLOR.green,
  cancelled: BADGE_COLOR.neutral,
  expired: BADGE_COLOR.red,
};

// EMP3: keep this in sync with `_INVITE_ALLOWED` in backend/app/modules/auth/service.py
const INVITE_ALLOWED: Record<string, ReadonlySet<string>> = {
  platform_admin: new Set(["platform_admin", "admin", "hr", "manager", "employee"]),
  admin: new Set(["admin", "hr", "manager", "employee"]),
  hr: new Set(["admin", "hr", "manager", "employee"]),
  manager: new Set(["employee"]),
};

function allowedInviteRoles(userRoles: string[]): Set<string> {
  const allowed = new Set<string>();
  for (const code of userRoles) {
    const set = INVITE_ALLOWED[code];
    if (set) for (const c of set) allowed.add(c);
  }
  return allowed;
}


// HRP-436: Invitations is an Admin-section page — managers and employees get a
// toast + redirect instead of the (empty, 403-backed) list. Guarding the whole
// component, not just its JSX, keeps the forbidden fetches from firing at all.
export default function InvitationsPage() {
  return (
    <RequireRole admin>
      <InvitationsPageContent />
    </RequireRole>
  );
}

function InvitationsPageContent() {
  const t = useTranslations("settings");
  const tc = useTranslations("common");
  const { user } = useAuth();
  const isAdmin = !!(
    user?.is_platform_admin || user?.roles?.includes("admin")
  );
  const inviterRoles: string[] = user?.is_platform_admin
    ? ["platform_admin", ...(user?.roles ?? [])]
    : (user?.roles ?? []);
  const allowedRoleCodes = allowedInviteRoles(inviterRoles);

  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [total, setTotal] = useState(0);
  const [roles, setRoles] = useState<Role[]>([]);
  const [divisions, setDivisions] = useState<Division[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("");

  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteForm, setInviteForm] = useState({
    name: "",
    email: "",
    role_code: "employee",
    division_id: "",
    position_id: "",
  });
  const [saving, setSaving] = useState(false);

  const [emailEdit, setEmailEdit] = useState<{
    id: string;
    email: string;
  } | null>(null);
  const [emailSaving, setEmailSaving] = useState(false);
  const [savingRows, setSavingRows] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    try {
      const [inv, r, d] = await Promise.allSettled([
        invitationsApi.list({ status: statusFilter || undefined }),
        api.get<Role[]>("/roles"),
        api.get<Division[]>("/divisions"),
      ]);
      if (inv.status === "fulfilled") {
        setInvitations(inv.value.items);
        setTotal(inv.value.total);
      }
      if (r.status === "fulfilled") setRoles(r.value);
      if (d.status === "fulfilled") setDivisions(d.value);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  // HRP-174: deep-linked Invite from the Add-employee modal opens the
  // Send invitation dialog automatically so the admin doesn't have to
  // hunt for the button after switching pages. useSearchParams is wrapped
  // in Suspense (Next 16 requires it for the static-prerender path).

  const flatDivisions = flattenTree(divisions);

  async function handleInvite() {
    if (!inviteForm.name.trim() || !inviteForm.email) return;
    setSaving(true);
    try {
      await invitationsApi.create({
        name: inviteForm.name.trim(),
        email: inviteForm.email,
        role_code: inviteForm.role_code,
        division_id: inviteForm.division_id || null,
        position_id: inviteForm.position_id || null,
      });
      toast.success(t("inviteSent"));
      setInviteOpen(false);
      setInviteForm({
        name: "",
        email: "",
        role_code: "employee",
        division_id: "",
        position_id: "",
      });
      await load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("inviteSendFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleCancel(id: string) {
    try {
      await invitationsApi.cancel(id);
      toast.success(t("inviteCancelled"));
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("inviteCancelFailed"));
    }
  }

  async function handleResend(id: string) {
    try {
      await invitationsApi.resend(id);
      toast.success(t("inviteResent"));
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("inviteResendFailed"));
    }
  }

  async function patchInvitation(id: string, payload: InvitationUpdate) {
    setSavingRows((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });
    setInvitations((rows) =>
      rows.map((r) => {
        if (r.id !== id) return r;
        const next: Invitation = { ...r };
        if (payload.role_code !== undefined) {
          next.role_code = payload.role_code;
        }
        if (payload.division_id !== undefined) {
          next.division_id = payload.division_id;
          next.division_name = null;
        }
        if (payload.position_id !== undefined) {
          next.position_id = payload.position_id;
          next.position_title = null;
        }
        return next;
      }),
    );
    try {
      const updated = await invitationsApi.update(id, payload);
      setInvitations((rows) =>
        rows.map((r) => (r.id === id ? updated : r)),
      );
    } catch (err) {
      const msg =
        err instanceof ApiError || err instanceof Error
          ? err.message
          : t("inviteUpdateFailed");
      toast.error(msg);
      await load();
    } finally {
      setSavingRows((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }

  async function handleEmailSubmit() {
    if (!emailEdit) return;
    const trimmed = emailEdit.email.trim();
    if (!trimmed) return;
    setEmailSaving(true);
    try {
      const updated = await invitationsApi.updateEmail(emailEdit.id, {
        email: trimmed,
      });
      setInvitations((rows) =>
        rows.map((r) => (r.id === emailEdit.id ? updated : r)),
      );
      toast.success(t("inviteReSent"));
      setEmailEdit(null);
    } catch (err) {
      const msg =
        err instanceof ApiError || err instanceof Error
          ? err.message
          : t("inviteEmailUpdateFailed");
      toast.error(msg);
    } finally {
      setEmailSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <Suspense fallback={null}>
        <DeepLinkInviteOpener onOpen={() => setInviteOpen(true)} />
      </Suspense>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("inviteTitle")}
          </h1>
          <p className="text-sm text-muted-foreground">
            {t("inviteSubtitle")}
          </p>
        </div>
        <Button data-testid="invitations-btn-invite" onClick={() => setInviteOpen(true)}>
          <Plus className="mr-1 h-4 w-4" />
          {t("inviteButton")}
        </Button>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">
            {t("inviteCount", { count: total })}
          </CardTitle>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-[140px]">
              <SelectValue placeholder={t("inviteAllStatuses")}>
                {statusFilter === "pending"
                  ? t("inviteStatusPending")
                  : statusFilter === "accepted"
                    ? t("inviteStatusAccepted")
                    : statusFilter === "cancelled"
                      ? t("inviteStatusCancelled")
                      : statusFilter === "expired"
                        ? t("inviteStatusExpired")
                        : undefined}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">{t("inviteStatusAll")}</SelectItem>
              <SelectItem value="pending">{t("inviteStatusPending")}</SelectItem>
              <SelectItem value="accepted">
                {t("inviteStatusAccepted")}
              </SelectItem>
              <SelectItem value="cancelled">
                {t("inviteStatusCancelled")}
              </SelectItem>
              <SelectItem value="expired">{t("inviteStatusExpired")}</SelectItem>
            </SelectContent>
          </Select>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              {tc("loading")}
            </p>
          ) : invitations.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              {t("inviteEmpty")}
            </p>
          ) : (
            <div className="rounded-lg border">
              <Table data-testid="invitations-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("inviteName")}</TableHead>
                    <TableHead>{t("inviteEmail")}</TableHead>
                    <TableHead>{t("inviteRole")}</TableHead>
                    <TableHead>{t("inviteDivision")}</TableHead>
                    <TableHead>{t("invitePosition")}</TableHead>
                    <TableHead>{t("inviteStatus")}</TableHead>
                    <TableHead>{t("inviteInvitedBy")}</TableHead>
                    <TableHead>{t("inviteDate")}</TableHead>
                    <TableHead className="text-right">
                      {t("inviteActions")}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {invitations.map((inv) => {
                    const editable = inv.status === "pending";
                    return (
                      <TableRow key={inv.id} data-testid={`invitations-row-${inv.id}`}>
                        <TableCell
                          className="font-medium"
                          data-testid={`invitations-row-${inv.id}-name`}
                        >
                          {inv.name}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1">
                            <span>{inv.email}</span>
                            {editable && isAdmin && (
                              <Button
                                variant="ghost"
                                size="icon-sm"
                                data-testid={`invitations-row-${inv.id}-btn-edit-email`}
                                onClick={() =>
                                  setEmailEdit({ id: inv.id, email: inv.email })
                                }
                                title={t("inviteEditEmailTitle")}
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </Button>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          {editable && isAdmin ? (
                            <Select
                              value={inv.role_code}
                              disabled={savingRows.has(inv.id)}
                              onValueChange={(val) =>
                                patchInvitation(inv.id, { role_code: val })
                              }
                            >
                              <SelectTrigger
                                className="h-8 w-[140px]"
                                data-testid={`invitations-row-${inv.id}-edit-role`}
                              >
                                <SelectValue>
                                  {roles.find((r) => r.code === inv.role_code)?.name ??
                                    inv.role_code}
                                </SelectValue>
                              </SelectTrigger>
                              <SelectContent>
                                {roles
                                  .filter((r) => allowedRoleCodes.has(r.code))
                                  .map((r) => (
                                    <SelectItem key={r.id} value={r.code}>
                                      {r.name}
                                    </SelectItem>
                                  ))}
                              </SelectContent>
                            </Select>
                          ) : (
                            <span data-testid={`invitations-row-${inv.id}-role`}>
                              {inv.role_code}
                            </span>
                          )}
                        </TableCell>
                        <TableCell
                          className="text-muted-foreground"
                          data-testid={`invitations-row-${inv.id}-division`}
                        >
                          {editable ? (
                            <Select
                              value={inv.division_id ?? ""}
                              disabled={savingRows.has(inv.id)}
                              onValueChange={(val) =>
                                patchInvitation(inv.id, {
                                  division_id: val || null,
                                })
                              }
                            >
                              <SelectTrigger
                                className="h-8 w-[180px]"
                                data-testid={`invitations-row-${inv.id}-edit-division`}
                              >
                                <SelectValue placeholder={t("inviteNoDivision")}>
                                  {(() => {
                                    if (!inv.division_id) return undefined;
                                    const d = flatDivisions.find(
                                      (x) => x.id === inv.division_id,
                                    );
                                    return d
                                      ? `${"—".repeat(d.depth)} ${d.name}`
                                      : (inv.division_name ?? undefined);
                                  })()}
                                </SelectValue>
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="">
                                  {t("inviteNoDivision")}
                                </SelectItem>
                                {flatDivisions.map((d) => (
                                  <SelectItem key={d.id} value={d.id}>
                                    {"—".repeat(d.depth)} {d.name}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          ) : (
                            (inv.division_name ?? "—")
                          )}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {editable ? (
                            <div className="w-[200px]">
                              <PositionCombobox
                                data-testid={`invitations-row-${inv.id}-edit-position`}
                                value={inv.position_id ?? null}
                                disabled={savingRows.has(inv.id)}
                                onValueChange={(id) =>
                                  patchInvitation(inv.id, {
                                    position_id: id || null,
                                  })
                                }
                              />
                            </div>
                          ) : (
                            (inv.position_title ?? "—")
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="secondary"
                            data-testid={`invitations-row-${inv.id}-status`}
                            className={statusColors[inv.status] || ""}
                          >
                            {inv.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {inv.inviter_name || "—"}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {formatDate(inv.created_at)}
                        </TableCell>
                        <TableCell className="text-right">
                          {editable && (
                            <div className="flex justify-end gap-1">
                              <Button
                                variant="ghost"
                                size="icon-sm"
                                onClick={() => handleResend(inv.id)}
                                title={t("inviteResendTitle")}
                              >
                                <RotateCw className="h-3.5 w-3.5" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon-sm"
                                data-testid={`invitations-row-${inv.id}-btn-revoke`}
                                onClick={() => handleCancel(inv.id)}
                                title={tc("cancel")}
                              >
                                <X className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Invite dialog */}
      <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
        <DialogContent data-testid="invitations-modal-invite">
          <DialogHeader>
            <DialogTitle>
              <Mail className="mr-2 inline h-5 w-5" />
              {t("inviteSendTitle")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>{t("inviteName")}</Label>
              <Input
                type="text"
                maxLength={200}
                data-testid="invitations-modal-invite-input-name"
                value={inviteForm.name}
                onChange={(e) =>
                  setInviteForm({ ...inviteForm, name: e.target.value })
                }
                placeholder={t("inviteNamePlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <Label>{t("inviteEmail")}</Label>
              <Input
                type="email"
                data-testid="invitations-modal-invite-input-email"
                value={inviteForm.email}
                onChange={(e) =>
                  setInviteForm({ ...inviteForm, email: e.target.value })
                }
                placeholder={t("inviteEmailPlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <Label>{t("inviteRole")}</Label>
              <Select
                value={inviteForm.role_code}
                onValueChange={(val) =>
                  setInviteForm({ ...inviteForm, role_code: val })
                }
              >
                <SelectTrigger className="w-full" data-testid="invitations-modal-invite-select-role">
                  <SelectValue>
                    {roles.find((r) => r.code === inviteForm.role_code)?.name ?? ""}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {roles
                    .filter((r) => allowedRoleCodes.has(r.code))
                    .map((r) => (
                      <SelectItem key={r.id} value={r.code}>
                        {r.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t("inviteDivision")}</Label>
              <Select
                value={inviteForm.division_id}
                onValueChange={(val) =>
                  setInviteForm({ ...inviteForm, division_id: val })
                }
              >
                <SelectTrigger
                  className="w-full"
                  data-testid="invitations-modal-invite-select-division"
                >
                  <SelectValue placeholder={t("inviteSelectDivision")}>
                    {(() => { if (!inviteForm.division_id) return undefined; const d = flatDivisions.find((d) => d.id === inviteForm.division_id); return d ? `${"—".repeat(d.depth)} ${d.name}` : undefined; })()}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {flatDivisions.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {"—".repeat(d.depth)} {d.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t("invitePosition")}</Label>
              <PositionCombobox
                data-testid="invitations-modal-invite-select-position"
                value={inviteForm.position_id || null}
                onValueChange={(id) =>
                  setInviteForm({ ...inviteForm, position_id: id || "" })
                }
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setInviteOpen(false)}
              disabled={saving}
            >
              {tc("cancel")}
            </Button>
            <Button
              data-testid="invitations-modal-invite-btn-submit"
              onClick={handleInvite}
              // HRP-195: Division and Position are required when sending
              // an invitation so the new user lands in the right place
              // (and, for role=manager, can be auto-assigned as the
              // division manager on accept).
              disabled={
                saving ||
                !inviteForm.name.trim() ||
                !inviteForm.email ||
                !inviteForm.division_id ||
                !inviteForm.position_id
              }
            >
              {saving ? t("inviteSending") : t("inviteSendTitle")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit-email dialog */}
      <Dialog
        open={!!emailEdit}
        onOpenChange={(open) => {
          if (!open) setEmailEdit(null);
        }}
      >
        <DialogContent data-testid="invitations-modal-edit-email">
          <DialogHeader>
            <DialogTitle>
              <Mail className="mr-2 inline h-5 w-5" />
              {t("inviteEditEmailTitle")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>{t("inviteEmail")}</Label>
              <Input
                type="email"
                data-testid="invitations-modal-edit-email-input"
                value={emailEdit?.email ?? ""}
                onChange={(e) =>
                  setEmailEdit((prev) =>
                    prev ? { ...prev, email: e.target.value } : prev,
                  )
                }
                placeholder={t("inviteEmailPlaceholder")}
              />
              <p className="text-xs text-muted-foreground">
                {t("inviteEmailHint")}
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setEmailEdit(null)}
              disabled={emailSaving}
            >
              {tc("cancel")}
            </Button>
            <Button
              data-testid="invitations-modal-edit-email-btn-submit"
              onClick={handleEmailSubmit}
              disabled={emailSaving || !emailEdit?.email.trim()}
            >
              {emailSaving ? t("inviteSending") : t("inviteResendSubmit")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
