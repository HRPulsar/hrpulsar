"use client";

// HRP-174: contextual "Add employee" dialog opened from the Division
// detail page. Two modes:
//
//   - Add existing: pick one or many existing employees (search by
//     name/email), PATCH each one with the new division_id (+ optional
//     position_id). Cross-division picks trigger a confirm step.
//
//   - Create new: spawn a brand-new Employee row attached to a
//     pre-existing User. division_id is locked to the parent division.
//
// The dialog never reaches outside its props for state — the parent
// passes the list of all tenant employees + division-aware Position
// catalog and gets a `onRefresh` callback after successful submission.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Check, HelpCircle, Plus, Search, X } from "lucide-react";
import { api } from "@/lib/api";
import { parseFormError } from "@/lib/form-errors";
import { Button } from "@/components/ui/button";
import { FormErrorBanner } from "@/components/ui/form-error";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DatePicker } from "@/components/ui/date-picker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { usePermissions } from "@/hooks/use-permissions";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export interface AddEmployeeDialogEmployee {
  id: string;
  user_id: string;
  user_name: string | null;
  user_email: string | null;
  division_id: string | null;
  division_name: string | null;
}

export interface AddEmployeeAvailableUser {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  origin?: string;
}

export interface AddEmployeeDialogPosition {
  id: string;
  title: string;
}

export interface AddEmployeeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  divisionId: string;
  divisionName: string;
  allEmployees: AddEmployeeDialogEmployee[];
  positions: AddEmployeeDialogPosition[];
  onRefresh: () => Promise<void> | void;
}

interface TransferTarget {
  employeeId: string;
  display: string;
  fromDivision: string;
}

const TAB_EXISTING = "existing";
const TAB_NEW = "new";

/**
 * Pure helper exposed for unit testing — flags any selected employee
 * whose `division_id` is already set to a value different from the
 * target. Used to decide whether the confirm-transfer step kicks in.
 */
export function pickTransferTargets(
  selectedIds: string[],
  employees: AddEmployeeDialogEmployee[],
  targetDivisionId: string,
): TransferTarget[] {
  const out: TransferTarget[] = [];
  for (const id of selectedIds) {
    const emp = employees.find((e) => e.id === id);
    if (!emp) continue;
    if (emp.division_id && emp.division_id !== targetDivisionId) {
      const display =
        emp.user_name?.trim() || emp.user_email || emp.id;
      out.push({
        employeeId: emp.id,
        display,
        fromDivision: emp.division_name?.trim() || "another division",
      });
    }
  }
  return out;
}

/**
 * Filters the searchable Add-existing list down to candidates that are
 * not already in the target division and match the query (case-insensitive
 * substring on name or email).
 */
export function filterAddExistingCandidates(
  employees: AddEmployeeDialogEmployee[],
  query: string,
  divisionId: string,
): AddEmployeeDialogEmployee[] {
  const normalized = query.trim().toLowerCase();
  return employees.filter((e) => {
    if (e.division_id === divisionId) return false;
    if (!normalized) return true;
    const name = (e.user_name ?? "").toLowerCase();
    const email = (e.user_email ?? "").toLowerCase();
    return name.includes(normalized) || email.includes(normalized);
  });
}

