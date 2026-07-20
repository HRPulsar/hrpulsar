"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { flattenTree } from "@/lib/utils";
import type {
  AssessmentList,
  DictionaryItem,
  Division,
  Employee,
  EmployeeList,
  Position,
  PositionList,
} from "@/lib/types";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PositionCombobox } from "@/components/position-combobox";
import { DatePicker } from "@/components/ui/date-picker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MultiSelectFilter } from "@/components/multi-select-filter";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { FieldError, FormErrorBanner } from "@/components/ui/form-error";
import {
  EMPTY_FORM_ERROR,
  parseFormError,
  type FormErrorState,
} from "@/lib/form-errors";
import { Pagination } from "@/components/pagination";
import { usePermissions } from "@/hooks/use-permissions";
import { toast } from "sonner";
import Link from "next/link";
import { CheckCircle, MoreHorizontal, Pencil, Plus, Search, Trash2, Upload, X } from "lucide-react";
import { BADGE_COLOR } from "@/lib/badge-tones";

const PAGE_SIZE = 20;

const statusColors: Record<string, string> = {
  active: BADGE_COLOR.green,
  inactive: BADGE_COLOR.neutral,
  on_leave: BADGE_COLOR.yellow,
  terminated: BADGE_COLOR.red,
};

const statusOptions = ["active", "inactive", "on_leave", "terminated"];

const FILTER_KEYS = [
  "division_id",
  "status",
  "position_id",
  "specialization_id",
  "grade_id",
] as const;

type FilterKey = (typeof FILTER_KEYS)[number];

type Filters = Record<FilterKey, string[]>;

const emptyFilters: Filters = {
  division_id: [],
  status: [],
  position_id: [],
  specialization_id: [],
  grade_id: [],
};

interface DivisionScopeItem {
  id: string;
  name: string;
}

const emptyCreateForm = {
  user_id: "",
  division_id: "",
  position_id: "",
  hire_date: "",
};

const emptyEditForm = {
  first_name: "",
  last_name: "",
  division_id: "",
  position_id: "",
  status: "",
};

function readFiltersFromQuery(params: URLSearchParams): Filters {
  const next: Filters = { ...emptyFilters };
  for (const key of FILTER_KEYS) {
    const values = params.getAll(key).filter(Boolean);
    next[key] = values;
  }
  return next;
}

function buildQuery(page: number, filters: Filters, search: string): string {
  const params = new URLSearchParams();
  params.set("page", String(page));
  if (search) params.set("q", search);
  for (const key of FILTER_KEYS) {
    for (const v of filters[key]) params.append(key, v);
  }
  return params.toString();
}

function formatSpecGrade(
  specialization: string | null,
  grade: string | null,
): string {
  if (specialization && grade) return `${specialization} · ${grade}`;
  return specialization ?? grade ?? "—";
}

function buildBackendQuery(
  page: number,
  filters: Filters,
  search: string,
): URLSearchParams {
  const params = new URLSearchParams();
  params.set("skip", String((page - 1) * PAGE_SIZE));
  params.set("limit", String(PAGE_SIZE));
  const trimmed = search.trim();
  if (trimmed) params.set("q", trimmed);
  for (const key of FILTER_KEYS) {
    for (const v of filters[key]) params.append(key, v);
  }
  return params;
}

