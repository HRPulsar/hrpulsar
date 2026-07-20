"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type {
  AssessmentGroupDetail,
  DictionaryItem,
  Division,
  Employee,
  EmployeeList,
  PositionList,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DatePicker } from "@/components/ui/date-picker";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
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
import { Checkbox } from "@/components/ui/checkbox";
import { toast } from "sonner";
import { ArrowLeft, ArrowRight, Users } from "lucide-react";
import { isPastDeadline, todayLocalISO } from "@/lib/deadline";
import { formatDate } from "@/lib/date-format";

const typeOptions = [
  { value: "self", label: "Self assessment" },
  { value: "180", label: "180°" },
  { value: "360", label: "360°" },
];

interface MassCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}

export function MassCreateDialog({
  open,
  onOpenChange,
  onCreated,
}: MassCreateDialogProps) {
  const [step, setStep] = useState(1);
  const [saving, setSaving] = useState(false);

  // Step 1: basic info
  const [title, setTitle] = useState("");
  const [typeCode, setTypeCode] = useState("360");
  const [endedAt, setEndedAt] = useState("");

  // Step 2: employee selection
  const [divisions, setDivisions] = useState<Division[]>([]);
  const [positions, setPositions] = useState<{ id: string; title: string }[]>([]);
  const [specializations, setSpecializations] = useState<DictionaryItem[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loadingEmployees, setLoadingEmployees] = useState(false);

  const [filterDivision, setFilterDivision] = useState("");
  const [filterPosition, setFilterPosition] = useState("");
  const [filterSpecialization, setFilterSpecialization] = useState("");

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Load filter options on open
  useEffect(() => {
    if (!open) return;
    Promise.all([
      api.get<Division[]>("/divisions").catch(() => []),
      // HRP-225: /employees/positions was removed with the structured
      // Position entity — filter by position id via /positions instead.
      api
        .get<PositionList>("/positions?limit=500&is_active=true")
        .then((r) => r.items.map((p) => ({ id: p.id, title: p.title })))
        .catch(() => []),
      api.get<DictionaryItem[]>("/dictionaries/specialization").catch(() => []),
    ]).then(([divs, pos, specs]) => {
      setDivisions(divs);
      setPositions(pos);
      setSpecializations(specs);
    });
  }, [open]);

  // Load employees when filters change. The sequence guard drops stale
  // responses so select-all never acts on a superseded filter's cohort.
  const reqSeq = useRef(0);
  const loadEmployees = useCallback(async () => {
    const seq = ++reqSeq.current;
    setLoadingEmployees(true);
    try {
      const params = new URLSearchParams();
      params.set("status", "active");
      params.set("limit", "100");
      if (filterDivision) params.set("division_id", filterDivision);
      if (filterPosition) params.set("position_id", filterPosition);
      if (filterSpecialization)
        params.set("specialization_id", filterSpecialization);
      const data = await api.get<EmployeeList>(`/employees?${params}`);
      if (seq !== reqSeq.current) return;
      setEmployees(data.items);
    } catch {
      // ignore
    } finally {
      if (seq === reqSeq.current) setLoadingEmployees(false);
    }
  }, [filterDivision, filterPosition, filterSpecialization]);

  useEffect(() => {
    if (open && step === 2) {
      loadEmployees();
    }
  }, [open, step, loadEmployees]);

  function reset() {
    setStep(1);
    setTitle("");
    setTypeCode("360");
    setEndedAt("");
    setFilterDivision("");
    setFilterPosition("");
    setFilterSpecialization("");
    setSelectedIds(new Set());
    setEmployees([]);
  }

  function handleClose(val: boolean) {
    if (!val) reset();
    onOpenChange(val);
  }

  function toggleEmployee(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    const allVisible = employees.map((e) => e.id);
    const allSelected = allVisible.every((id) => selectedIds.has(id));
    if (allSelected) {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        allVisible.forEach((id) => next.delete(id));
        return next;
      });
    } else {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        allVisible.forEach((id) => next.add(id));
        return next;
      });
    }
  }

  async function handleCreate() {
    if (isPastDeadline(endedAt)) {
      toast.error("Deadline cannot be in the past");
      return;
    }
    setSaving(true);
    try {
      // HRP-37: backend partial-create surfaces created_count vs
      // requested_count so we can render a `Created M of N` snackbar
      // when some employees were at the active-assessment cap. If
      // everyone was capped the API returns 409 and we land in catch.
      const result = await api.post<AssessmentGroupDetail>("/assessment-groups", {
        title,
        employee_ids: Array.from(selectedIds),
        type_code: typeCode,
        ended_at: endedAt || null,
      });
      const created = result.created_count ?? selectedIds.size;
      const requested = result.requested_count ?? selectedIds.size;
      const capped = result.skipped_capped_count ?? 0;
      if (capped > 0) {
        toast.success(
          `Created ${created} of ${requested} assessments — ${capped} employee${
            capped === 1 ? "" : "s"
          } already at the active cap`,
        );
      } else {
        toast.success(`Created ${created} assessments`);
      }
      handleClose(false);
      onCreated();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create");
    } finally {
      setSaving(false);
    }
  }

  const allVisibleSelected =
    employees.length > 0 &&
    employees.every((e) => selectedIds.has(e.id));

  // Flatten division tree for dropdown
  function flattenDivisions(divs: Division[], depth = 0): { id: string; name: string; depth: number }[] {
    const result: { id: string; name: string; depth: number }[] = [];
    for (const d of divs) {
      result.push({ id: d.id, name: d.name, depth });
      if (d.children?.length) {
        result.push(...flattenDivisions(d.children, depth + 1));
      }
    }
    return result;
  }

  const flatDivisions = flattenDivisions(divisions);

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-lg" data-testid="assessments-modal-mass-create">
        <DialogHeader>
          <DialogTitle>
            {step === 1 && "Mass assessment — Settings"}
            {step === 2 && "Mass assessment — Select employees"}
            {step === 3 && "Mass assessment — Confirm"}
          </DialogTitle>
        </DialogHeader>

        {step === 1 && (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Title</Label>
              <Input
                data-testid="assessments-mass-input-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Q2 2026 360° Review"
                maxLength={100}
              />
            </div>
            <div className="space-y-2">
              <Label>Type</Label>
              <Select value={typeCode} onValueChange={setTypeCode}>
                <SelectTrigger className="w-full" data-testid="assessments-mass-select-type">
                  <SelectValue>
                    {typeOptions.find((t) => t.value === typeCode)?.label ?? ""}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {typeOptions.map((t) => (
                    <SelectItem key={t.value} value={t.value}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>End date</Label>
              {/* HRP-335: shared DatePicker (HRP-152) instead of the
                  native date input. */}
              <DatePicker
                data-testid="assessments-mass-input-end-date"
                min={todayLocalISO()}
                value={endedAt}
                onChange={setEndedAt}
              />
              {isPastDeadline(endedAt) && (
                <p className="text-xs text-destructive">Deadline cannot be in the past</p>
              )}
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            {/* Filters */}
            <div className="grid grid-cols-3 gap-2">
              <Select value={filterDivision} onValueChange={setFilterDivision}>
                <SelectTrigger className="w-full" data-testid="assessments-mass-select-division">
                  <SelectValue placeholder="Division">
                    {filterDivision
                      ? flatDivisions.find((d) => d.id === filterDivision)?.name
                      : undefined}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">All divisions</SelectItem>
                  {flatDivisions.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {"  ".repeat(d.depth)}{d.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={filterPosition} onValueChange={setFilterPosition}>
                <SelectTrigger className="w-full" data-testid="assessments-mass-select-position">
                  <SelectValue placeholder="Position">
                    {filterPosition
                      ? positions.find((p) => p.id === filterPosition)?.title
                      : undefined}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">All positions</SelectItem>
                  {positions.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={filterSpecialization}
                onValueChange={setFilterSpecialization}
              >
                <SelectTrigger className="w-full" data-testid="assessments-mass-select-specialization">
                  <SelectValue placeholder="Specialization">
                    {filterSpecialization
                      ? specializations.find((s) => s.id === filterSpecialization)?.title
                      : undefined}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">All</SelectItem>
                  {specializations.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Select all + employee list */}
            <div className="rounded-md border">
              <div className="flex items-center gap-2 border-b px-3 py-2">
                <Checkbox
                  data-testid="assessments-mass-checkbox-select-all"
                  checked={allVisibleSelected}
                  disabled={loadingEmployees || employees.length === 0}
                  onCheckedChange={toggleAll}
                />
                <span className="text-sm text-muted-foreground">
                  Select all ({employees.length})
                </span>
              </div>
              <div className="max-h-56 overflow-y-auto">
                {loadingEmployees ? (
                  <div className="py-6 text-center text-sm text-muted-foreground">
                    Loading...
                  </div>
                ) : employees.length === 0 ? (
                  <div className="py-6 text-center text-sm text-muted-foreground">
                    No employees match filters
                  </div>
                ) : (
                  employees.map((e) => (
                    <label
                      key={e.id}
                      className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-muted"
                    >
                      <Checkbox
                        checked={selectedIds.has(e.id)}
                        onCheckedChange={() => toggleEmployee(e.id)}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">
                          {e.user_name?.trim() || e.user_email || "—"}
                        </div>
                        <div className="truncate text-xs text-muted-foreground">
                          {[e.position_title, e.division_name]
                            .filter(Boolean)
                            .join(" · ")}
                        </div>
                      </div>
                    </label>
                  ))
                )}
              </div>
            </div>

            {selectedIds.size > 0 && (
              <p className="text-sm font-medium">
                {selectedIds.size} employee{selectedIds.size !== 1 ? "s" : ""}{" "}
                selected
              </p>
            )}
          </div>
        )}

        {step === 3 && (
          <div className="space-y-3">
            <div className="rounded-md border p-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Title</span>
                <span className="text-sm font-medium">{title || "Untitled"}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Type</span>
                <Badge variant="secondary">
                  {typeOptions.find((t) => t.value === typeCode)?.label}
                </Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Employees</span>
                <span className="text-sm font-medium flex items-center gap-1">
                  <Users className="h-3.5 w-3.5" />
                  {selectedIds.size}
                </span>
              </div>
              {endedAt && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">End date</span>
                  <span className="text-sm">
                    {formatDate(endedAt)}
                  </span>
                </div>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              This will create {selectedIds.size} individual assessments grouped
              together.
            </p>
          </div>
        )}

        <DialogFooter className="gap-2">
          {step > 1 && (
            <Button
              variant="outline"
              onClick={() => setStep(step - 1)}
              disabled={saving}
            >
              <ArrowLeft className="mr-1 h-4 w-4" />
              Back
            </Button>
          )}
          <div className="flex-1" />
          {step === 1 && (
            <Button data-testid="assessments-mass-btn-next-1" onClick={() => setStep(2)} disabled={!title.trim()}>
              Next
              <ArrowRight className="ml-1 h-4 w-4" />
            </Button>
          )}
          {step === 2 && (
            <Button
              data-testid="assessments-mass-btn-next-2"
              onClick={() => setStep(3)}
              disabled={selectedIds.size === 0}
            >
              Next ({selectedIds.size})
              <ArrowRight className="ml-1 h-4 w-4" />
            </Button>
          )}
          {step === 3 && (
            <Button data-testid="assessments-mass-btn-submit" onClick={handleCreate} disabled={saving}>
              {saving
                ? "Creating..."
                : `Create ${selectedIds.size} assessments`}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
