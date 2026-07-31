"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { BADGE_COLOR } from "@/lib/badge-tones";
import {
  dictionaryItemDescription,
  dictionaryItemLabel,
} from "@/lib/reference-labels";
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

// HRP-476: dictionary type → keys in the `dictionaries` i18n namespace. The
// tab label and the type-specific empty state travel together so the pair
// stays consistent per type.
const DICT_TYPES = [
  { key: "grade", labelKey: "typeGrades", emptyKey: "emptyGrades" },
  {
    key: "specialization",
    labelKey: "typeSpecializations",
    emptyKey: "emptySpecializations",
  },
  {
    key: "competence_type",
    labelKey: "typeCompetenceTypes",
    emptyKey: "emptyCompetenceTypes",
  },
  { key: "role", labelKey: "typeRoles", emptyKey: "emptyRoles" },
  { key: "goal", labelKey: "typeGoals", emptyKey: "emptyGoals" },
  { key: "project", labelKey: "typeProjects", emptyKey: "emptyProjects" },
];

const emptyForm = { title: "", description: "", sort_index: 0, is_active: true };

export default function DictionariesPage() {
  const t = useTranslations("dictionaries");
  const tc = useTranslations("common");
  const tRef = useTranslations("reference");
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
        toast.success(t("toastItemCreated"));
      } else {
        // HRP-285: System items only ship ``is_active`` to the API —
        // every other field is frozen for tenants.
        const payload = editingIsSystem
          ? { is_active: form.is_active }
          : form;
        await api.put(`/dictionaries/items/${editingId}`, payload);
        toast.success(t("toastItemUpdated"));
      }
      setDialogOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorSave"));
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
      toast.success(t("toastItemDeleted"));
      setDeleteOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorDelete"));
    } finally {
      setSaving(false);
    }
  }

  // HRP-289: derive the visible list once so the counter (above the
  // Search row) and the table consume the same source.
  const filteredItems = useMemo(
    () =>
      items.filter((i) => {
        // HRP-479: match both the stored title and the localized label —
        // the table shows the latter, so the visible string must hit.
        if (searchQuery) {
          const q = searchQuery.toLowerCase();
          const raw = i.title.toLowerCase();
          const localized = dictionaryItemLabel(tRef, i).toLowerCase();
          if (!raw.includes(q) && !localized.includes(q)) return false;
        }
        if (sourceFilter === "system" && i.tenant_id) return false;
        if (sourceFilter === "custom" && !i.tenant_id) return false;
        if (statusFilter === "active" && !i.is_active) return false;
        if (statusFilter === "inactive" && i.is_active) return false;
        return true;
      }),
    [items, searchQuery, sourceFilter, statusFilter, tRef],
  );
  const filteredCount = filteredItems.length;

  return (
    <RequireRole manage>
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("title")}
          </h1>
          <p className="text-sm text-muted-foreground">{t("subtitle")}</p>
        </div>
        <Button size="sm" onClick={openCreate} data-testid="dictionaries-btn-add" className="sm:self-auto self-start">
          <Plus className="mr-1 h-4 w-4" />
          {t("addItem")}
        </Button>
      </div>

      {/* Type tabs — horizontal scroll on narrow viewports so labels don't collide */}
      <div className="-mx-1 flex gap-1 overflow-x-auto rounded-lg border bg-muted p-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {DICT_TYPES.map((dt) => (
          <button
            key={dt.key}
            onClick={() => setActiveType(dt.key)}
            className={`shrink-0 whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              activeType === dt.key
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {t(dt.labelKey)}
          </button>
        ))}
      </div>

      {/* HRP-289: filtered item counter above Search; respects active filters. */}
      <p
        data-testid="dictionaries-count"
        className="text-sm text-muted-foreground"
      >
        {t("itemCount", { count: filteredCount })}
      </p>

      {/* Search + filters (HRP-283) */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative max-w-sm flex-1 min-w-48">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={t("searchPlaceholder")}
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
            <SelectValue placeholder={t("filterAllSources")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="system">{t("sourceSystem")}</SelectItem>
            <SelectItem value="custom">{t("sourceCustom")}</SelectItem>
          </SelectContent>
        </Select>
        <Select
          value={statusFilter}
          onValueChange={(v) =>
            setStatusFilter((v as "" | "active" | "inactive") || "")
          }
        >
          <SelectTrigger className="w-40" data-testid="dictionaries-filter-status">
            <SelectValue placeholder={t("filterAllStatuses")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="active">{t("statusActive")}</SelectItem>
            <SelectItem value="inactive">{t("statusInactive")}</SelectItem>
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
            {t("clear")}
          </Button>
        )}
      </div>

      {(() => {
        const filtered = filteredItems;
        return loading ? (
        <div className="py-12 text-center text-muted-foreground">
          {tc("loading")}
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-lg border border-dashed p-12 text-center text-muted-foreground" data-testid="dictionaries-empty">
          {items.length === 0
            ? t(
                DICT_TYPES.find((dt) => dt.key === activeType)?.emptyKey ??
                  "emptyFiltered",
              )
            : t("emptyFiltered")}
        </div>
      ) : (
        <div className="rounded-lg border" data-testid="dictionaries-list">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("columnTitle")}</TableHead>
                <TableHead>{t("columnDescription")}</TableHead>
                <TableHead>{t("columnSortIndex")}</TableHead>
                <TableHead>{t("columnSource")}</TableHead>
                <TableHead>{t("columnStatus")}</TableHead>
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
                        {dictionaryItemLabel(tRef, item)}
                      </Link>
                    ) : (
                      dictionaryItemLabel(tRef, item)
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {dictionaryItemDescription(tRef, item) || "—"}
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
                      {item.tenant_id ? t("sourceCustom") : t("sourceSystem")}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="secondary"
                      className={item.is_active ? BADGE_COLOR.green : BADGE_COLOR.neutral}
                    >
                      {item.is_active ? t("statusActive") : t("statusInactive")}
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
                          {t("edit")}
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
                            {tc("delete")}
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
              {dialogMode === "create" ? t("addItem") : t("editItem")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {/* HRP-285: System items expose only the Active checkbox; the
                other fields stay frozen for tenants. */}
            <div className="space-y-2">
              <Label>{t("fieldTitle")}</Label>
              <Input
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                maxLength={100}
                disabled={editingIsSystem && dialogMode === "edit"}
              />
            </div>
            <div className="space-y-2">
              <Label>{t("fieldDescription")}</Label>
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
              <Label>{t("fieldSortIndex")}</Label>
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
                <Label>{t("fieldActive")}</Label>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDialogOpen(false)}
              disabled={saving}
            >
              {tc("cancel")}
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving
                ? t("saving")
                : dialogMode === "create"
                  ? t("create")
                  : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation */}
      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={t("deleteItemTitle")}
        description={t("deleteItemDescription", {
          title: deletingItem?.title ?? "",
        })}
        onConfirm={confirmDelete}
        loading={saving}
      />
    </div>
    </RequireRole>
  );
}