export default function EmployeesPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [employees, setEmployees] = useState<Employee[]>([]);
  const [total, setTotal] = useState(0);
  const [divisions, setDivisions] = useState<Division[]>([]);
  const [scopedDivisions, setScopedDivisions] = useState<DivisionScopeItem[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [specializations, setSpecializations] = useState<DictionaryItem[]>([]);
  const [grades, setGrades] = useState<DictionaryItem[]>([]);
  const [assessedEmployees, setAssessedEmployees] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);

  const initialFilters = useMemo(
    () => readFiltersFromQuery(new URLSearchParams(searchParams.toString())),
    // run once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const initialSearch = searchParams.get("q") ?? "";
  const initialPage = Math.max(1, Number(searchParams.get("page") ?? "1") || 1);

  const [filters, setFilters] = useState<Filters>(initialFilters);
  const [searchQuery, setSearchQuery] = useState(initialSearch);
  const [debouncedSearch, setDebouncedSearch] = useState(initialSearch);
  const [page, setPage] = useState(initialPage);

  // Create
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState(emptyCreateForm);
  const [createError, setCreateError] = useState<FormErrorState>(EMPTY_FORM_ERROR);
  const [editError, setEditError] = useState<FormErrorState>(EMPTY_FORM_ERROR);
  const [availableUsers, setAvailableUsers] = useState<{ id: string; email: string; first_name: string; last_name: string; origin: string }[]>([]);

  // Edit
  const [editOpen, setEditOpen] = useState(false);
  const [editForm, setEditForm] = useState(emptyEditForm);
  const [editingId, setEditingId] = useState<string | null>(null);

  // Delete
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletingEmp, setDeletingEmp] = useState<Employee | null>(null);

  const [saving, setSaving] = useState(false);

  const { canManage } = usePermissions();

  // HRP-120: search is debounced and can fire overlapping requests. Track
  // the latest call with a monotonic token so an older response can't
  // overwrite a fresher one when it lands out of order.
  const loadRequestId = useRef(0);

  const loadEmployees = useCallback(
    async (p: number, f: Filters, search: string) => {
      const requestId = ++loadRequestId.current;
      try {
        const params = buildBackendQuery(p, f, search);
        const empData = await api.get<EmployeeList>(`/employees?${params}`);
        if (loadRequestId.current !== requestId) return;
        setEmployees(empData.items);
        setTotal(empData.total);
      } catch {
        // ignore
      }
    },
    [],
  );

  const loadMeta = useCallback(async () => {
    try {
      const [divData, scopeData, posData, specData, gradeData, asmtData] =
        await Promise.all([
          api.get<Division[]>("/divisions"),
          api
            .get<DivisionScopeItem[]>("/divisions/scope")
            .catch(() => [] as DivisionScopeItem[]),
          api
            .get<PositionList>("/positions?limit=200")
            .catch(() => ({ items: [], total: 0 }) as PositionList),
          api
            .get<DictionaryItem[]>("/dictionaries/specialization")
            .catch(() => [] as DictionaryItem[]),
          api
            .get<DictionaryItem[]>("/dictionaries/grade")
            .catch(() => [] as DictionaryItem[]),
          api.get<AssessmentList>("/assessments?limit=100"),
        ]);
      setDivisions(divData);
      setScopedDivisions(scopeData);
      setPositions(posData.items);
      setSpecializations(specData);
      setGrades(gradeData);
      const done = new Set(
        asmtData.items.filter((a) => a.status_code === "done").map((a) => a.employee_id),
      );
      setAssessedEmployees(done);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadMeta().finally(() => setLoading(false));
  }, [loadMeta]);

  useEffect(() => {
    loadEmployees(page, filters, debouncedSearch);
  }, [page, filters, debouncedSearch, loadEmployees]);

  // HRP-120: debounce the search input so typing doesn't fire a request per
  // keystroke; resetting to page 1 keeps results aligned with the query.
  useEffect(() => {
    if (searchQuery === debouncedSearch) return;
    const handle = window.setTimeout(() => {
      setDebouncedSearch(searchQuery);
      setPage(1);
    }, 250);
    return () => window.clearTimeout(handle);
  }, [searchQuery, debouncedSearch]);

  // Sync URL when filters / page / search change
  useEffect(() => {
    const qs = buildQuery(page, filters, debouncedSearch);
    const current = searchParams.toString();
    if (qs !== current) {
      router.replace(`/employees?${qs}`, { scroll: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, filters, debouncedSearch]);

  const flatDivisions = useMemo(() => flattenTree(divisions), [divisions]);

  // Use scoped list for the filter (manager → only own subtree),
  // but fall back to the full tree for admins/hr (scope endpoint returns all).
  const divisionFilterOptions = useMemo(
    () =>
      scopedDivisions.length > 0
        ? scopedDivisions
            .map((d) => ({ value: d.id, label: d.name }))
            .sort((a, b) => a.label.localeCompare(b.label))
        : flatDivisions.map((d) => ({
            value: d.id,
            label: `${"—".repeat(d.depth)} ${d.name}`.trim(),
          })),
    [scopedDivisions, flatDivisions],
  );

  const statusFilterOptions = useMemo(
    () => statusOptions.map((s) => ({ value: s, label: s })),
    [],
  );

  const positionFilterOptions = useMemo(
    () =>
      positions
        .map((p) => ({ value: p.id, label: p.title }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [positions],
  );

  const specializationFilterOptions = useMemo(
    () =>
      specializations
        .map((s) => ({ value: s.id, label: s.title }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [specializations],
  );

  const gradeFilterOptions = useMemo(
    () =>
      grades
        .map((g) => ({ value: g.id, label: g.title }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [grades],
  );

  // HRP-120: the server applies the q filter, so the page already arrives
  // pre-filtered. No client-side narrowing here — otherwise hits outside the
  // current page would be invisible (the original bug).
  const filtered = employees;

  function updateFilter(key: FilterKey, next: string[]) {
    setFilters((prev) => ({ ...prev, [key]: next }));
    setPage(1);
  }

  function clearFilters() {
    setSearchQuery("");
    setDebouncedSearch("");
    setFilters(emptyFilters);
    setPage(1);
  }

  const hasFilters =
    Boolean(searchQuery) ||
    FILTER_KEYS.some((k) => filters[k].length > 0);

  async function loadAvailableUsers() {
    try {
      const users = await api.get<{ id: string; email: string; first_name: string; last_name: string; origin: string }[]>("/employees/available-users");
      setAvailableUsers(users);
    } catch {
      setAvailableUsers([]);
    }
  }

  async function handleCreate() {
    setSaving(true);
    setCreateError(EMPTY_FORM_ERROR);
    try {
      await api.post("/employees", {
        user_id: createForm.user_id,
        position_id: createForm.position_id || null,
        division_id: createForm.division_id || null,
        hire_date: createForm.hire_date,
      });
      toast.success("Employee created");
      setCreateOpen(false);
      setCreateForm(emptyCreateForm);
      await loadEmployees(page, filters, debouncedSearch);
    } catch (err) {
      setCreateError(
        parseFormError(err, ["user_id", "position_id", "division_id", "hire_date"]),
      );
    } finally {
      setSaving(false);
    }
  }

  function openEdit(emp: Employee) {
    // HRP-121: split the cached user_name back into first/last for the form.
    // The list endpoint only returns the concatenated string, so we make a
    // best-effort split — anything after the first space is treated as last
    // name. Users with multi-word first names can fix the split inline.
    const fullName = emp.user_name || "";
    const firstSpace = fullName.indexOf(" ");
    const firstName =
      firstSpace === -1 ? fullName : fullName.slice(0, firstSpace);
    const lastName =
      firstSpace === -1 ? "" : fullName.slice(firstSpace + 1);
    setEditForm({
      first_name: firstName,
      last_name: lastName,
      division_id: emp.division_id || "",
      position_id: emp.position_id || "",
      status: emp.status,
    });
    setEditingId(emp.id);
    setEditError(EMPTY_FORM_ERROR);
    setEditOpen(true);
  }

  async function handleEdit() {
    const firstName = editForm.first_name.trim();
    const lastName = editForm.last_name.trim();
    if (!firstName || !lastName) {
      toast.error("Name and Last name are required");
      return;
    }
    setSaving(true);
    setEditError(EMPTY_FORM_ERROR);
    try {
      await api.put(`/employees/${editingId}`, {
        first_name: firstName,
        last_name: lastName,
        position_id: editForm.position_id || null,
        division_id: editForm.division_id || null,
        status: editForm.status || undefined,
      });
      toast.success("Employee updated");
      setEditOpen(false);
      await loadEmployees(page, filters, debouncedSearch);
    } catch (err) {
      setEditError(parseFormError(err));
    } finally {
      setSaving(false);
    }
  }

  function openDelete(emp: Employee) {
    setDeletingEmp(emp);
    setDeleteOpen(true);
  }

  async function confirmDelete() {
    if (!deletingEmp) return;
    setSaving(true);
    try {
      await api.delete(`/employees/${deletingEmp.id}`);
      toast.success("Employee deleted");
      setDeleteOpen(false);
      await loadEmployees(page, filters, debouncedSearch);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div data-testid="employees-loading" className="flex items-center justify-center py-12 text-muted-foreground">
        Loading...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Employees</h1>
          <p className="text-sm text-muted-foreground">
            {total} employee{total !== 1 ? "s" : ""} total
          </p>
        </div>
        {canManage && (
          <div className="flex items-center gap-2">
            <Button data-testid="employees-btn-import" variant="outline" size="sm" render={<Link href="/settings/import" />}>
              <Upload className="mr-1 h-4 w-4" />
              Import
            </Button>
            <Button data-testid="employees-btn-create" size="sm" onClick={() => { loadAvailableUsers(); setCreateError(EMPTY_FORM_ERROR); setCreateOpen(true); }}>
              <Plus className="mr-1 h-4 w-4" />
              Add employee
            </Button>
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            data-testid="employees-input-search"
            placeholder="Search by name or email..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8"
          />
        </div>
        <MultiSelectFilter
          data-testid="employees-multi-divisions"
          options={divisionFilterOptions}
          value={filters.division_id}
          onChange={(next) => updateFilter("division_id", next)}
          placeholder="Divisions"
          className="w-44"
        />
        <MultiSelectFilter
          data-testid="employees-multi-statuses"
          options={statusFilterOptions}
          value={filters.status}
          onChange={(next) => updateFilter("status", next)}
          placeholder="Statuses"
          className="w-36"
        />
        <MultiSelectFilter
          data-testid="employees-multi-positions"
          options={positionFilterOptions}
          value={filters.position_id}
          onChange={(next) => updateFilter("position_id", next)}
          placeholder="Positions"
          className="w-44"
        />
        <MultiSelectFilter
          data-testid="employees-multi-specializations"
          options={specializationFilterOptions}
          value={filters.specialization_id}
          onChange={(next) => updateFilter("specialization_id", next)}
          placeholder="Specializations"
          className="w-44"
        />
        <MultiSelectFilter
          data-testid="employees-multi-grades"
          options={gradeFilterOptions}
          value={filters.grade_id}
          onChange={(next) => updateFilter("grade_id", next)}
          placeholder="Grades"
          className="w-36"
        />
        {hasFilters && (
          <Button data-testid="employees-btn-clear-filters" variant="ghost" size="sm" onClick={clearFilters}>
            <X className="mr-1 h-3 w-3" />
            Clear
          </Button>
        )}
      </div>

      {filtered.length === 0 ? (
        <div data-testid="employees-empty" className="rounded-lg border border-dashed p-12 text-center text-muted-foreground">
          {hasFilters ? "No employees match the filters" : "No employees yet"}
        </div>
      ) : (
        <>
          <div className="rounded-lg border">
            <Table data-testid="employees-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Division</TableHead>
                  <TableHead>Position</TableHead>
                  <TableHead>Specialization · Grade</TableHead>
                  <TableHead>Status</TableHead>
                  {canManage && <TableHead className="w-10" />}
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((emp) => (
                  <TableRow key={emp.id} data-testid={`employees-row-${emp.id}`}>
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        <Avatar className="h-6 w-6" size="sm">
                          {emp.avatar_url && <AvatarImage src={emp.avatar_url} />}
                          <AvatarFallback className="text-[10px]">
                            {emp.user_name ? emp.user_name.split(" ").map((n: string) => n[0]).join("").toUpperCase().slice(0, 2) : "?"}
                          </AvatarFallback>
                        </Avatar>
                        <div className="flex flex-col leading-tight">
                          <Link
                            data-testid={`employees-row-${emp.id}-name`}
                            href={`/employees/${emp.id}`}
                            className="hover:underline"
                          >
                            {emp.user_name || "—"}
                          </Link>
                          <span
                            data-testid={`employees-row-${emp.id}-email`}
                            className="text-xs text-muted-foreground"
                          >
                            {emp.user_email || "—"}
                          </span>
                        </div>
                        {assessedEmployees.has(emp.id) && (
                          <span title="Assessment completed">
                            <CheckCircle className="h-3.5 w-3.5 text-green-600" />
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>{emp.division_name || "—"}</TableCell>
                    <TableCell>{emp.position_title || "—"}</TableCell>
                    <TableCell
                      data-testid={`employees-row-${emp.id}-spec-grade`}
                      className="text-muted-foreground"
                    >
                      {formatSpecGrade(emp.specialization_title, emp.grade_title)}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="secondary"
                        className={statusColors[emp.status] || ""}
                      >
                        {emp.status}
                      </Badge>
                    </TableCell>
                    {canManage && (
                      <TableCell>
                        <DropdownMenu>
                          <DropdownMenuTrigger data-testid={`employees-row-${emp.id}-actions`} render={<Button variant="ghost" size="icon-xs" />}>
                            <MoreHorizontal className="h-4 w-4" />
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem data-testid={`employees-row-${emp.id}-btn-edit`} onClick={() => openEdit(emp)}>
                              <Pencil className="mr-2 h-4 w-4" />
                              Edit
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              data-testid={`employees-row-${emp.id}-btn-delete`}
                              variant="destructive"
                              onClick={() => openDelete(emp)}
                            >
                              <Trash2 className="mr-2 h-4 w-4" />
                              Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </>
      )}

      {/* Create dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent data-testid="employees-modal-create">
          <DialogHeader>
            <DialogTitle>Add employee</DialogTitle>
          </DialogHeader>
          <FormErrorBanner
            message={createError.message}
            testId="employees-modal-create-error"
          />
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>User</Label>
              <Select
                value={createForm.user_id}
                onValueChange={(val) =>
                  setCreateForm({ ...createForm, user_id: val })
                }
              >
                <SelectTrigger data-testid="employees-modal-create-select-user" className="w-full">
                  <SelectValue placeholder="Select user">
                    {(() => { if (!createForm.user_id) return undefined; const u = availableUsers.find((u) => u.id === createForm.user_id); return u ? `${u.first_name} ${u.last_name} (${u.email})` : undefined; })()}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {availableUsers.length === 0 && (
                    <div className="px-2 py-4 text-center text-sm text-muted-foreground">
                      No available users
                    </div>
                  )}
                  {availableUsers.map((u) => (
                    <SelectItem key={u.id} value={u.id}>
                      <span className="flex items-center gap-2">
                        {u.first_name} {u.last_name} ({u.email})
                        <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                          {u.origin === "invited" ? "invited" : "self-registered"}
                        </Badge>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FieldError
                message={createError.fields.user_id}
                testId="employees-modal-create-error-user-id"
              />
            </div>
            <div className="space-y-2">
              <Label>Position</Label>
              <PositionCombobox
                data-testid="employees-modal-create-input-position"
                value={createForm.position_id || null}
                onValueChange={(id) =>
                  setCreateForm({ ...createForm, position_id: id || "" })
                }
              />
              <FieldError
                message={createError.fields.position_id}
                testId="employees-modal-create-error-position"
              />
            </div>
            <div className="space-y-2">
              <Label>Division</Label>
              <Select
                data-testid="employees-modal-create-select-division"
                value={createForm.division_id}
                onValueChange={(val) =>
                  setCreateForm({ ...createForm, division_id: val })
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="No division">
                    {(() => { if (!createForm.division_id) return undefined; const d = flatDivisions.find((d) => d.id === createForm.division_id); return d ? `${"—".repeat(d.depth)} ${d.name}` : undefined; })()}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">No division</SelectItem>
                  {flatDivisions.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {"—".repeat(d.depth)} {d.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FieldError
                message={createError.fields.division_id}
                testId="employees-modal-create-error-division"
              />
            </div>
            <div className="space-y-2">
              <Label>Hire date</Label>
              <DatePicker
                data-testid="employees-modal-create-input-hire-date"
                value={createForm.hire_date}
                onChange={(value) =>
                  setCreateForm({ ...createForm, hire_date: value })
                }
              />
              <FieldError
                message={createError.fields.hire_date}
                testId="employees-modal-create-error-hire-date"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              data-testid="employees-modal-create-btn-cancel"
              variant="outline"
              onClick={() => setCreateOpen(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button data-testid="employees-modal-create-btn-submit" onClick={handleCreate} disabled={saving}>
              {saving ? "Creating..." : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit dialog */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent data-testid="employees-modal-edit">
          <DialogHeader>
            <DialogTitle>Edit employee</DialogTitle>
          </DialogHeader>
          <FormErrorBanner
            message={editError.message}
            testId="employees-modal-edit-error"
          />
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label>Name</Label>
                <Input
                  data-testid="employees-modal-edit-input-first-name"
                  value={editForm.first_name}
                  onChange={(e) =>
                    setEditForm({ ...editForm, first_name: e.target.value })
                  }
                  maxLength={100}
                />
              </div>
              <div className="space-y-2">
                <Label>Last name</Label>
                <Input
                  data-testid="employees-modal-edit-input-last-name"
                  value={editForm.last_name}
                  onChange={(e) =>
                    setEditForm({ ...editForm, last_name: e.target.value })
                  }
                  maxLength={100}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>Position</Label>
              <PositionCombobox
                data-testid="employees-modal-edit-input-position"
                value={editForm.position_id || null}
                onValueChange={(id) =>
                  setEditForm({ ...editForm, position_id: id || "" })
                }
              />
            </div>
            <div className="space-y-2">
              <Label>Division</Label>
              <Select
                data-testid="employees-modal-edit-select-division"
                value={editForm.division_id}
                onValueChange={(val) =>
                  setEditForm({ ...editForm, division_id: val })
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="No division">
                    {(() => { if (!editForm.division_id) return undefined; const d = flatDivisions.find((d) => d.id === editForm.division_id); return d ? `${"—".repeat(d.depth)} ${d.name}` : undefined; })()}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">No division</SelectItem>
                  {flatDivisions.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {"—".repeat(d.depth)} {d.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Status</Label>
              <Select
                data-testid="employees-modal-edit-select-status"
                value={editForm.status}
                onValueChange={(val) =>
                  setEditForm({ ...editForm, status: val })
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {statusOptions.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button
              data-testid="employees-modal-edit-btn-cancel"
              variant="outline"
              onClick={() => setEditOpen(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button data-testid="employees-modal-edit-btn-submit" onClick={handleEdit} disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation */}
      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Delete employee"
        description={`Are you sure you want to delete ${deletingEmp?.user_name || "this employee"}? This action cannot be undone.`}
        onConfirm={confirmDelete}
        loading={saving}
      />
    </div>
  );
}
