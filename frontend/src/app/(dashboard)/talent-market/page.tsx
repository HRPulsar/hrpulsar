"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { flattenTree } from "@/lib/utils";
import { BADGE_COLOR } from "@/lib/badge-tones";
import type { Division, TalentCard } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DatePicker } from "@/components/ui/date-picker";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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
import { ConfirmDialog } from "@/components/confirm-dialog";
import { MultiSelectFilter } from "@/components/multi-select-filter";
import { usePermissions } from "@/hooks/use-permissions";
import { toast } from "sonner";
import Link from "next/link";
import { MoreHorizontal, Plus, Search, Send, Trash2, X } from "lucide-react";
import { formatDate } from "@/lib/date-format";

// HRP-476: the wording lives in the `talentMarket` i18n namespace — these
// maps only own the code → key relation (same shape as
// `components/employees/employee-status.ts`).
const TYPE_KEYS: Record<string, string> = {
  vacancy: "typeVacancy",
  talent: "typeTalent",
  project: "typeProject",
};

const TYPE_CODES = ["vacancy", "talent", "project"] as const;

const statusColors: Record<string, string> = {
  draft: BADGE_COLOR.neutral,
  published: BADGE_COLOR.blue,
  // Keep `closed` for legacy rows; new code paths emit `completed`.
  closed: BADGE_COLOR.green,
  completed: BADGE_COLOR.green,
  cancelled: BADGE_COLOR.red,
};

// HRP-148: capitalised labels — the API returns lowercase codes; the UI
// surfaces "Draft / Published / Completed / Cancelled" per spec.
// HRP-476: the map holds i18n keys in the `talentMarket` namespace.
const STATUS_KEYS: Record<string, string> = {
  draft: "statusDraft",
  published: "statusPublished",
  completed: "statusCompleted",
  closed: "statusCompleted",
  cancelled: "statusCancelled",
};

/** Translated status label with a raw-code fallback for unknown values. */
function statusLabel(t: (key: string) => string, status: string): string {
  const key = STATUS_KEYS[status];
  return key ? t(key) : status;
}

const TERMINAL_STATUSES = new Set(["completed", "closed", "cancelled"]);

// HRP-148: status options for the Change-status submenu. Each option is
// gated by `from` (the current card status) → keeps the UI in sync with
// the backend transition guards.
const STATUS_TRANSITIONS: Array<{
  from: string;
  to: string;
  labelKey: string;
}> = [
  { from: "draft", to: "published", labelKey: "actionPublish" },
  { from: "draft", to: "cancelled", labelKey: "actionCancel" },
  { from: "published", to: "completed", labelKey: "actionComplete" },
  { from: "published", to: "cancelled", labelKey: "actionCancel" },
];

// The filter chips render the raw lowercase codes the API persists, so
// their labels are separate keys from the capitalised badge wording.
const STATUS_FILTER_KEYS: Array<{ value: string; labelKey: string }> = [
  { value: "draft", labelKey: "statusFilterDraft" },
  { value: "published", labelKey: "statusFilterPublished" },
  { value: "completed", labelKey: "statusFilterCompleted" },
  { value: "cancelled", labelKey: "statusFilterCancelled" },
];

// HRP-92: ISO date helpers for the Start/End date pickers (`date` input
// uses YYYY-MM-DD, no time component). Use the user's *local* date so a
// user at UTC+10 just after midnight doesn't get yesterday as today's
// default + min-bound.
function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