export function AddEmployeeDialog({
  open,
  onOpenChange,
  divisionId,
  divisionName,
  allEmployees,
  positions,
  onRefresh,
}: AddEmployeeDialogProps) {
  const { canInvite } = usePermissions();
  const [tab, setTab] = useState<string>(TAB_EXISTING);

  // --- Add existing state ---
  const [search, setSearch] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [existingPositionId, setExistingPositionId] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [transferTargets, setTransferTargets] = useState<TransferTarget[] | null>(
    null,
  );

  // --- Create new state ---
  const [availableUsers, setAvailableUsers] = useState<
    AddEmployeeAvailableUser[]
  >([]);
  const [createUserId, setCreateUserId] = useState<string>("");
  const [createHireDate, setCreateHireDate] = useState<string>("");
  const [createPositionId, setCreatePositionId] = useState<string>("");

  useEffect(() => {
    if (!open) return;
    // Lazy-load the picker — same endpoint the standalone employees page
    // uses (HRP-91 / employees/page.tsx).
    void (async () => {
      try {
        const users = await api.get<AddEmployeeAvailableUser[]>(
          "/employees/available-users",
        );
        setAvailableUsers(users);
      } catch {
        setAvailableUsers([]);
      }
    })();
    // Default hire date to today on open.
    setCreateHireDate(new Date().toISOString().slice(0, 10));
  }, [open]);

  useEffect(() => {
    if (open) return;
    // Reset all transient state on close.
    setTab(TAB_EXISTING);
    setSearch("");
    setSelectedIds([]);
    setExistingPositionId("");
    setCreateUserId("");
    setCreatePositionId("");
    setErrorMsg(null);
    setTransferTargets(null);
    setSubmitting(false);
  }, [open]);

  const candidates = useMemo(
    () => filterAddExistingCandidates(allEmployees, search, divisionId),
    [allEmployees, search, divisionId],
  );

  const selectedEmployees = useMemo(
    () => allEmployees.filter((e) => selectedIds.includes(e.id)),
    [allEmployees, selectedIds],
  );

  function toggleSelection(id: string) {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  async function performAddExisting(confirmedTransfer: boolean) {
    setSubmitting(true);
    setErrorMsg(null);
    try {
      // Sequential PATCHes — there's no bulk endpoint and the UI keeps
      // a per-row error inline. Building the dialog around per-loop
      // toasts would be noisy; the operator gets a single summary toast.
      const payload: Record<string, unknown> = { division_id: divisionId };
      if (existingPositionId) payload.position_id = existingPositionId;
      const errors: string[] = [];
      for (const emp of selectedEmployees) {
        try {
          await api.put(`/employees/${emp.id}`, payload);
        } catch (err) {
          const display = emp.user_name?.trim() || emp.user_email || emp.id;
          const reason = err instanceof Error ? err.message : "request failed";
          errors.push(`${display}: ${reason}`);
        }
      }
      if (errors.length > 0) {
        setErrorMsg(errors.join("\n"));
        return;
      }
      const moved = confirmedTransfer
        ? selectedEmployees.length
        : selectedEmployees.length;
      toast.success(
        moved === 1
          ? `Added 1 employee to ${divisionName}`
          : `Added ${moved} employees to ${divisionName}`,
      );
      await onRefresh();
      onOpenChange(false);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleAddExistingSubmit() {
    if (selectedIds.length === 0) return;
    const targets = pickTransferTargets(selectedIds, allEmployees, divisionId);
    if (targets.length > 0) {
      setTransferTargets(targets);
      return;
    }
    await performAddExisting(false);
  }

  async function confirmTransfer() {
    setTransferTargets(null);
    await performAddExisting(true);
  }

  function cancelTransfer() {
    setTransferTargets(null);
  }

  async function handleCreateSubmit() {
    if (!createUserId || !createHireDate) return;
    setSubmitting(true);
    setErrorMsg(null);
    try {
      const payload: Record<string, unknown> = {
        user_id: createUserId,
        division_id: divisionId,
        hire_date: createHireDate,
      };
      if (createPositionId) payload.position_id = createPositionId;
      await api.post("/employees", payload);
      const u = availableUsers.find((x) => x.id === createUserId);
      const display = u
        ? `${u.first_name} ${u.last_name}`.trim() || u.email
        : "Employee";
      toast.success(`${display} created in ${divisionName}`);
      await onRefresh();
      onOpenChange(false);
    } catch (err) {
      setErrorMsg(parseFormError(err).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="division-detail-modal-add-employee"
        className="sm:max-w-2xl"
      >
        <DialogHeader>
          <DialogTitle>Add employee</DialogTitle>
          <DialogDescription>
            Adding to{" "}
            <span className="font-medium text-foreground">{divisionName}</span>
            . Switch tabs to add an existing employee or create a new one.
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue={TAB_EXISTING} value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger
              value={TAB_EXISTING}
              data-testid="division-detail-modal-add-employee-tab-existing"
            >
              Add existing
            </TabsTrigger>
            <TabsTrigger
              value={TAB_NEW}
              data-testid="division-detail-modal-add-employee-tab-new"
            >
              Create new
            </TabsTrigger>
          </TabsList>

          <TabsContent value={TAB_EXISTING} className="space-y-3">
            <div className="space-y-2">
              <Label htmlFor="add-employee-search">Employees</Label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="add-employee-search"
                  data-testid="division-detail-modal-add-employee-field-employee"
                  className="pl-8"
                  placeholder="Search by name or email…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <ul className="max-h-56 space-y-1 overflow-y-auto rounded-md border p-1">
                {candidates.length === 0 ? (
                  <li
                    data-testid="division-detail-modal-add-employee-candidates-empty"
                    className="px-2 py-3 text-center text-xs text-muted-foreground"
                  >
                    {search
                      ? "No matches — try a different query"
                      : "No eligible employees"}
                  </li>
                ) : (
                  candidates.map((emp) => {
                    const checked = selectedIds.includes(emp.id);
                    const display =
                      emp.user_name?.trim() || emp.user_email || emp.id;
                    return (
                      <li key={emp.id}>
                        <button
                          type="button"
                          data-testid={`division-detail-modal-add-employee-candidate-${emp.id}`}
                          aria-pressed={checked}
                          onClick={() => toggleSelection(emp.id)}
                          className={cn(
                            "flex w-full items-center justify-between gap-2 rounded-sm px-2 py-1.5 text-left text-sm",
                            checked
                              ? "bg-primary/10 text-foreground"
                              : "hover:bg-muted",
                          )}
                        >
                          <span className="flex flex-col">
                            <span className="font-medium">{display}</span>
                            {emp.user_email ? (
                              <span className="text-xs text-muted-foreground">
                                {emp.user_email}
                              </span>
                            ) : null}
                          </span>
                          <span className="flex items-center gap-2">
                            {emp.division_name ? (
                              <Badge variant="outline" className="text-xs">
                                {emp.division_name}
                              </Badge>
                            ) : null}
                            {checked ? (
                              <Check className="h-4 w-4 text-primary" />
                            ) : null}
                          </span>
                        </button>
                      </li>
                    );
                  })
                )}
              </ul>
              {selectedEmployees.length > 0 ? (
                <div className="flex flex-wrap gap-1">
                  {selectedEmployees.map((emp) => {
                    const display =
                      emp.user_name?.trim() || emp.user_email || emp.id;
                    return (
                      <Badge
                        key={emp.id}
                        variant="secondary"
                        className="gap-1 pr-1"
                      >
                        {display}
                        <button
                          type="button"
                          aria-label={`Remove ${display}`}
                          className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full hover:bg-background/40"
                          onClick={() => toggleSelection(emp.id)}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </Badge>
                    );
                  })}
                </div>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label>Position (optional)</Label>
              <Select
                value={existingPositionId}
                onValueChange={setExistingPositionId}
              >
                <SelectTrigger
                  data-testid="division-detail-modal-add-employee-field-position"
                  className="w-full"
                >
                  {/* HRP-174: explicit children prevent Base UI from
                      serialising the raw UUID when no <SelectItem> has
                      matched the current value yet (same trap as HRP-59
                      on the division Manager picker). */}
                  <SelectValue placeholder="Keep current position">
                    {existingPositionId
                      ? positions.find((p) => p.id === existingPositionId)
                          ?.title ?? "Keep current position"
                      : "Keep current position"}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">Keep current position</SelectItem>
                  {positions.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </TabsContent>

          <TabsContent value={TAB_NEW} className="space-y-3">
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Label htmlFor="add-employee-user">User</Label>
                {/* HRP-174 REDO: explain who actually appears in the list
                    (signed-up users without an employee card) so the
                    operator doesn't wonder why an invited person is
                    missing. */}
                <Tooltip>
                  <TooltipTrigger
                    render={
                      <button
                        type="button"
                        aria-label="Who is listed here?"
                        data-testid="division-detail-modal-add-employee-user-help"
                        className="inline-flex h-4 w-4 items-center justify-center text-muted-foreground hover:text-foreground"
                      />
                    }
                  >
                    <HelpCircle className="h-3.5 w-3.5" />
                  </TooltipTrigger>
                  <TooltipContent className="max-w-sm text-left">
                    Users who already signed up but do not yet have an
                    employee card. Check the Invitations page if you
                    have access, or ask an administrator to invite
                    them first.
                  </TooltipContent>
                </Tooltip>
                {canInvite ? (
                  <Button
                    variant="link"
                    size="sm"
                    className="ml-auto h-auto px-0 text-xs"
                    data-testid="division-detail-modal-add-employee-invite-link"
                    render={
                      <Link href="/settings/invitations?open=invite" />
                    }
                    onClick={() => onOpenChange(false)}
                  >
                    <Plus className="mr-1 h-3 w-3" />
                    Invite
                  </Button>
                ) : null}
              </div>
              <Select value={createUserId} onValueChange={setCreateUserId}>
                <SelectTrigger
                  id="add-employee-user"
                  data-testid="division-detail-modal-add-employee-field-employee"
                  className="w-full"
                >
                  {/* HRP-174: same UUID-leak fix as the Position picker.
                      Without explicit children the trigger renders the
                      raw user id whenever the value is set before the
                      <SelectItem> for it has mounted. */}
                  <SelectValue placeholder="Pick an existing user">
                    {(() => {
                      if (!createUserId) return undefined;
                      const u = availableUsers.find(
                        (x) => x.id === createUserId,
                      );
                      if (!u) return undefined;
                      const name =
                        `${u.first_name} ${u.last_name}`.trim() || u.email;
                      return `${name} (${u.email})`;
                    })()}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {availableUsers.length === 0 ? (
                    <div className="px-2 py-3 text-center text-xs text-muted-foreground">
                      No users available — invite one first
                    </div>
                  ) : (
                    availableUsers.map((u) => {
                      const name =
                        `${u.first_name} ${u.last_name}`.trim() || u.email;
                      return (
                        <SelectItem key={u.id} value={u.id}>
                          {name} ({u.email})
                        </SelectItem>
                      );
                    })
                  )}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="add-employee-hire-date">Hire date</Label>
                <DatePicker
                  id="add-employee-hire-date"
                  data-testid="division-detail-modal-add-employee-field-hire-date"
                  value={createHireDate}
                  onChange={setCreateHireDate}
                />
              </div>
              <div className="space-y-2">
                <Label>Division</Label>
                <Input
                  value={divisionName}
                  disabled
                  data-testid="division-detail-modal-add-employee-field-division"
                  // HRP-174: division is locked to the current page
                  // context; surfaced as disabled input with helper text.
                />
                <p className="text-xs text-muted-foreground">
                  Adding to this division
                </p>
              </div>
            </div>

            <div className="space-y-2">
              <Label>Position (optional)</Label>
              <Select
                value={createPositionId}
                onValueChange={setCreatePositionId}
              >
                <SelectTrigger
                  data-testid="division-detail-modal-add-employee-field-position"
                  className="w-full"
                >
                  {/* HRP-174: same UUID-leak fix — without children the
                      trigger renders the raw position id. */}
                  <SelectValue placeholder="None">
                    {createPositionId
                      ? positions.find((p) => p.id === createPositionId)
                          ?.title ?? "None"
                      : "None"}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">None</SelectItem>
                  {positions.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </TabsContent>
        </Tabs>

        <FormErrorBanner
          message={errorMsg}
          testId="division-detail-modal-add-employee-error"
        />

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
            data-testid="division-detail-modal-add-employee-cancel"
          >
            Cancel
          </Button>
          {tab === TAB_EXISTING ? (
            <Button
              data-testid="division-detail-modal-add-employee-submit"
              onClick={handleAddExistingSubmit}
              disabled={submitting || selectedIds.length === 0}
            >
              {submitting
                ? "Adding…"
                : selectedIds.length > 1
                  ? `Add ${selectedIds.length} employees`
                  : "Add employee"}
            </Button>
          ) : (
            <Button
              data-testid="division-detail-modal-add-employee-submit"
              onClick={handleCreateSubmit}
              disabled={submitting || !createUserId || !createHireDate}
            >
              {submitting ? "Creating…" : "Create employee"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>

      {/* HRP-174: confirm step for cross-division transfers. Mirrors the
          shape of the existing role-downgrade confirm dialog so the UX
          stays predictable. */}
      <Dialog
        open={transferTargets !== null && transferTargets.length > 0}
        onOpenChange={(o) => {
          if (!o) cancelTransfer();
        }}
      >
        <DialogContent
          data-testid="division-detail-transfer-confirm"
          className="sm:max-w-md"
        >
          <DialogHeader>
            <DialogTitle>
              Move{" "}
              {transferTargets && transferTargets.length === 1
                ? "1 employee"
                : `${transferTargets?.length ?? 0} employees`}{" "}
              to this division?
            </DialogTitle>
            <DialogDescription>
              The following employees will be moved from their current
              divisions.
            </DialogDescription>
          </DialogHeader>
          <ul className="space-y-1 text-sm">
            {(transferTargets ?? []).map((t) => (
              <li
                key={t.employeeId}
                data-testid={`division-detail-transfer-confirm-target-${t.employeeId}`}
                className="text-muted-foreground"
              >
                <span className="text-foreground">{t.display}</span>
                <span> (currently in &ldquo;{t.fromDivision}&rdquo;)</span>
              </li>
            ))}
          </ul>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={cancelTransfer}
              disabled={submitting}
              data-testid="division-detail-transfer-confirm-cancel"
            >
              Cancel
            </Button>
            <Button
              onClick={confirmTransfer}
              disabled={submitting}
              data-testid="division-detail-transfer-confirm-move"
            >
              {submitting ? "Moving…" : "Move"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Dialog>
  );
}
