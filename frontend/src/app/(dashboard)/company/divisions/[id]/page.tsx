"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { flattenTree } from "@/lib/utils";
import { formatDate } from "@/lib/date-format";
import type {
  Division,
  Employee,
  EmployeeList as EmployeeListResponse,
  PendingRoleDowngrade,
  PositionList as PositionListResponse,
  SpecializationDivision,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  EmployeeList,
  type EmployeeListItem,
} from "@/components/employees/EmployeeListRow";
import { AddEmployeeDialog } from "@/components/employees/AddEmployeeDialog";
import type { Position } from "@/lib/types";
import {
  EMPTY_FILTERS,
  activeFilterCount,
  applyDivisionFilters,
  deriveGradeOptions,
  derivePositionOptions,
  hasActiveDivisionFilters,
  type DivisionEmployeeFilters,
} from "@/lib/division-employee-filters";
import { usePermissions } from "@/hooks/use-permissions";
import { ArrowLeft, Pencil, Users, X } from "lucide-react";
import { toast } from "sonner";

const emptyDivisionForm = {
  name: "",
  description: "",
  parent_id: "",
  manager_id: "",
  deputy_manager_id: "",
};

// HRP-59: Base UI's <Select.Value> falls back to serializing the raw
// `value` (a UUID) when the children expression returns `undefined`
// AND no rendered `<SelectItem>` matches it — which happens before the
// dropdown is opened. Always returning a string from the children
// keeps the trigger label readable even when the employees list is
// still loading or has been trimmed by API pagination.
function employeeLabel(
  id: string,
  employees: Employee[],
  fallback: string | null | undefined,
  noneLabel: string,
): string {
  if (!id) return noneLabel;
  const emp = employees.find((e) => e.id === id);
  if (emp) return emp.user_name?.trim() || emp.user_email || "—";
  return fallback?.trim() || "—";
}

