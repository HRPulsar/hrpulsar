"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { EmployeeSummaryLine } from "@/components/employee/employee-summary-line";
import {
  PDP_STATUS_OPTIONS,
  isManualBlockedPDPStatus,
  isTerminalPDPStatus,
  pdpStatusColor,
  pdpStatusLabel,
} from "@/lib/pdp-status";
import { formatDate } from "@/lib/date-format";
import type {
  DictionaryItem,
  Employee,
  EmployeeList,
  GradeOption,
  PDP,
  Position,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DatePicker } from "@/components/ui/date-picker";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip, TooltipContent, TooltipTrigger,
} from "@/components/ui/tooltip";
import { MultiSelectFilter } from "@/components/multi-select-filter";
import { usePermissions } from "@/hooks/use-permissions";
import { toast } from "sonner";
import Link from "next/link";
import { Info, MoreHorizontal, Plus, Search, X } from "lucide-react";
import { isPastDeadline, todayLocalISO } from "@/lib/deadline";
import {
  hasActivePdpFilters,
  matchesPdpFilters,
  sortPdpsForList,
} from "@/lib/pdp-filters";

const emptyForm = {
  title: "",
  employee_id: "",
  specialization_id: "",
  grade_id: "",
  deadline: "",
};

export default function DevelopmentPage() {
  const router = useRouter();
  const [pdps, setPdps] = useState<PDP[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [specializations, setSpecializations] = useState<DictionaryItem[]>([]);
  // HRP-293: grade options are server-side — chains of the selected
  // specialization minus tenant-deactivated grades (include_id keeps a
  // pre-filled grade selectable).
  const [specGrades, setSpecGrades] = useState<GradeOption[]>([]);
  const [loading, setLoading] = useState(true);

  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);

  // HRP-292: the dropdowns offer only active dictionary items; a value
  // pre-filled from the employee's position stays selectable even if it
  // was deactivated, so the auto-fill isn't silently lost.
  const specOptions = useMemo(
    () =>
      specializations.filter(
        (s) => s.is_active || s.id === form.specialization_id,
      ),
    [specializations, form.specialization_id],
  );

  const [statusOpen, setStatusOpen] = useState(false);
  const [statusTarget, setStatusTarget] = useState<PDP | null>(null);
  const [newStatus, setNewStatus] = useState("");

  const [saving, setSaving] = useState(false);

  // Filters — HRP-147: mirror Assessments filter bar (search + multi-status).
  // Type filter is dropped per spec: PDPs do not carry a type.
  const [searchQuery, setSearchQuery] = useState("");
  const [filterStatuses, setFilterStatuses] = useState<string[]>([]);

  const { canManage } = usePermissions();

  async function load() {
    try {
      const [pdpData, empData, specData] = await Promise.all([
        api.get<PDP[]>("/pdp"),
        api.get<EmployeeList>("/employees?limit=100"),
        api.get<DictionaryItem[]>("/dictionaries/specialization").catch(() => []),
      ]);
      setPdps(pdpData);
      setEmployees(empData.items);
      setSpecializations(specData);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  // Monotonic token: a slow response for a previously selected
  // specialization must not overwrite the options of the current one.
  const gradeReqSeq = useRef(0);

  async function loadGradesForSpec(
    specId: string,
    includeGradeId?: string,
  ): Promise<GradeOption[] | null> {
    const seq = ++gradeReqSeq.current;
    // Clear immediately: the previous specialization's options must not be
    // pickable while the new list is in flight.
    setSpecGrades([]);
    if (!specId) return [];
    const url = includeGradeId
      ? `/grade-system/specializations/${specId}/grades?include_id=${includeGradeId}`
      : `/grade-system/specializations/${specId}/grades`;
    let options: GradeOption[] = [];
    try {
      options = await api.get<GradeOption[]>(url);
    } catch {
      options = [];
    }
    if (seq !== gradeReqSeq.current) return null;
    setSpecGrades(options);
    return options;
  }

  function handleSpecializationChange(specId: string) {
    // Manual specialization switch invalidates the grade — grades are
    // scoped to their specialization's chains.
    setForm((prev) => ({ ...prev, specialization_id: specId, grade_id: "" }));
    loadGradesForSpec(specId);
  }

  async function handleEmployeeChange(employeeId: string) {
    setForm((prev) => ({
      ...prev,
      employee_id: employeeId,
      specialization_id: "",
      grade_id: "",
    }));
    void loadGradesForSpec("");
    const emp = employees.find((e) => e.id === employeeId);
    if (!emp?.position_id) return;
    try {
      const pos = await api.get<Position>(`/positions/${emp.position_id}`);
      setForm((prev) => ({
        ...prev,
        employee_id: employeeId,
        specialization_id: pos.specialization_id ?? "",
        // A position grade without a specialization would sit invisible
        // behind the disabled select and leak into the POST — drop it.
        grade_id: pos.specialization_id ? pos.grade_id ?? "" : "",
      }));
      if (pos.specialization_id) {
        const options = await loadGradesForSpec(
          pos.specialization_id,
          pos.grade_id ?? undefined,
        );
        // include_id only rescues a chained-but-deactivated grade; a
        // position grade not chained to the specialization is absent
        // from the options and must not linger as an invisible selection.
        // options === null means a newer request superseded this one.
        if (
          options &&
          pos.grade_id &&
          !options.some((g) => g.id === pos.grade_id)
        ) {
          setForm((prev) => ({ ...prev, grade_id: "" }));
        }
      }
    } catch {
      // employee position lookup failed — keep manual selection
    }
  }

  async function handleCreate() {
    if (!form.title.trim()) {
      toast.error("Title is required");
      return;
    }
    if (!form.employee_id) {
      toast.error("Employee is required");
      return;
    }
    if (isPastDeadline(form.deadline)) {
      toast.error("Deadline cannot be in the past");
      return;
    }
    setSaving(true);
    try {
      await api.post("/pdp", {
        title: form.title.trim(),
        employee_id: form.employee_id,
        specialization_id: form.specialization_id || null,
        grade_id: form.grade_id || null,
        deadline: form.deadline || null,
      });
      toast.success("Development plan created");
      setCreateOpen(false);
      setForm(emptyForm);
      setSpecGrades([]);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create");
    } finally {
      setSaving(false);
    }
  }

  function openStatus(p: PDP) {
    setStatusTarget(p);
    setNewStatus(p.status);
    setStatusOpen(true);
  }

  async function handleStatus() {
    if (!statusTarget) return;
    setSaving(true);
    try {
      await api.post(`/pdp/${statusTarget.id}/status`, { status_code: newStatus });
      toast.success("Status updated");
      setStatusOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update status");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="py-12 text-center text-muted-foreground">Loading...</div>;

  const filters = { searchQuery, filterStatuses };
  // HRP-222: list order — active first (by Created desc), then Done by
  // ``finished_at``, then Cancelled by ``finished_at``.
  const filtered = sortPdpsForList(pdps.filter((p) => matchesPdpFilters(p, filters)));
  const filtersActive = hasActivePdpFilters(filters);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight" data-testid="development-heading">Development Plans</h1>
          {/* HRP-290: counter respects active filters (Assessments parity). */}
          <p className="text-sm text-muted-foreground" data-testid="development-count">{filtered.length} plan{filtered.length !== 1 ? "s" : ""}</p>
        </div>
        {canManage && (
          <Button size="sm" onClick={() => setCreateOpen(true)} data-testid="development-btn-create">
            <Plus className="mr-1 h-4 w-4" />
            Create plan
          </Button>
        )}
      </div>

      {/* Filters — HRP-147: parity with Assessments (search + multi-status,
          no type filter — PDPs do not have a type). */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            data-testid="development-input-search"
            placeholder="Search by title..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8"
          />
        </div>
        <MultiSelectFilter
          data-testid="development-multi-statuses"
          options={PDP_STATUS_OPTIONS.map((s) => ({ value: s, label: pdpStatusLabel(s) }))}
          value={filterStatuses}
          onChange={setFilterStatuses}
          placeholder="All statuses"
          className="w-40"
        />
        {filtersActive && (
          <Button
            data-testid="development-btn-clear-filters"
            variant="ghost"
            size="sm"
            onClick={() => { setSearchQuery(""); setFilterStatuses([]); }}
          >
            <X className="mr-1 h-3 w-3" />
            Clear
          </Button>
        )}
      </div>

      {pdps.length === 0 ? (
        <div className="rounded-lg border border-dashed p-12 text-center text-muted-foreground" data-testid="development-empty">No development plans yet</div>
      ) : filtered.length === 0 ? (
        <div className="rounded-lg border border-dashed p-12 text-center text-muted-foreground" data-testid="development-empty-filtered">No development plans match the filters</div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="development-table">
          {filtered.map((p) => {
            const showActions = canManage && !isTerminalPDPStatus(p.status);
            const deadlineOverdue = !!p.deadline && isPastDeadline(p.deadline);
            return (
              <Card key={p.id} className="relative cursor-pointer" data-testid={`development-row-${p.id}`} onClick={(e) => { if ((e.target as HTMLElement).closest("button, [role='menu'], [role='menuitem']")) return; router.push(`/development/${p.id}`); }}>
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm font-medium">
                      <Link href={`/development/${p.id}`} className="hover:underline" onClick={(e) => e.stopPropagation()} data-testid={`development-row-${p.id}-title`}>{p.title}</Link>
                    </CardTitle>
                    <div className="flex items-center gap-1">
                      <Badge variant="secondary" className={pdpStatusColor(p.status)} data-testid={`development-row-${p.id}-status`}>{pdpStatusLabel(p.status)}</Badge>
                      {showActions && (
                        <DropdownMenu>
                          <DropdownMenuTrigger render={<Button variant="ghost" size="icon-xs" data-testid={`development-row-${p.id}-actions`} />}>
                            <MoreHorizontal className="h-4 w-4" />
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => openStatus(p)}>Change status</DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {/* HRP-333: shared employee summary — name, current
                        position and a status chip when not active. */}
                    {p.employee_name && (
                      <EmployeeSummaryLine
                        employee={{
                          user_name: p.employee_name,
                          position_title: p.employee_position_title,
                          status: p.employee_status,
                        }}
                        data-testid={`development-row-${p.id}-employee`}
                      />
                    )}
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Progress</span>
                      <span className="font-medium">{p.total_progress}%</span>
                    </div>
                    <div className="h-2 rounded-full bg-muted" data-testid={`development-row-${p.id}-progress`}>
                      <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${p.total_progress}%` }} />
                    </div>
                    {/* HRP-132: for terminal plans (Completed / Cancelled)
                        we surface the date the plan was closed instead of
                        the (now-moot) deadline; ``finished_at`` is set on
                        both ``done`` and ``cancelled`` transitions. */}
                    {(() => {
                      if (p.status === "done" || p.status === "cancelled") {
                        if (!p.finished_at) return null;
                        const label = p.status === "done" ? "Completed at" : "Cancelled at";
                        return (
                          <p
                            className="text-xs text-muted-foreground"
                            data-testid={`development-row-${p.id}-finished-at`}
                          >
                            {label}: {formatDate(p.finished_at)}
                          </p>
                        );
                      }
                      return p.deadline ? (
                        <p
                          className={`text-xs ${deadlineOverdue ? "font-medium text-destructive" : "text-muted-foreground"}`}
                          data-testid={`development-row-${p.id}-deadline`}
                        >
                          Deadline: {formatDate(p.deadline)}
                        </p>
                      ) : null;
                    })()}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Create dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Create development plan</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Title</Label>
              <Input
                data-testid="development-create-title"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                placeholder="e.g. Senior Backend growth plan"
                maxLength={100}
              />
            </div>
            <div className="space-y-2">
              <Label>Employee</Label>
              <Select value={form.employee_id} onValueChange={(val) => handleEmployeeChange(val ?? "")}>
                <SelectTrigger className="w-full" data-testid="development-create-employee">
                  <SelectValue placeholder="Select employee">
                    {(() => { const emp = employees.find((e) => e.id === form.employee_id); return emp ? (emp.user_name?.trim() || emp.user_email || emp.position_title) : undefined; })()}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {employees.map((e) => (
                    <SelectItem key={e.id} value={e.id}>{e.user_name?.trim() || e.user_email || e.position_title}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Development specialization</Label>
              <Select
                value={form.specialization_id}
                onValueChange={(val) => handleSpecializationChange(val ?? "")}
              >
                <SelectTrigger className="w-full" data-testid="development-create-specialization">
                  <SelectValue placeholder="No specialization">
                    {specializations.find((s) => s.id === form.specialization_id)?.title}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {specOptions.map((s) => (
                    <SelectItem key={s.id} value={s.id}>{s.title}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Development grade</Label>
              {/* HRP-293: disabled until a specialization is chosen;
                  options are the specialization's configured grades. */}
              <Select
                value={form.grade_id}
                onValueChange={(val) => setForm({ ...form, grade_id: val ?? "" })}
                disabled={!form.specialization_id}
              >
                <SelectTrigger className="w-full" data-testid="development-create-grade">
                  <SelectValue
                    placeholder={
                      form.specialization_id
                        ? "No grade"
                        : "Select specialization first"
                    }
                  >
                    {specGrades.find((g) => g.id === form.grade_id)?.title}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {specGrades.map((g) => (
                    <SelectItem key={g.id} value={g.id}>{g.title}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Deadline</Label>
              {/* HRP-335: shared DatePicker (HRP-152) instead of the
                  native date input. */}
              <DatePicker
                min={todayLocalISO()}
                value={form.deadline}
                onChange={(value) => setForm({ ...form, deadline: value })}
                data-testid="development-create-deadline"
              />
              {isPastDeadline(form.deadline) && (
                <p className="text-xs text-destructive">Deadline cannot be in the past</p>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)} disabled={saving}>Cancel</Button>
            <Button onClick={handleCreate} disabled={saving}>{saving ? "Creating..." : "Create"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Status dialog — HRP-197: ``In progress`` is greyed out with the
          "Manual transition is not allowed" tooltip because that step only
          fires when the owner ticks an item from ``Sent``. */}
      <Dialog open={statusOpen} onOpenChange={setStatusOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Change status</DialogTitle></DialogHeader>
          <div className="space-y-2">
            <Label>New status</Label>
            <Select value={newStatus} onValueChange={setNewStatus}>
              <SelectTrigger className="w-full" data-testid="development-change-status-select">
                <SelectValue>{newStatus ? pdpStatusLabel(newStatus) : undefined}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {PDP_STATUS_OPTIONS.map((s) => {
                  const manualBlocked = isManualBlockedPDPStatus(s);
                  return (
                    <SelectItem
                      key={s}
                      value={s}
                      disabled={manualBlocked}
                      data-testid={`development-change-status-option-${s}`}
                    >
                      <span className="inline-flex items-center gap-1.5">
                        {pdpStatusLabel(s)}
                        {manualBlocked && (
                          // HRP-197 REDO: hover the (i) icon to see why
                          // the option is greyed out. The disabled
                          // SelectItem swallows pointer events on its own
                          // children, so the icon lives inside a
                          // pointer-events-auto span that overrides it.
                          <Tooltip>
                            <TooltipTrigger
                              render={
                                <span
                                  className="pointer-events-auto inline-flex"
                                  data-testid={`development-change-status-option-${s}-info`}
                                  aria-label="Manual transition is not allowed"
                                  onPointerDown={(e) => e.stopPropagation()}
                                  onClick={(e) => e.preventDefault()}
                                />
                              }
                            >
                              <Info className="h-3 w-3 text-muted-foreground" />
                            </TooltipTrigger>
                            <TooltipContent>
                              Manual transition is not allowed
                            </TooltipContent>
                          </Tooltip>
                        )}
                      </span>
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
            {isManualBlockedPDPStatus(newStatus) && (
              <p
                className="text-xs text-muted-foreground"
                data-testid="development-change-status-blocked-hint"
              >
                Manual transition is not allowed
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setStatusOpen(false)} disabled={saving}>Cancel</Button>
            <Button
              onClick={handleStatus}
              disabled={saving || isManualBlockedPDPStatus(newStatus)}
            >
              {saving ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
