"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { BADGE_COLOR } from "@/lib/badge-tones";
import type { DictionaryItem } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { RequireRole } from "@/components/require-role";
import { Checkbox } from "@/components/ui/checkbox";
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ConfirmDialog } from "@/components/confirm-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { MoreHorizontal, Pencil, Plus, Search, Trash2, X } from "lucide-react";

const DICT_TYPES = [
  { key: "grade", label: "Grades" },
  { key: "specialization", label: "Specializations" },
  { key: "competence_type", label: "Competence Types" },
  { key: "role", label: "Roles" },
  { key: "goal", label: "Goals" },
  { key: "project", label: "Projects" },
];

const emptyForm = { title: "", description: "", sort_index: 0, is_active: true };

export default function DictionariesPage() {
  const [activeType, setActiveType] = useState("grade");
  const [items, setItems] = useState<DictionaryItem[]>([]);
  const [loading, setLoading] = useState(true);

  // Create/Edit
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"create" | "edit">("create");
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  // HRP-285: track whether the row being edited is Source=System; if so,
  // only ``is_active`` is editable per tenant — title / description /
  // sort_index inputs render disabled and the PUT payload is filtered.
  const [editingIsSystem, setEditingIsSystem] = useState(false);

  // Delete
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletingItem, setDeletingItem] = useState<DictionaryItem | null>(null);

  const [searchQuery, setSearchQuery] = useState("");
  // HRP-283: Source (System/Custom) + Status (Active/Inactive) single-select filters.
  const [sourceFilter, setSourceFilter] = useState<"" | "system" | "custom">("");
  const [statusFilter, setStatusFilter] = useState<"" | "active" | "inactive">(
    "",
  );

  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<DictionaryItem[]>(
        `/dictionaries/${activeType}`,
      );
      setItems(data);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [activeType]);

  useEffect(() => {
    load();
  }, [load]);

  function openCreate() {
    setDialogMode("create");
    setForm(emptyForm);
    setEditingId(null);
    setEditingIsSystem(false);
    setDialogOpen(true);
  }

  function openEdit(item: DictionaryItem) {
    setDialogMode("edit");
    setForm({
      title: item.title,
      description: item.description || "",
      sort_index: item.sort_index,
      is_active: item.is_active,
    });
    setEditingId(item.id);
    setEditingIsSystem(!item.tenant_id);
    setDialogOpen(true);
  }

  async function handleSave() {
    setSaving(true);
    try {
      if (dialogMode === "create") {
        await api.post(`/dictionaries/${activeType}`, form);
        toast.success("Item created");
      } else {
        // HRP-285: System items only ship ``is_active`` to the API —
        // every other field is frozen for tenants.
        const payload = editingIsSystem
          ? { is_active: form.is_active }
          : form;
        await api.put(`/dictionaries/items/${editingId}`, payload);
        toast.success("Item updated");
      }
      setDialogOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  function openDelete(item: DictionaryItem) {
    setDeletingItem(item);
    setDeleteOpen(true);
  }

  async function confirmDelete() {
    if (!deletingItem) return;
    setSaving(true);
    try {
      await api.delete(`/dictionaries/items/${deletingItem.id}`);
      toast.success("Item deleted");
      setDeleteOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setSaving(false);
    }
  }

  // HRP-289: derive the visible list once so the counter (above the
  // Search row) and the table consume the same source.
  const filteredItems = useMemo(
    () =>
      items.filter((i) => {
        if (
          searchQuery &&
          !i.title.toLowerCase().includes(searchQuery.toLowerCase())
        )
          return false;
        if (sourceFilter === "system" && i.tenant_id) return false;
        if (sourceFilter === "custom" && !i.tenant_id) return false;
        if (statusFilter === "active" && !i.is_active) return false;
        if (statusFilter === "inactive" && i.is_active) return false;
        return true;
      }),
    [items, searchQuery, sourceFilter, statusFilter],
  );
  const filteredCount = filteredItems.length;

  return (
    <RequireRole manage>
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">
            Dictionaries
          </h1>
          <p className="text-sm text-muted-foreground">
            System and custom lookup data
          </p>
        </div>
        <Button size="sm" onClick={openCreate} data-testid="dictionaries-btn-add" className="sm:self-auto self-start">
          <Plus className="mr-1 h-4 w-4" />
          Add item
        </Button>
      </div>

      {/* Type tabs — horizontal scroll on narrow viewports so labels don't collide */}
      <div className="-mx-1 flex gap-1 overflow-x-auto rounded-lg border bg-muted p-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {DICT_TYPES.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveType(t.key)}
            className={`shrink-0 whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              activeType === t.key
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* HRP-289: filtered item counter above Search; respects active filters. */}
      <p
        data-testid="dictionaries-count"
        className="text-sm text-muted-foreground"
      >
        {filteredCount} item{filteredCount === 1 ? "" : "s"}
      </p>

      {/* Search + filters (HRP-283) */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative max-w-sm flex-1 min-w-48">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search by title..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8"
            data-testid="dictionaries-input-search"
          />
        </div>
        <Select
          value={sourceFilter}
          onValueChange={(v) =>
            setSourceFilter((v as "" | "system" | "custom") || "")
          }
        >
          <SelectTrigger className="w-40" data-testid="dictionaries-filter-source">
            <SelectValue placeholder="All sources" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="system">System</SelectItem>
            <SelectItem value="custom">Custom</SelectItem>
          </SelectContent>
        </Select>
        <Select
          value={statusFilter}
          onValueChange={(v) =>
            setStatusFilter((v as "" | "active" | "inactive") || "")
          }
        >
          <SelectTrigger className="w-40" data-testid="dictionaries-filter-status">
            <SelectValue placeholder="All statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="inactive">Inactive</SelectItem>
          </SelectContent>
        </Select>
        {(searchQuery || sourceFilter || statusFilter) && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSearchQuery("");
              setSourceFilter("");
              setStatusFilter("");
            }}
            data-testid="dictionaries-btn-clear-filters"
          >
            <X className="mr-1 h-3 w-3" />
            Clear
          </Button>
        )}
      </div>

      {(() => {
        const filtered = filteredItems;
        return loading ? (
        <div className="py-12 text-center text-muted-foreground">
          Loading...
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-lg border border-dashed p-12 text-center text-muted-foreground" data-testid="dictionaries-empty">
          {items.length === 0
            ? `No ${DICT_TYPES.find((t) => t.key === activeType)?.label.toLowerCase()} yet`
            : "No items match the filters"}
        </div>
      ) : (
        <div className="rounded-lg border" data-testid="dictionaries-list">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Sort index</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((item) => (
                <TableRow key={item.id} data-testid={`dictionaries-item-${item.id}`}>
                  <TableCell className="font-medium">
                    {activeType === "specialization" ? (
                      <Link
                        href={`/dictionaries/specializations/${item.id}`}
                        className="text-primary hover:underline"
                        data-testid={`dictionaries-item-${item.id}-link`}
                      >
                        {item.title}
                      </Link>
                    ) : (
                      item.title
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {item.description || "—"}
                  </TableCell>
                  <TableCell
                    className="text-muted-foreground tabular-nums"
                    data-testid={`dictionaries-item-${item.id}-sort-index`}
                  >
                    {item.sort_index}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="secondary"
                      className={item.tenant_id ? BADGE_COLOR.blue : BADGE_COLOR.neutral}
                    >
                      {item.tenant_id ? "Custom" : "System"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="secondary"
                      className={item.is_active ? BADGE_COLOR.green : BADGE_COLOR.neutral}
                    >
                      {item.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger render={<Button variant="ghost" size="icon-xs" />}>
                        <MoreHorizontal className="h-4 w-4" />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => openEdit(item)} data-testid={`dictionaries-item-${item.id}-btn-edit`}>
                          <Pencil className="mr-2 h-4 w-4" />
                          Edit
                        </DropdownMenuItem>
                        {/* HRP-286: Delete is hidden for Source=System rows —
                            origin items can never be deleted by a tenant. */}
                        {item.tenant_id && (
                          <DropdownMenuItem
                            variant="destructive"
                            onClick={() => openDelete(item)}
                            data-testid={`dictionaries-item-${item.id}-btn-delete`}
                          >
                            <Trash2 className="mr-2 h-4 w-4" />
                            Delete
                          </DropdownMenuItem>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      );
      })()}

      {/* Create/Edit dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent data-testid="dictionaries-modal-form">
          <DialogHeader>
            <DialogTitle>
              {dialogMode === "create" ? "Add item" : "Edit item"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {/* HRP-285: System items expose only the Active checkbox; the
                other fields stay frozen for tenants. */}
            <div className="space-y-2">
              <Label>Title</Label>
              <Input
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                maxLength={100}
                disabled={editingIsSystem && dialogMode === "edit"}
              />
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <Textarea
                value={form.description}
                onChange={(e) =>
                  setForm({ ...form, description: e.target.value })
                }
                rows={2}
                maxLength={250}
                disabled={editingIsSystem && dialogMode === "edit"}
              />
            </div>
            <div className="space-y-2">
              <Label>Sort index</Label>
              <Input
                type="number"
                value={form.sort_index}
                onChange={(e) =>
                  setForm({ ...form, sort_index: Number(e.target.value) })
                }
                disabled={editingIsSystem && dialogMode === "edit"}
              />
            </div>
            {dialogMode === "edit" && (
              <div className="flex items-center gap-2">
                <Checkbox
                  checked={form.is_active}
                  onCheckedChange={(checked) =>
                    setForm({ ...form, is_active: !!checked })
                  }
                />
                <Label>Active</Label>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDialogOpen(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving
                ? "Saving..."
                : dialogMode === "create"
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
        title="Delete item"
        description={`Are you sure you want to delete "${deletingItem?.title}"? This action cannot be undone.`}
        onConfirm={confirmDelete}
        loading={saving}
      />
    </div>
    </RequireRole>
  );
}