function isoLocal(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function isoToday(): string {
  return isoLocal(new Date());
}

function isoShift(years: number): string {
  const d = new Date();
  d.setFullYear(d.getFullYear() + years);
  return isoLocal(d);
}


// HRP-167: red-highlight the date range on active cards whose End date
// is in the past. Terminal cards (Completed / Cancelled) keep their
// neutral palette — overdue is only meaningful while the card is still
// active.
function isOverdue(card: TalentCard): boolean {
  if (!card.end_date) return false;
  if (TERMINAL_STATUSES.has(card.status)) return false;
  return card.end_date < isoToday();
}

// HRP-92 REDO: terminal cards show "Completed: yyyy-mm-dd" /
// "Cancelled: yyyy-mm-dd" instead of the legacy "Closed:" label,
// matching the Assessments section. Active cards (Draft / Published)
// still render the date range.
function formatCardTermLabel(
  t: (key: string, values?: Record<string, string>) => string,
  card: TalentCard,
): string {
  if (card.status === "completed" || card.status === "closed") {
    const when = card.completed_at ?? card.closed_at;
    if (when) {
      return t("termCompleted", { date: formatDate(when.slice(0, 10)) });
    }
  }
  if (card.status === "cancelled") {
    const when = card.cancelled_at ?? card.closed_at;
    if (when) {
      return t("termCancelled", { date: formatDate(when.slice(0, 10)) });
    }
  }
  if (card.end_date) {
    return t("termRange", {
      start: formatDate(card.start_date),
      end: formatDate(card.end_date),
    });
  }
  return t("termSince", { date: formatDate(card.start_date) });
}

// HRP-128: Match% is required at create (50..100). 80 is the default the
// previous step-3 dialog defaulted to and keeps the matcher behaviour
// stable for cards that were created before the rewrite.
const DEFAULT_MATCH_PERCENT = 80;

const emptyForm = {
  title: "",
  description: "",
  card_type: "vacancy",
  division_id: "",
  start_date: isoToday(),
  end_date: "",
  match_percent: String(DEFAULT_MATCH_PERCENT),
};

export default function TalentMarketPage() {
  const t = useTranslations("talentMarket");
  const tc = useTranslations("common");
  const [cards, setCards] = useState<TalentCard[]>([]);
  // HRP-290 follow-up: server total across all cards, not just the loaded
  // `{ limit: 50 }` page — the header counter shows it when no client-side
  // filter is active, so tenants past 50 cards aren't under-reported.
  const [total, setTotal] = useState(0);
  const [divisions, setDivisions] = useState<Division[]>([]);
  const [loading, setLoading] = useState(true);

  // Create/Edit
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"create" | "edit">("create");
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  // HRP-128: Match% is read-only after publish. Tracked separately because
  // the form doesn't otherwise carry the publish state.
  const [editingPublished, setEditingPublished] = useState(false);

  // Delete
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletingCard, setDeletingCard] = useState<TalentCard | null>(null);

  // HRP-88: filter block (mirror /assessments). Filtering is client-side
  // over the currently-loaded page — same trade-off as the assessments
  // list; a backend `card_types` / `statuses` array param can land
  // later if pagination starts swallowing matches.
  const [searchQuery, setSearchQuery] = useState("");
  const [filterTypes, setFilterTypes] = useState<string[]>([]);
  const [filterStatuses, setFilterStatuses] = useState<string[]>([]);

  const [saving, setSaving] = useState(false);

  const { canManage } = usePermissions();

  async function load() {
    try {
      const [searchData, divData] = await Promise.all([
        api.post<{ items: TalentCard[]; total: number }>("/talent-market/search", { limit: 50 }),
        api.get<Division[]>("/divisions"),
      ]);
      setCards(searchData.items);
      setTotal(searchData.total);
      setDivisions(divData);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const flatDivisions = flattenTree(divisions);

  const typeOptions = TYPE_CODES.map((value) => ({
    value,
    label: t(TYPE_KEYS[value]),
  }));

  function openCreate() {
    setDialogMode("create");
    setForm({ ...emptyForm, start_date: isoToday() });
    setEditingId(null);
    setEditingPublished(false);
    setDialogOpen(true);
  }

  async function handleSave() {
    if (!form.title.trim()) {
      toast.error(t("toastTitleRequired"));
      return;
    }
    if (!form.start_date) {
      toast.error(t("toastStartDateRequired"));
      return;
    }
    if (form.end_date && form.end_date < form.start_date) {
      toast.error(t("toastEndDateBeforeStart"));
      return;
    }
    // HRP-128: Match% must be 50..100. Surface the rule client-side so the
    // 422 response isn't the first the user hears about it.
    const matchNum = Number(form.match_percent);
    if (
      !Number.isInteger(matchNum) ||
      matchNum < 50 ||
      matchNum > 100
    ) {
      toast.error(t("toastMatchRangeCreate"));
      return;
    }
    setSaving(true);
    try {
      const payload = {
        ...form,
        division_id: form.division_id || null,
        end_date: form.end_date || null,
        match_percent: matchNum,
      };
      if (dialogMode === "create") {
        await api.post("/talent-market", payload);
        toast.success(t("toastCardCreated"));
      } else {
        await api.put(`/talent-market/${editingId}`, payload);
        toast.success(t("toastCardUpdated"));
      }
      setDialogOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastSaveFailed"));
    } finally {
      setSaving(false);
    }
  }

  // HRP-148: drives the Change-status submenu in the action menu. Maps
  // the target status onto the dedicated endpoint added in HRP-150.
  async function handleChangeStatus(card: TalentCard, target: string) {
    const endpointByTarget: Record<string, string> = {
      published: "publish",
      completed: "complete",
      cancelled: "cancel",
    };
    const ep = endpointByTarget[target];
    if (!ep) return;
    try {
      await api.post(`/talent-market/${card.id}/${ep}`);
      toast.success(
        t("toastStatusChanged", { status: statusLabel(t, target) }),
      );
      await load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("toastStatusChangeFailed"),
      );
    }
  }

  function openDelete(card: TalentCard) {
    setDeletingCard(card);
    setDeleteOpen(true);
  }

  async function confirmDelete() {
    if (!deletingCard) return;
    setSaving(true);
    try {
      await api.delete(`/talent-market/${deletingCard.id}`);
      toast.success(t("toastCardDeleted"));
      setDeleteOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastDeleteFailed"));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="py-12 text-center text-muted-foreground">{tc("loading")}</div>;

  const filteredCards = cards.filter((card) => {
    if (
      searchQuery &&
      !card.title.toLowerCase().includes(searchQuery.toLowerCase())
    ) {
      return false;
    }
    if (filterTypes.length > 0 && !filterTypes.includes(card.card_type)) return false;
    if (filterStatuses.length > 0 && !filterStatuses.includes(card.status)) return false;
    return true;
  });

  // HRP-290 follow-up: all filters here are client-side over the loaded
  // page (see the HRP-88 comment above), so `filteredCards.length` is only
  // honest while a filter is active. Unfiltered, show the server total —
  // the load is capped at 50 items.
  const hasClientFilters =
    Boolean(searchQuery) || filterTypes.length > 0 || filterStatuses.length > 0;
  const displayCount = hasClientFilters ? filteredCards.length : total;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight" data-testid="talent-market-heading">{t("title")}</h1>
          {/* HRP-290: counter respects active filters (Assessments parity). */}
          <p className="text-sm text-muted-foreground" data-testid="talent-market-count">{t("cardCount", { count: displayCount })}</p>
        </div>
        {canManage && (
          <Button size="sm" onClick={openCreate} data-testid="talent-market-btn-create">
            <Plus className="mr-1 h-4 w-4" />
            {t("createCard")}
          </Button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            data-testid="talent-market-input-search"
            placeholder={t("searchPlaceholder")}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8"
          />
        </div>
        <MultiSelectFilter
          data-testid="talent-market-multi-types"
          options={typeOptions}
          value={filterTypes}
          onChange={setFilterTypes}
          placeholder={t("filterAllTypes")}
          className="w-36"
        />
        <MultiSelectFilter
          data-testid="talent-market-multi-statuses"
          options={STATUS_FILTER_KEYS.map((s) => ({
            value: s.value,
            label: t(s.labelKey),
          }))}
          value={filterStatuses}
          onChange={setFilterStatuses}
          placeholder={t("filterAllStatuses")}
          className="w-40"
        />
        {(searchQuery || filterTypes.length > 0 || filterStatuses.length > 0) && (
          <Button
            variant="ghost"
            size="sm"
            data-testid="talent-market-btn-clear-filters"
            onClick={() => {
              setSearchQuery("");
              setFilterTypes([]);
              setFilterStatuses([]);
            }}
          >
            <X className="mr-1 h-3 w-3" />
            {t("clear")}
          </Button>
        )}
      </div>

      {filteredCards.length === 0 ? (
        <div
          data-testid="talent-market-empty"
          className="rounded-lg border border-dashed p-12 text-center text-muted-foreground"
        >
          {cards.length === 0 ? t("emptyNoCards") : t("emptyFiltered")}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredCards.map((card) => (
            <Card key={card.id} className="group relative">
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <Badge variant="secondary">
                    {TYPE_KEYS[card.card_type]
                      ? t(TYPE_KEYS[card.card_type])
                      : card.card_type}
                  </Badge>
                  <div className="flex items-center gap-1">
                    {/* HRP-213: surface "Reacted" left of the status
                        badge on cards the viewer has already reacted
                        on. Hidden for viewers without an employee row
                        (admins outside the tenant employee map). */}
                    {card.reacted_by_me && (
                      <Badge
                        variant="secondary"
                        className={BADGE_COLOR.blue}
                        data-testid={`talent-market-card-${card.id}-reacted`}
                      >
                        {t("reacted")}
                      </Badge>
                    )}
                    <Badge
                      variant="secondary"
                      className={statusColors[card.status] || ""}
                      data-testid={`talent-market-card-${card.id}-status`}
                    >
                      {statusLabel(t, card.status)}
                    </Badge>
                    {/* HRP-148: action menu is always visible (no hover gate)
                        and hidden entirely on terminal cards. Menu items
                        collapsed to Change-status submenu + Delete.
                        HRP-209: hidden for plain Employees — they can't
                        change status or delete cards. */}
                    {canManage && !TERMINAL_STATUSES.has(card.status) && (
                      <DropdownMenu>
                        <DropdownMenuTrigger
                          render={
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              data-testid={`talent-market-card-${card.id}-menu`}
                            />
                          }
                        >
                          <MoreHorizontal className="h-4 w-4" />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {STATUS_TRANSITIONS.filter(
                            (transition) => transition.from === card.status,
                          ).map((transition) => (
                            <DropdownMenuItem
                              key={transition.to}
                              onClick={() =>
                                handleChangeStatus(card, transition.to)
                              }
                              data-testid={`talent-market-card-${card.id}-change-status-${transition.to}`}
                            >
                              <Send className="mr-2 h-4 w-4" />
                              {t(transition.labelKey)}
                            </DropdownMenuItem>
                          ))}
                          <DropdownMenuItem
                            variant="destructive"
                            onClick={() => openDelete(card)}
                            data-testid={`talent-market-card-${card.id}-delete`}
                          >
                            <Trash2 className="mr-2 h-4 w-4" />
                            {tc("delete")}
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </div>
                </div>
                <CardTitle className="text-base mt-2">
                  <Link href={`/talent-market/${card.id}`} className="hover:underline">{card.title}</Link>
                </CardTitle>
              </CardHeader>
              <CardContent>
                {card.description && (
                  <p className="text-sm text-muted-foreground line-clamp-2">{card.description}</p>
                )}
                <p
                  data-testid={`talent-market-card-${card.id}-term`}
                  className={`mt-2 text-xs ${
                    isOverdue(card) ? "text-destructive" : "text-muted-foreground"
                  }`}
                >
                  {formatCardTermLabel(t, card)}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Create/Edit dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{dialogMode === "create" ? t("createCard") : t("editCard")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>{t("fieldTitle")}</Label>
              <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} maxLength={100} />
            </div>
            <div className="space-y-2">
              <Label>{t("fieldDescription")}</Label>
              <Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={3} maxLength={250} />
            </div>
            <div className="space-y-2">
              <Label>{t("fieldType")}</Label>
              <Select value={form.card_type} onValueChange={(val) => setForm({ ...form, card_type: val ?? "" })}>
                <SelectTrigger className="w-full">
                  <SelectValue>
                    {typeOptions.find((opt) => opt.value === form.card_type)?.label ?? ""}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {typeOptions.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="talent-market-input-start-date">
                  {t("fieldStartDate")} <span className="text-destructive">*</span>
                </Label>
                {/* HRP-335: shared DatePicker (HRP-152) instead of the
                    native date inputs. */}
                <DatePicker
                  id="talent-market-input-start-date"
                  data-testid="talent-market-input-start-date"
                  value={form.start_date}
                  min={isoShift(-5)}
                  max={isoShift(5)}
                  onChange={(value) => setForm({ ...form, start_date: value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="talent-market-input-end-date">{t("fieldEndDate")}</Label>
                <DatePicker
                  id="talent-market-input-end-date"
                  data-testid="talent-market-input-end-date"
                  value={form.end_date}
                  min={form.start_date || isoToday()}
                  max={isoShift(5)}
                  onChange={(value) => setForm({ ...form, end_date: value })}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="talent-market-input-match">
                {t("fieldMatchPercent")} <span className="text-destructive">*</span>
              </Label>
              <Input
                id="talent-market-input-match"
                data-testid="talent-market-input-match"
                type="number"
                min={50}
                max={100}
                step={1}
                value={form.match_percent}
                disabled={editingPublished}
                onChange={(e) =>
                  setForm({ ...form, match_percent: e.target.value })
                }
              />
              <p className="text-xs text-muted-foreground">
                {editingPublished ? t("matchHintReadOnly") : t("matchHint")}
              </p>
            </div>
            <div className="space-y-2">
              <Label>{t("fieldDivision")}</Label>
              <Select value={form.division_id} onValueChange={(val) => setForm({ ...form, division_id: val ?? "" })}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder={t("divisionNone")}>
                    {(() => { if (!form.division_id) return undefined; const d = flatDivisions.find((d) => d.id === form.division_id); return d ? `${"—".repeat(d.depth)} ${d.name}` : undefined; })()}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">{t("divisionNone")}</SelectItem>
                  {flatDivisions.map((d) => (
                    <SelectItem key={d.id} value={d.id}>{"—".repeat(d.depth)} {d.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={saving}>{tc("cancel")}</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? t("saving") : dialogMode === "create" ? t("create") : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation */}
      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={t("deleteCardTitle")}
        description={t("deleteCardConfirm", {
          title: deletingCard?.title ?? "",
        })}
        onConfirm={confirmDelete}
        loading={saving}
      />
    </div>
  );
}
