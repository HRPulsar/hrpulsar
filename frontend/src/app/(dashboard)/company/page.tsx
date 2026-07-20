"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { flattenTree } from "@/lib/utils";
import { formatDate } from "@/lib/date-format";
import type {
  Division,
  Employee,
  EmployeeList,
  PendingRoleDowngrade,
  Tenant,
} from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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
import { CompanyTabs } from "@/components/company/company-tabs";
import { usePermissions } from "@/hooks/use-permissions";
import { toast } from "sonner";
import Link from "next/link";
import { MoreHorizontal, Pencil, Plus, Trash2, Upload } from "lucide-react";

function DivisionNode({
  division,
  depth = 0,
  onEdit,
  onDelete,
  onAddChild,
}: {
  division: Division;
  depth?: number;
  onEdit: (d: Division) => void;
  onDelete: (d: Division) => void;
  onAddChild: (parentId: string) => void;
}) {
  return (
    <div data-testid={`company-division-${division.id}`}>
      <div
        className="group flex items-center gap-2 rounded-md px-3 py-2 hover:bg-muted transition-colors"
        style={{ paddingLeft: `${depth * 24 + 12}px` }}
      >
        {division.children.length > 0 ? (
          <svg
            className="h-4 w-4 text-muted-foreground"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={1.5}
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="m19.5 8.25-7.5 7.5-7.5-7.5"
            />
          </svg>
        ) : (
          <div className="w-4" />
        )}
        <svg
          className="h-4 w-4 text-muted-foreground"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={1.5}
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M2.25 12.75V12A2.25 2.25 0 0 1 4.5 9.75h15A2.25 2.25 0 0 1 21.75 12v.75m-8.69-6.44-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44Z"
          />
        </svg>
        <Link href={`/company/divisions/${division.id}`} className="flex-1 text-sm font-medium hover:text-primary hover:underline">
          {division.name}
        </Link>
        {division.description && (
          <span className="text-xs text-muted-foreground">
            {division.description}
          </span>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger data-testid={`company-division-${division.id}-actions`} render={<Button variant="ghost" size="icon-xs" className="opacity-0 group-hover:opacity-100 transition-opacity" />}>
            <MoreHorizontal className="h-4 w-4" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem data-testid={`company-division-${division.id}-btn-add-child`} onClick={() => onAddChild(division.id)}>
              <Plus className="mr-2 h-4 w-4" />
              Add child
            </DropdownMenuItem>
            <DropdownMenuItem data-testid={`company-division-${division.id}-btn-edit`} onClick={() => onEdit(division)}>
              <Pencil className="mr-2 h-4 w-4" />
              Edit
            </DropdownMenuItem>
            <DropdownMenuItem
              data-testid={`company-division-${division.id}-btn-delete`}
              variant="destructive"
              onClick={() => onDelete(division)}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {division.children.map((child) => (
        <DivisionNode
          key={child.id}
          division={child}
          depth={depth + 1}
          onEdit={onEdit}
          onDelete={onDelete}
          onAddChild={onAddChild}
        />
      ))}
    </div>
  );
}

const emptyTenantForm = { name: "", slug: "" };
const emptyDivisionForm = {
  name: "",
  description: "",
  parent_id: "",
  manager_id: "",
  deputy_manager_id: "",
};

// HRP-59: Base UI's <Select.Value> serializes the raw value (a UUID)
// when the children expression returns `undefined` AND no <SelectItem>
// in the registry matches the value yet — which happens whenever the
// employees list is still loading or has been trimmed by API
// pagination. Always returning a string keeps the trigger label
// readable; we fall back to the snapshot name from the division
// record when the picker hasn't materialized that row yet.
function employeeLabel(
  id: string,
  employees: Employee[],
  fallback: string | null | undefined,
): string {
  if (!id) return "None";
  const emp = employees.find((e) => e.id === id);
  if (emp) return emp.user_name?.trim() || emp.user_email || "—";
  return fallback?.trim() || "—";
}

export default function CompanyPage() {
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [divisions, setDivisions] = useState<Division[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);

  // Tenant edit
  const [tenantDialogOpen, setTenantDialogOpen] = useState(false);
  const [tenantForm, setTenantForm] = useState(emptyTenantForm);

  // Division create/edit
  const [divDialogOpen, setDivDialogOpen] = useState(false);
  const [divDialogMode, setDivDialogMode] = useState<"create" | "edit">("create");
  const [divError, setDivError] = useState<FormErrorState>(EMPTY_FORM_ERROR);
  const [tenantError, setTenantError] = useState<FormErrorState>(EMPTY_FORM_ERROR);
  const [divForm, setDivForm] = useState(emptyDivisionForm);
  const [editingDivId, setEditingDivId] = useState<string | null>(null);
  // Snapshot of the names attached to the division being edited; lets
  // the Manager/Deputy <Select> show a readable label even when the
  // picker list hasn't loaded the corresponding employee yet (HRP-59).
  const [editingDivManagerName, setEditingDivManagerName] = useState<string | null>(null);
  const [editingDivDeputyName, setEditingDivDeputyName] = useState<string | null>(null);

  // Delete
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletingDiv, setDeletingDiv] = useState<Division | null>(null);

  // EMP3: pending role downgrade after manager unassignment
  const [pendingDowngrade, setPendingDowngrade] = useState<
    PendingRoleDowngrade[]
  >([]);
  const [downgradeIndex, setDowngradeIndex] = useState(0);
  const [downgrading, setDowngrading] = useState(false);

  const [saving, setSaving] = useState(false);

  const { canManage } = usePermissions();

  async function load() {
    const [tRes, dRes, empRes] = await Promise.allSettled([
      api.get<Tenant>("/company"),
      api.get<Division[]>("/divisions"),
      api.get<EmployeeList>("/employees?limit=100"),
    ]);
    if (tRes.status === "fulfilled") setTenant(tRes.value);
    if (dRes.status === "fulfilled") setDivisions(dRes.value);
    if (empRes.status === "fulfilled") setEmployees(empRes.value.items);
    setLoading(false);
  }

  useEffect(() => {
    load();
  }, []);

  // Tenant
  function openEditTenant() {
    if (!tenant) return;
    setTenantForm({ name: tenant.name, slug: tenant.slug });
    setTenantError(EMPTY_FORM_ERROR);
    setTenantDialogOpen(true);
  }

  async function saveTenant() {
    setSaving(true);
    setTenantError(EMPTY_FORM_ERROR);
    try {
      await api.put("/company", tenantForm);
      toast.success("Company updated");
      setTenantDialogOpen(false);
      await load();
    } catch (err) {
      setTenantError(parseFormError(err));
    } finally {
      setSaving(false);
    }
  }

  // Division create
  function openCreateDivision(parentId?: string) {
    setDivDialogMode("create");
    setDivForm({
      name: "",
      description: "",
      parent_id: parentId || "",
      manager_id: "",
      deputy_manager_id: "",
    });
    setEditingDivId(null);
    setEditingDivManagerName(null);
    setEditingDivDeputyName(null);
    setDivError(EMPTY_FORM_ERROR);
    setDivDialogOpen(true);
  }

  function openEditDivision(d: Division) {
    setDivDialogMode("edit");
    setDivForm({
      name: d.name,
      description: d.description || "",
      parent_id: d.parent_id || "",
      manager_id: d.manager_id || "",
      deputy_manager_id: d.deputy_manager_id || "",
    });
    setEditingDivId(d.id);
    setEditingDivManagerName(d.manager_name ?? null);
    setEditingDivDeputyName(d.deputy_manager_name ?? null);
    setDivError(EMPTY_FORM_ERROR);
    setDivDialogOpen(true);
  }

  async function saveDivision() {
    setSaving(true);
    setDivError(EMPTY_FORM_ERROR);
    try {
      const payload = {
        ...divForm,
        parent_id: divForm.parent_id || null,
        manager_id: divForm.manager_id || null,
        deputy_manager_id: divForm.deputy_manager_id || null,
      };
      let result: Division;
      if (divDialogMode === "create") {
        result = await api.post<Division>("/divisions", payload);
        toast.success("Division created");
      } else {
        result = await api.put<Division>(`/divisions/${editingDivId}`, payload);
        toast.success("Division updated");
      }
      setDivDialogOpen(false);
      const pending = result.pending_role_downgrade ?? [];
      // HRP-196: server auto-downgrades the previous manager — the FE
      // shows a toast and only falls through to the confirm dialog for
      // entries that were NOT yet auto-applied (legacy / explicit confirm).
      const auto = pending.filter((p) => p.downgraded);
      const manual = pending.filter((p) => !p.downgraded);
      if (auto.length > 0) {
        const names = auto
          .map((p) => p.user_name)
          .filter((n): n is string => Boolean(n));
        if (names.length > 0) {
          toast.success(
            names.length === 1
              ? `${names[0]} downgraded to employee`
              : `${names.length} managers downgraded to employee`,
          );
        } else {
          toast.success("Previous manager role downgraded to employee");
        }
      }
      if (manual.length > 0) {
        setPendingDowngrade(manual);
        setDowngradeIndex(0);
      }
      await load();
    } catch (err) {
      setDivError(parseFormError(err, ["name"]));
    } finally {
      setSaving(false);
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
          ? `${target.user_name} downgraded to employee`
          : "Role downgraded to employee",
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to downgrade");
    } finally {
      setDowngrading(false);
      advanceDowngrade();
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

  // Delete
  function openDeleteDivision(d: Division) {
    setDeletingDiv(d);
    setDeleteOpen(true);
  }

  async function confirmDelete() {
    if (!deletingDiv) return;
    setSaving(true);
    try {
      await api.delete(`/divisions/${deletingDiv.id}`);
      toast.success("Division deleted");
      setDeleteOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setSaving(false);
    }
  }

  const flatDivisions = flattenTree(divisions);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        Loading...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Company</h1>
          <p className="text-sm text-muted-foreground">Organization structure</p>
        </div>
        <Button variant="outline" size="sm" render={<Link href="/settings/import" />}>
          <Upload className="mr-1 h-4 w-4" />
          Import
        </Button>
      </div>

      <CompanyTabs />

      {tenant && (
        <Card data-testid="company-card-info">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle data-testid="company-name">{tenant.name}</CardTitle>
            <Button data-testid="company-btn-edit" variant="ghost" size="icon-sm" onClick={openEditTenant}>
              <Pencil className="h-4 w-4" />
            </Button>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            <p>Slug: {tenant.slug}</p>
            <p>
              Created: {formatDate(tenant.created_at)}
            </p>
          </CardContent>
        </Card>
      )}

      <Card data-testid="company-divisions-card">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">Divisions</CardTitle>
          {canManage && (
            <Button data-testid="company-divisions-btn-add" size="sm" onClick={() => openCreateDivision()}>
              <Plus className="mr-1 h-4 w-4" />
              Add division
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {divisions.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              No divisions yet
            </p>
          ) : (
            <div data-testid="company-divisions-tree" className="-mx-3">
              {divisions.map((div) => (
                <DivisionNode
                  key={div.id}
                  division={div}
                  onEdit={openEditDivision}
                  onDelete={openDeleteDivision}
                  onAddChild={(parentId) => openCreateDivision(parentId)}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Tenant edit dialog */}
      <Dialog open={tenantDialogOpen} onOpenChange={setTenantDialogOpen}>
        <DialogContent data-testid="company-modal-edit">
          <DialogHeader>
            <DialogTitle>Edit company</DialogTitle>
          </DialogHeader>
          <FormErrorBanner
            message={tenantError.message}
            testId="company-modal-edit-error"
          />
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Name</Label>
              <Input
                data-testid="company-modal-edit-input-name"
                value={tenantForm.name}
                onChange={(e) =>
                  setTenantForm({ ...tenantForm, name: e.target.value })
                }
              />
            </div>
            <div className="space-y-2">
              <Label>Slug</Label>
              <Input
                data-testid="company-modal-edit-input-slug"
                value={tenantForm.slug}
                onChange={(e) =>
                  setTenantForm({ ...tenantForm, slug: e.target.value })
                }
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setTenantDialogOpen(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button data-testid="company-modal-edit-btn-submit" onClick={saveTenant} disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Division create/edit dialog */}
      <Dialog open={divDialogOpen} onOpenChange={setDivDialogOpen}>
        <DialogContent data-testid="company-modal-division">
          <DialogHeader>
            <DialogTitle>
              {divDialogMode === "create" ? "Add division" : "Edit division"}
            </DialogTitle>
          </DialogHeader>
          <FormErrorBanner
            message={divError.message}
            testId="company-modal-division-error"
          />
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Name</Label>
              <Input
                data-testid="company-modal-division-input-name"
                value={divForm.name}
                onChange={(e) =>
                  setDivForm({ ...divForm, name: e.target.value })
                }
              />
              <FieldError
                message={divError.fields.name}
                testId="company-modal-division-error-name"
              />
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <Textarea
                data-testid="company-modal-division-input-description"
                value={divForm.description}
                onChange={(e) =>
                  setDivForm({ ...divForm, description: e.target.value })
                }
                rows={2}
              />
            </div>
            <div className="space-y-2">
              <Label>Parent division</Label>
              <Select
                value={divForm.parent_id}
                onValueChange={(val) =>
                  setDivForm({ ...divForm, parent_id: val })
                }
              >
                <SelectTrigger className="w-full" data-testid="company-modal-division-select-parent">
                  <SelectValue placeholder="None (top level)">
                    {(() => { if (!divForm.parent_id) return undefined; const d = flatDivisions.find((d) => d.id === divForm.parent_id); return d ? `${"—".repeat(d.depth)} ${d.name}` : undefined; })()}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">None (top level)</SelectItem>
                  {flatDivisions
                    .filter((d) => d.id !== editingDivId)
                    .map((d) => (
                      <SelectItem key={d.id} value={d.id}>
                        {"—".repeat(d.depth)} {d.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Manager</Label>
              <Select
                value={divForm.manager_id}
                onValueChange={(val) =>
                  setDivForm({ ...divForm, manager_id: val })
                }
              >
                <SelectTrigger className="w-full" data-testid="company-modal-division-select-manager">
                  <SelectValue placeholder="None">
                    {employeeLabel(divForm.manager_id, employees, editingDivManagerName)}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">None</SelectItem>
                  {employees.map((emp) => (
                    <SelectItem key={emp.id} value={emp.id}>
                      {emp.user_name?.trim() || emp.user_email || "—"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Deputy Manager</Label>
              <Select
                value={divForm.deputy_manager_id}
                onValueChange={(val) =>
                  setDivForm({ ...divForm, deputy_manager_id: val })
                }
              >
                <SelectTrigger className="w-full" data-testid="company-modal-division-select-deputy-manager">
                  <SelectValue placeholder="None">
                    {employeeLabel(divForm.deputy_manager_id, employees, editingDivDeputyName)}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">None</SelectItem>
                  {employees.map((emp) => (
                    <SelectItem key={emp.id} value={emp.id}>
                      {emp.user_name?.trim() || emp.user_email || "—"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDivDialogOpen(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button data-testid="company-modal-division-btn-submit" onClick={saveDivision} disabled={saving}>
              {saving
                ? "Saving..."
                : divDialogMode === "create"
                  ? "Create"
                  : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation */}
      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Delete division"
        description={`Are you sure you want to delete "${deletingDiv?.name}"? This action cannot be undone.`}
        onConfirm={confirmDelete}
        loading={saving}
      />

      {/* EMP3: role downgrade confirmation after manager unassignment */}
      <Dialog
        open={pendingDowngrade.length > 0}
        onOpenChange={(open) => {
          if (!open) advanceDowngrade();
        }}
      >
        <DialogContent
          className="sm:max-w-md"
          data-testid="role-downgrade-dialog"
        >
          <DialogHeader>
            <DialogTitle>Downgrade role to employee?</DialogTitle>
          </DialogHeader>
          <div className="space-y-2 text-sm text-muted-foreground">
            <p>
              {pendingDowngrade[downgradeIndex]?.user_name
                ? `${pendingDowngrade[downgradeIndex]?.user_name} no longer manages any division.`
                : "This user no longer manages any division."}
            </p>
            <p>Lower their role from manager to employee?</p>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={advanceDowngrade}
              disabled={downgrading}
              data-testid="role-downgrade-keep"
            >
              Keep manager
            </Button>
            <Button
              onClick={confirmDowngrade}
              disabled={downgrading}
              data-testid="role-downgrade-confirm"
            >
              {downgrading ? "Downgrading..." : "Downgrade"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