export default function DivisionDetailPage() {
  const t = useTranslations("company");
  const tc = useTranslations("common");
  const { id } = useParams<{ id: string }>();
  const { canManage } = usePermissions();
  const [division, setDivision] = useState<Division | null>(null);
  const [allDivisions, setAllDivisions] = useState<Division[]>([]);
  const [allEmployees, setAllEmployees] = useState<Employee[]>([]);
  const [specializations, setSpecializations] = useState<SpecializationDivision[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  // HRP-58: filter state for the Employees block. Specialization plates
  // already wrote to `filterSpecId` — keep the same path but extend with
  // position + grade (AND-combined). The filters object is opaque to the
  // page, so the matcher / option deriver live in a tiny pure module.
  const [filters, setFilters] = useState<DivisionEmployeeFilters>(EMPTY_FILTERS);
  const filterSpecId = filters.specializationId;
  const [editOpen, setEditOpen] = useState(false);
  const [editForm, setEditForm] = useState(emptyDivisionForm);
  const [saving, setSaving] = useState(false);
  const [pendingDowngrade, setPendingDowngrade] = useState<PendingRoleDowngrade[]>([]);
  const [downgradeIndex, setDowngradeIndex] = useState(0);
  const [downgrading, setDowngrading] = useState(false);
  // HRP-174: state for the contextual "Add employee" modal opened from
  // the Employees block (header button + empty-state CTA).
  const [addEmployeeOpen, setAddEmployeeOpen] = useState(false);
  const [allPositions, setAllPositions] = useState<Position[]>([]);

  const load = useCallback(async () => {
    try {
      // HRP-174: positions are needed so the Add-employee modal can
      // surface them as an optional picker. Pull alongside the existing
      // payloads to avoid an extra round-trip when the modal opens.
      const [div, specs, empList, divsAll, empsAll, posAll] =
        await Promise.allSettled([
          api.get<Division>(`/divisions/${id}`),
          api.get<SpecializationDivision[]>(`/divisions/${id}/specializations`),
          api.get<EmployeeListResponse>(`/employees?division_id=${id}&limit=500`),
          api.get<Division[]>("/divisions"),
          api.get<EmployeeListResponse>("/employees?limit=500"),
          api.get<PositionListResponse>("/positions?lifecycle_status=active"),
        ]);
      if (div.status === "fulfilled") setDivision(div.value);
      if (specs.status === "fulfilled") setSpecializations(specs.value);
      if (empList.status === "fulfilled") setEmployees(empList.value.items);
      if (divsAll.status === "fulfilled") setAllDivisions(divsAll.value);
      if (empsAll.status === "fulfilled") setAllEmployees(empsAll.value.items);
      if (posAll.status === "fulfilled") setAllPositions(posAll.value.items);
      if (div.status === "rejected") toast.error(t("toastDivisionLoadFailed"));
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  useEffect(() => {
    load();
  }, [load]);

  const employeeCountBySpec = useMemo(() => {
    const map = new Map<string, number>();
    for (const e of employees) {
      if (!e.specialization_id) continue;
      map.set(e.specialization_id, (map.get(e.specialization_id) ?? 0) + 1);
    }
    return map;
  }, [employees]);

  const filteredEmployees = useMemo(
    () => applyDivisionFilters(employees, filters),
    [employees, filters],
  );

  // HRP-58: dropdown options are derived from the actual division
  // employees so the picker never offers a value that yields zero rows.
  const positionOptions = useMemo(
    () => derivePositionOptions(employees),
    [employees],
  );
  const gradeOptions = useMemo(
    () => deriveGradeOptions(employees),
    [employees],
  );
  const flatDivisions = useMemo(() => flattenTree(allDivisions), [allDivisions]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        {tc("loading")}
      </div>
    );
  }

  if (!division) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" render={<Link href="/company" />}>
          <ArrowLeft className="mr-1 h-4 w-4" />
          {t("backToCompany")}
        </Button>
        <div className="py-12 text-center text-muted-foreground">
          {t("divisionNotFound")}
        </div>
      </div>
    );
  }

  const filterSpecTitle = filterSpecId
    ? specializations.find((s) => s.specialization_id === filterSpecId)
        ?.specialization_title ?? tc("unknown")
    : null;

  function openEditDialog() {
    if (!division) return;
    setEditForm({
      name: division.name,
      description: division.description || "",
      parent_id: division.parent_id || "",
      manager_id: division.manager_id || "",
      deputy_manager_id: division.deputy_manager_id || "",
    });
    setEditOpen(true);
  }

  async function saveDivision() {
    if (!division) return;
    setSaving(true);
    try {
      const payload = {
        ...editForm,
        parent_id: editForm.parent_id || null,
        manager_id: editForm.manager_id || null,
        deputy_manager_id: editForm.deputy_manager_id || null,
      };
      const result = await api.put<Division>(`/divisions/${division.id}`, payload);
      toast.success(t("toastDivisionUpdated"));
      setEditOpen(false);
      const pending = result.pending_role_downgrade ?? [];
      // HRP-196: the server now auto-downgrades the previous manager
      // when they lose their last division. Surfacing the affected names
      // in a toast keeps the operator informed without an extra prompt.
      // Anything not flagged `downgraded` (legacy clients / future opt-in
      // confirm flow) still falls through to the existing confirm dialog.
      const auto = pending.filter((p) => p.downgraded);
      const manual = pending.filter((p) => !p.downgraded);
      if (auto.length > 0) {
        const names = auto
          .map((p) => p.user_name)
          .filter((n): n is string => Boolean(n));
        if (names.length > 0) {
          toast.success(
            names.length === 1
              ? t("toastDowngradedNamed", { name: names[0] })
              : t("toastDowngradedCount", { count: names.length }),
          );
        } else {
          toast.success(t("toastPreviousManagerDowngraded"));
        }
      }
      // HRP-196: the same flow auto-upgrades employees just put in a
      // manager seat. Surfacing the upgrade keeps the operator's mental
      // model in sync with the actual role graph instead of leaving the
      // promotion invisible until they navigate to another page.
      const upgrades = result.role_upgrades ?? [];
      if (upgrades.length > 0) {
        const names = upgrades
          .map((u) => u.user_name)
          .filter((n): n is string => Boolean(n));
        if (names.length > 0) {
          toast.success(
            names.length === 1
              ? t("toastPromotedNamed", { name: names[0] })
              : t("toastPromotedCount", { count: names.length }),
          );
        } else {
          toast.success(t("toastUserPromoted"));
        }
      }
      if (manual.length > 0) {
        setPendingDowngrade(manual);
        setDowngradeIndex(0);
      }
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastSaveFailed"));
    } finally {
      setSaving(false);
    }
  }

  function advanceDowngrade() {
    if (downgradeIndex + 1 >= pendingDowngrade.length) {
      setPendingDowngrade([]);
      setDowngradeIndex(0);
    } else {
      setDowngradeIndex(downgradeIndex + 1);
    }
  }

  async function confirmDowngrade() {
    const target = pendingDowngrade[downgradeIndex];
    if (!target) return;
    setDowngrading(true);
    try {
      await api.post(`/employees/${target.employee_id}/downgrade-role`, {});
      toast.success(
        target.user_name
          ? t("toastDowngradedNamed", { name: target.user_name })
          : t("toastRoleDowngraded"),
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastDowngradeFailed"));
    } finally {
      setDowngrading(false);
      advanceDowngrade();
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon-sm" render={<Link href="/company" />}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <h1 className="text-2xl font-semibold tracking-tight">{division.name}</h1>
          {division.description && (
            <p className="text-sm text-muted-foreground">{division.description}</p>
          )}
        </div>
        {canManage && (
          <Button
            variant="outline"
            size="sm"
            data-testid="division-detail-btn-edit"
            onClick={openEditDialog}
          >
            <Pencil className="mr-1 h-4 w-4" />
            {t("edit")}
          </Button>
        )}
      </div>

      {/* Info card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("divisionInfo")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
            <div>
              <p className="text-muted-foreground">{t("manager")}</p>
              <p className="font-medium">
                {division.manager_name || t("notAssigned")}
              </p>
            </div>
            <div>
              <p className="text-muted-foreground">{t("deputyManager")}</p>
              <p className="font-medium">
                {division.deputy_manager_name || t("notAssigned")}
              </p>
            </div>
            <div>
              <p className="text-muted-foreground">{t("employees")}</p>
              <p className="font-medium">{employees.length}</p>
            </div>
            <div>
              <p className="text-muted-foreground">{t("created")}</p>
              <p className="font-medium">{formatDate(division.created_at)}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Specializations */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t("specializationsWithCount", { count: specializations.length })}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {specializations.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              {t("divisionNoSpecializations")}
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {specializations.map((spec) => {
                const count = employeeCountBySpec.get(spec.specialization_id) ?? 0;
                const active = filterSpecId === spec.specialization_id;
                return (
                  <button
                    type="button"
                    key={spec.id}
                    data-testid={`division-spec-${spec.specialization_id}-filter`}
                    aria-pressed={active}
                    onClick={() =>
                      setFilters((prev) => ({
                        ...prev,
                        specializationId: active ? null : spec.specialization_id,
                      }))
                    }
                    className={`flex items-center justify-between rounded-lg border p-3 text-left transition-colors hover:bg-accent ${
                      active ? "border-primary bg-accent" : ""
                    }`}
                  >
                    <span className="text-sm font-medium">
                      {spec.specialization_title || tc("unknown")}
                    </span>
                    <Badge variant="secondary" className="gap-1">
                      <Users className="h-3 w-3" />
                      {count}
                    </Badge>
                  </button>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Employees list */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle
              className="text-base"
              // HRP-58: aria-live so screen readers announce the
              // updated visible/total count when filters change.
              aria-live="polite"
            >
              {t("employees")}{" "}
              <span className="text-muted-foreground">
                {hasActiveDivisionFilters(filters)
                  ? t("employeesVisibleOfTotal", {
                      visible: filteredEmployees.length,
                      total: employees.length,
                    })
                  : t("employeesVisible", {
                      visible: filteredEmployees.length,
                    })}
              </span>
            </CardTitle>
            <div className="flex flex-wrap items-center gap-2">
              {/* HRP-58: Position filter — dropdown, options derived from
                  the loaded employees so the picker never offers a value
                  that yields zero rows. The explicit children inside
                  <SelectValue> defeat Base UI's fallback to the raw
                  value (UUID) when no <SelectItem> matches the current
                  selection yet (see HRP-59 note above). */}
              <Select
                value={filters.positionId ?? ""}
                onValueChange={(val) =>
                  setFilters((prev) => ({ ...prev, positionId: val || null }))
                }
              >
                <SelectTrigger
                  className="h-8 w-[200px]"
                  data-testid="division-employees-position-filter"
                  aria-label={t("filterByPosition")}
                >
                  <SelectValue placeholder={t("allPositions")}>
                    {filters.positionId
                      ? positionOptions.find(
                          (o) => o.id === filters.positionId,
                        )?.title ?? t("allPositions")
                      : t("allPositions")}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">{t("allPositions")}</SelectItem>
                  {positionOptions.map((opt) => (
                    <SelectItem key={opt.id} value={opt.id}>
                      {opt.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {/* HRP-58: Grade filter — same pattern as Position. */}
              <Select
                value={filters.gradeId ?? ""}
                onValueChange={(val) =>
                  setFilters((prev) => ({ ...prev, gradeId: val || null }))
                }
              >
                <SelectTrigger
                  className="h-8 w-[160px]"
                  data-testid="division-employees-grade-filter"
                  aria-label={t("filterByGrade")}
                >
                  <SelectValue placeholder={t("allGrades")}>
                    {filters.gradeId
                      ? gradeOptions.find((o) => o.id === filters.gradeId)
                          ?.title ?? t("allGrades")
                      : t("allGrades")}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">{t("allGrades")}</SelectItem>
                  {gradeOptions.map((opt) => (
                    <SelectItem key={opt.id} value={opt.id}>
                      {opt.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {/* HRP-174: Add employee — opens a contextual modal so HR
                  can add existing or create a new employee without
                  leaving the division detail page. */}
              {canManage ? (
                <Button
                  size="sm"
                  data-testid="division-detail-btn-add-employee"
                  onClick={() => setAddEmployeeOpen(true)}
                >
                  {t("addEmployee")}
                </Button>
              ) : null}
            </div>
          </div>
          {hasActiveDivisionFilters(filters) ? (
            <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
              {filters.specializationId ? (
                <Badge
                  variant="outline"
                  className="gap-1 pr-1"
                  data-testid="division-employees-specialization-filter-chip"
                >
                  {t("chipSpecialization", {
                    value: filterSpecTitle ?? tc("unknown"),
                  })}
                  <button
                    type="button"
                    data-testid="division-employees-filter-clear"
                    className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full hover:bg-muted"
                    onClick={() =>
                      setFilters((prev) => ({ ...prev, specializationId: null }))
                    }
                    aria-label={t("clearSpecializationFilter")}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              ) : null}
              {filters.positionId ? (
                <Badge
                  variant="outline"
                  className="gap-1 pr-1"
                  data-testid="division-employees-position-filter-chip"
                >
                  {t("chipPosition", {
                    value:
                      positionOptions.find((o) => o.id === filters.positionId)
                        ?.title ?? tc("unknown"),
                  })}
                  <button
                    type="button"
                    data-testid="division-employees-position-filter-clear"
                    className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full hover:bg-muted"
                    onClick={() =>
                      setFilters((prev) => ({ ...prev, positionId: null }))
                    }
                    aria-label={t("clearPositionFilter")}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              ) : null}
              {filters.gradeId ? (
                <Badge
                  variant="outline"
                  className="gap-1 pr-1"
                  data-testid="division-employees-grade-filter-chip"
                >
                  {t("chipGrade", {
                    value:
                      gradeOptions.find((o) => o.id === filters.gradeId)
                        ?.title ?? tc("unknown"),
                  })}
                  <button
                    type="button"
                    data-testid="division-employees-grade-filter-clear"
                    className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full hover:bg-muted"
                    onClick={() =>
                      setFilters((prev) => ({ ...prev, gradeId: null }))
                    }
                    aria-label={t("clearGradeFilter")}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              ) : null}
              {activeFilterCount(filters) >= 2 ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-xs"
                  data-testid="division-employees-filter-clear-all"
                  onClick={() => setFilters(EMPTY_FILTERS)}
                >
                  {t("clearAll")}
                </Button>
              ) : null}
            </div>
          ) : null}
        </CardHeader>
        <CardContent>
          {hasActiveDivisionFilters(filters) && filteredEmployees.length === 0 ? (
            <div
              data-testid="division-detail-employees-empty"
              className="space-y-3 py-6 text-center"
            >
              <p className="text-sm text-muted-foreground">
                {t("divisionEmployeesNoMatches")}
              </p>
              <Button
                variant="outline"
                size="sm"
                data-testid="division-employees-empty-clear-all"
                onClick={() => setFilters(EMPTY_FILTERS)}
              >
                {t("clearAllFilters")}
              </Button>
            </div>
          ) : filteredEmployees.length === 0 ? (
            <div
              data-testid="division-detail-employees-empty"
              className="space-y-3 py-6 text-center"
            >
              <p className="text-sm text-muted-foreground">
                {t("divisionNoEmployees")}
              </p>
              {canManage ? (
                <Button
                  variant="outline"
                  size="sm"
                  data-testid="division-detail-empty-add-employee"
                  onClick={() => setAddEmployeeOpen(true)}
                >
                  {t("addEmployee")}
                </Button>
              ) : null}
            </div>
          ) : (
            /* HRP-175: unified 7-column EmployeeList (Name → Position →
               Specialization → Grade → Division → Status → Hire Date)
               matches the positions drilldown so the layout is the same
               wherever a list of employees appears. */
            <div className="overflow-x-auto rounded-lg border">
              <EmployeeList
                employees={filteredEmployees as unknown as EmployeeListItem[]}
                testIdPrefix="division-detail-employees-row"
              />
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent data-testid="division-detail-modal-edit">
          <DialogHeader>
            <DialogTitle>{t("editDivision")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>{t("name")}</Label>
              <Input
                data-testid="division-detail-modal-edit-input-name"
                value={editForm.name}
                onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>{t("description")}</Label>
              <Textarea
                data-testid="division-detail-modal-edit-input-description"
                value={editForm.description}
                onChange={(e) =>
                  setEditForm({ ...editForm, description: e.target.value })
                }
                rows={2}
              />
            </div>
            <div className="space-y-2">
              <Label>{t("parentDivision")}</Label>
              <Select
                value={editForm.parent_id}
                onValueChange={(val) => setEditForm({ ...editForm, parent_id: val })}
              >
                <SelectTrigger
                  className="w-full"
                  data-testid="division-detail-modal-edit-select-parent"
                >
                  <SelectValue placeholder={t("noneTopLevel")}>
                    {(() => {
                      if (!editForm.parent_id) return undefined;
                      const d = flatDivisions.find((x) => x.id === editForm.parent_id);
                      return d ? `${"—".repeat(d.depth)} ${d.name}` : undefined;
                    })()}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">{t("noneTopLevel")}</SelectItem>
                  {flatDivisions
                    .filter((d) => d.id !== division.id)
                    .map((d) => (
                      <SelectItem key={d.id} value={d.id}>
                        {"—".repeat(d.depth)} {d.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t("manager")}</Label>
              <Select
                value={editForm.manager_id}
                onValueChange={(val) => setEditForm({ ...editForm, manager_id: val })}
              >
                <SelectTrigger
                  className="w-full"
                  data-testid="division-detail-modal-edit-select-manager"
                >
                  <SelectValue placeholder={t("none")}>
                    {employeeLabel(
                      editForm.manager_id,
                      allEmployees,
                      division.manager_name,
                      t("none"),
                    )}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">{t("none")}</SelectItem>
                  {allEmployees.map((emp) => (
                    <SelectItem key={emp.id} value={emp.id}>
                      {emp.user_name?.trim() || emp.user_email || "—"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t("deputyManager")}</Label>
              <Select
                value={editForm.deputy_manager_id}
                onValueChange={(val) =>
                  setEditForm({ ...editForm, deputy_manager_id: val })
                }
              >
                <SelectTrigger
                  className="w-full"
                  data-testid="division-detail-modal-edit-select-deputy-manager"
                >
                  <SelectValue placeholder={t("none")}>
                    {employeeLabel(
                      editForm.deputy_manager_id,
                      allEmployees,
                      division.deputy_manager_name,
                      t("none"),
                    )}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">{t("none")}</SelectItem>
                  {allEmployees.map((emp) => (
                    <SelectItem key={emp.id} value={emp.id}>
                      {emp.user_name?.trim() || emp.user_email || "—"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditOpen(false)} disabled={saving}>
              {tc("cancel")}
            </Button>
            <Button
              data-testid="division-detail-modal-edit-btn-submit"
              onClick={saveDivision}
              disabled={saving}
            >
              {saving ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={pendingDowngrade.length > 0}
        onOpenChange={(open) => {
          if (!open) advanceDowngrade();
        }}
      >
        <DialogContent
          className="sm:max-w-md"
          data-testid="division-detail-role-downgrade-dialog"
        >
          <DialogHeader>
            <DialogTitle>{t("downgradeTitle")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-2 text-sm text-muted-foreground">
            <p>
              {pendingDowngrade[downgradeIndex]?.user_name
                ? t("downgradeBodyNamed", {
                    name: pendingDowngrade[downgradeIndex]!.user_name!,
                  })
                : t("downgradeBodyGeneric")}
            </p>
            <p>{t("downgradeQuestion")}</p>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={advanceDowngrade}
              disabled={downgrading}
              data-testid="division-detail-role-downgrade-keep"
            >
              {t("keepAsManager")}
            </Button>
            <Button
              onClick={confirmDowngrade}
              disabled={downgrading}
              data-testid="division-detail-role-downgrade-confirm"
            >
              {downgrading ? t("downgrading") : t("downgrade")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* HRP-174: contextual Add-employee modal lives here so the
          Employees block can open it from both the header button and
          the empty-state CTA. */}
      <AddEmployeeDialog
        open={addEmployeeOpen}
        onOpenChange={setAddEmployeeOpen}
        divisionId={division.id}
        divisionName={division.name}
        allEmployees={allEmployees.map((e) => ({
          id: e.id,
          user_id: e.user_id,
          user_name: e.user_name,
          user_email: e.user_email,
          division_id: e.division_id,
          division_name: e.division_name,
        }))}
        positions={allPositions.map((p) => ({ id: p.id, title: p.title }))}
        onRefresh={async () => {
          await load();
        }}
      />
    </div>
  );
}
