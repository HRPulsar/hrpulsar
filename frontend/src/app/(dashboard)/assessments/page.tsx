"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import {
  assessmentStatusTitle,
  assessmentTypeTitle,
} from "@/lib/reference-labels";
import type {
  Assessment,
  AssessmentGroupDetail,
  Employee,
  EmployeeList,
  GroupedAssessmentList,
  GroupedAssessmentListItem,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DatePicker } from "@/components/ui/date-picker";
import { Label } from "@/components/ui/label";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
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
import { EmployeeSummaryLine } from "@/components/employee/employee-summary-line";
import { toast } from "sonner";
import Link from "next/link";
import { Pagination } from "@/components/pagination";
import { usePermissions } from "@/hooks/use-permissions";
import {
  ChevronDown,
  ChevronRight,
  MoreHorizontal,
  Plus,
  Search,
  User,
  Users,
  X,
} from "lucide-react";
import { MassCreateDialog } from "./mass-create-dialog";
import { isPastDeadline, todayLocalISO } from "@/lib/deadline";
import { formatDate } from "@/lib/date-format";
import {
  ASSESSMENT_MANUAL_FORBIDDEN_STATUSES,
  ASSESSMENT_MANUAL_FORBIDDEN_TOOLTIP_KEY,
  ASSESSMENT_STATUS_COLORS as statusColors,
  ASSESSMENT_STATUS_OPTIONS,
  ASSESSMENT_TERMINAL_STATUSES as TERMINAL_STATUSES,
  assessmentRowDate,
  assessmentStatusLabel,
} from "@/lib/assessment-status";

const TYPE_OPTION_KEYS = [
  { value: "self", labelKey: "typeSelf" },
  { value: "180", labelKey: "type180" },
  { value: "360", labelKey: "type360" },
];

const statusOptions = ASSESSMENT_STATUS_OPTIONS;

const PAGE_SIZE = 20;
const emptyForm = { title: "", employee_id: "", type_code: "self", ended_at: "" };

// HRP-192 REDO: the `(i)` hint sits inside a disabled SelectItem whose
// CSS sets pointer-events:none, so a plain `title` attribute never reaches
// the cursor. Re-enable pointer events on this span only so the Tooltip
// can fire, and swallow pointer/click events so they don't bubble up to
// the Select primitive that would treat them as a re-select.
function ManualForbiddenHint({ testId }: { testId: string }) {
  const t = useTranslations("assessments");
  const tooltip = t(ASSESSMENT_MANUAL_FORBIDDEN_TOOLTIP_KEY);
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            tabIndex={-1}
            data-testid={testId}
            aria-label={tooltip}
            className="ml-1 inline-flex cursor-help text-muted-foreground pointer-events-auto"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
          >
            (i)
          </span>
        }
      />
      <TooltipContent>{tooltip}</TooltipContent>
    </Tooltip>
  );
}

function statusSummaryText(
  t: (key: string, values?: Record<string, string | number>) => string,
  summary: Record<string, number>,
): string {
  const total = Object.values(summary).reduce((a, b) => a + b, 0);
  const done = summary["done"] || 0;
  if (total === 0) return t("groupSummaryEmpty");
  if (done === total) return t("groupSummaryAllDone", { total });
  return t("groupSummaryPartial", { done, total });
}

export default function AssessmentsPage() {
  const t = useTranslations("assessments");
  const tc = useTranslations("common");
  const tRef = useTranslations("reference");
  const [items, setItems] = useState<GroupedAssessmentListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);

  // Create dialog (mode selection + single)
  const [createOpen, setCreateOpen] = useState(false);
  const [createMode, setCreateMode] = useState<"select" | "single" | null>("select");
  const [massOpen, setMassOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);

  const [statusOpen, setStatusOpen] = useState(false);
  const [statusTarget, setStatusTarget] = useState<Assessment | null>(null);
  const [newStatus, setNewStatus] = useState("");

  // Bulk status for groups
  const [bulkStatusOpen, setBulkStatusOpen] = useState(false);
  const [bulkStatusGroupId, setBulkStatusGroupId] = useState<string | null>(null);
  const [bulkNewStatus, setBulkNewStatus] = useState("");

  // Filters — HRP-86: multi-select Types & Statuses.
  const [searchQuery, setSearchQuery] = useState("");
  const [filterTypes, setFilterTypes] = useState<string[]>([]);
  const [filterStatuses, setFilterStatuses] = useState<string[]>([]);

  const [saving, setSaving] = useState(false);

  // Expanded groups
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [groupChildren, setGroupChildren] = useState<Record<string, Assessment[]>>({});

  const { canManage } = usePermissions();

  const typeOptions = useMemo(
    () => TYPE_OPTION_KEYS.map(({ value, labelKey }) => ({
      value,
      label: t(labelKey),
    })),
    [t],
  );
  // HRP-194 REDO: Base UI's <SelectValue/> shows the raw value (status code)
  // unless the Select root receives a value->label map. Build it from the
  // same constants the dropdown items use so the trigger renders e.g.
  // "On review" instead of "on_review" once the user picks an option.
  const statusItems = useMemo(
    () => ASSESSMENT_STATUS_OPTIONS.map((value) => ({
      value,
      label: assessmentStatusLabel(t, value),
    })),
    [t],
  );

  const loadData = useCallback(
    async (
      p: number,
      opts: { search: string; types: string[]; statuses: string[] },
    ) => {
      try {
        const params = new URLSearchParams();
        params.set("skip", String((p - 1) * PAGE_SIZE));
        params.set("limit", String(PAGE_SIZE));
        // HRP-193: push filters to the backend so the X-Y of N counter and
        // pagination follow the filtered slice. Empty filters omit the
        // params entirely (matches the /employees endpoint contract).
        const trimmed = opts.search.trim();
        if (trimmed) params.set("search", trimmed);
        for (const t of opts.types) params.append("type", t);
        for (const s of opts.statuses) params.append("status", s);
        const data = await api.get<GroupedAssessmentList>(
          `/assessments-grouped?${params}`
        );
        setItems(data.items);
        setTotal(data.total);
      } catch {
        // ignore
      }
    },
    [],
  );

  async function loadEmployees() {
    try {
      const eData = await api.get<EmployeeList>("/employees?limit=100");
      setEmployees(eData.items);
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    Promise.all([
      loadData(1, { search: searchQuery, types: filterTypes, statuses: filterStatuses }),
      loadEmployees(),
    ]).finally(() => setLoading(false));
    // First mount only — subsequent reloads driven by the page/filter
    // effects below. searchQuery / filterTypes / filterStatuses are read
    // once so we don't refetch from this effect on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // HRP-193: changing any filter resets to page 1 and reloads from the
  // backend so the visible slice + counter always reflect the filtered
  // result set (mirrors the /employees listing). Debounces the title
  // search so we don't fire a request on every keystroke.
  useEffect(() => {
    const handle = setTimeout(() => {
      setPage(1);
      loadData(1, { search: searchQuery, types: filterTypes, statuses: filterStatuses });
    }, 250);
    return () => clearTimeout(handle);
  }, [searchQuery, filterTypes, filterStatuses, loadData]);

  // Pagination changes (when the filters didn't move): reload the same
  // filtered slice for the new page. Page resets above already trigger
  // their own load, so this guard avoids a duplicate request when the
  // page changes _because_ of a filter change.
  useEffect(() => {
    if (page === 1) return;
    loadData(page, { search: searchQuery, types: filterTypes, statuses: filterStatuses });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  async function toggleGroup(groupId: string) {
    const next = new Set(expandedGroups);
    if (next.has(groupId)) {
      next.delete(groupId);
      setExpandedGroups(next);
      return;
    }
    // Lazy load children
    if (!groupChildren[groupId]) {
      try {
        const detail = await api.get<AssessmentGroupDetail>(
          `/assessment-groups/${groupId}`
        );
        setGroupChildren((prev) => ({
          ...prev,
          [groupId]: detail.assessments,
        }));
      } catch {
        return;
      }
    }
    next.add(groupId);
    setExpandedGroups(next);
  }

  // Create: single
  function openCreate() {
    setCreateMode("select");
    setForm(emptyForm);
    setCreateOpen(true);
  }

  async function handleCreateSingle() {
    if (isPastDeadline(form.ended_at)) {
      toast.error(t("errorDeadlineInPast"));
      return;
    }
    setSaving(true);
    try {
      await api.post("/assessments", {
        ...form,
        ended_at: form.ended_at || null,
      });
      toast.success(t("toastCreated"));
      setCreateOpen(false);
      setForm(emptyForm);
      setCreateMode("select");
      setPage(1);
      await loadData(1, { search: searchQuery, types: filterTypes, statuses: filterStatuses });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorCreateFailed"));
    } finally {
      setSaving(false);
    }
  }

  // Status (single)
  function openStatus(a: Assessment) {
    setStatusTarget(a);
    setNewStatus(a.status_code);
    setStatusOpen(true);
  }

  async function handleStatus() {
    if (!statusTarget) return;
    setSaving(true);
    try {
      await api.post(`/assessments/${statusTarget.id}/status`, {
        status_code: newStatus,
      });
      toast.success(t("toastStatusUpdated"));
      setStatusOpen(false);
      await loadData(page, { search: searchQuery, types: filterTypes, statuses: filterStatuses });
      // Refresh expanded group if the assessment belongs to one
      if (statusTarget.group_id && groupChildren[statusTarget.group_id]) {
        const detail = await api.get<AssessmentGroupDetail>(
          `/assessment-groups/${statusTarget.group_id}`
        );
        setGroupChildren((prev) => ({
          ...prev,
          [statusTarget.group_id!]: detail.assessments,
        }));
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorStatusUpdateFailed"));
    } finally {
      setSaving(false);
    }
  }

  // Bulk status (group)
  function openBulkStatus(groupId: string) {
    setBulkStatusGroupId(groupId);
    setBulkNewStatus("sent");
    setBulkStatusOpen(true);
  }

  async function handleBulkStatus() {
    if (!bulkStatusGroupId) return;
    setSaving(true);
    try {
      const result = await api.post<{
        changed: number;
        skipped: number;
        total: number;
        skipped_reasons?: {
          terminal?: number;
          same_or_lower_status?: number;
          already_cancelled?: number;
          missing_criteria_or_scale?: number;
          deadline_in_past?: number;
          no_completed_participant?: number;
          not_in_on_review?: number;
          manual_in_progress_not_allowed?: number;
        };
      }>(
        `/assessment-groups/${bulkStatusGroupId}/status`,
        { status_code: bulkNewStatus }
      );
      if (result.skipped > 0) {
        const reasons = result.skipped_reasons ?? {};
        const parts: string[] = [];
        if (reasons.terminal)
          parts.push(t("bulkSkipTerminal", { count: reasons.terminal }));
        if (reasons.same_or_lower_status)
          parts.push(
            t("bulkSkipSameStatus", {
              count: reasons.same_or_lower_status,
              status: assessmentStatusLabel(t, bulkNewStatus).toLowerCase(),
            }),
          );
        if (reasons.already_cancelled)
          parts.push(t("bulkSkipCancelled", { count: reasons.already_cancelled }));
        if (reasons.missing_criteria_or_scale)
          parts.push(
            t("bulkSkipMissingCriteria", {
              count: reasons.missing_criteria_or_scale,
            }),
          );
        if (reasons.deadline_in_past)
          parts.push(t("bulkSkipDeadlinePast", { count: reasons.deadline_in_past }));
        if (reasons.manual_in_progress_not_allowed)
          parts.push(t("bulkSkipManualInProgress"));
        const tail = parts.length > 0 ? ` (${parts.join(", ")})` : "";
        // HRP-83: when no child advanced (e.g. every deadline is in the past)
        // this is a failed launch, not a partial success — surface it as an
        // error and mirror the single-assessment phrasing when deadline is the
        // sole reason so the user knows what to fix.
        if (result.changed === 0) {
          const onlyDeadline =
            reasons.deadline_in_past === result.skipped &&
            !reasons.terminal &&
            !reasons.same_or_lower_status &&
            !reasons.already_cancelled &&
            !reasons.missing_criteria_or_scale &&
            !reasons.manual_in_progress_not_allowed;
          // HRP-192: when every child was skipped solely because the modal
          // tried to push them into in_progress, mirror the single-status
          // error copy so the operator immediately knows why nothing moved.
          const onlyManualInProgress =
            reasons.manual_in_progress_not_allowed === result.skipped &&
            !reasons.terminal &&
            !reasons.same_or_lower_status &&
            !reasons.already_cancelled &&
            !reasons.missing_criteria_or_scale &&
            !reasons.deadline_in_past;
          if (onlyDeadline) {
            toast.error(t("errorDeadlineIsInPast"));
          } else if (onlyManualInProgress) {
            toast.error(t(ASSESSMENT_MANUAL_FORBIDDEN_TOOLTIP_KEY));
          } else {
            toast.error(t("bulkNoneUpdated", { tail }));
          }
        } else {
          toast.success(
            t("bulkUpdated", {
              changed: result.changed,
              total: result.total,
              tail,
            }),
          );
        }
      } else {
        toast.success(
          t("bulkUpdated", {
            changed: result.changed,
            total: result.total,
            tail: "",
          }),
        );
      }
      setBulkStatusOpen(false);
      await loadData(page, { search: searchQuery, types: filterTypes, statuses: filterStatuses });
      // Refresh expanded children
      if (expandedGroups.has(bulkStatusGroupId)) {
        const detail = await api.get<AssessmentGroupDetail>(
          `/assessment-groups/${bulkStatusGroupId}`
        );
        setGroupChildren((prev) => ({
          ...prev,
          [bulkStatusGroupId!]: detail.assessments,
        }));
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorUpdateFailed"));
    } finally {
      setSaving(false);
    }
  }

  if (loading)
    return (
      <div className="py-12 text-center text-muted-foreground">
        {tc("loading")}
      </div>
    );

  // HRP-193: filtering is now server-side — `items` is already the filtered
  // slice, so the render path uses it directly and pagination math (X-Y of N)
  // reads off the filtered `total`.
  const filtered = items;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight" data-testid="assessments-heading">{t("title")}</h1>
          <p className="text-sm text-muted-foreground">
            {t("itemsCount", { count: total })}
          </p>
        </div>
        {canManage && (
          <Button data-testid="assessments-btn-create" size="sm" onClick={openCreate}>
            <Plus className="mr-1 h-4 w-4" />
            {t("createAssessment")}
          </Button>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            data-testid="assessments-input-search"
            placeholder={t("searchPlaceholder")}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8"
          />
        </div>
        <MultiSelectFilter
          data-testid="assessments-multi-types"
          options={typeOptions}
          value={filterTypes}
          onChange={setFilterTypes}
          placeholder={t("allTypes")}
          className="w-36"
        />
        <MultiSelectFilter
          data-testid="assessments-multi-statuses"
          options={statusOptions.map((s) => ({
            value: s,
            label: assessmentStatusLabel(t, s),
          }))}
          value={filterStatuses}
          onChange={setFilterStatuses}
          placeholder={t("allStatuses")}
          className="w-36"
        />
        {(searchQuery || filterTypes.length > 0 || filterStatuses.length > 0) && (
          <Button data-testid="assessments-btn-clear-filters" variant="ghost" size="sm" onClick={() => { setSearchQuery(""); setFilterTypes([]); setFilterStatuses([]); setPage(1); }}>
            <X className="mr-1 h-3 w-3" />
            {t("clear")}
          </Button>
        )}
      </div>

      {filtered.length === 0 ? (
        <div data-testid="assessments-empty" className="rounded-lg border border-dashed p-12 text-center text-muted-foreground">
          {(searchQuery || filterTypes.length > 0 || filterStatuses.length > 0)
            ? t("emptyFiltered")
            : t("empty")}
        </div>
      ) : (
        <div className="rounded-lg border">
          <Table data-testid="assessments-table">
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>{t("fieldTitle")}</TableHead>
                <TableHead>{t("fieldType")}</TableHead>
                <TableHead>{t("status")}</TableHead>
                <TableHead />
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((item) => {
                if (item.kind === "single" && item.assessment) {
                  const a = item.assessment;
                  return (
                    <TableRow key={`s-${a.id}`} data-testid={`assessments-row-${a.id}`}>
                      <TableCell />
                      <TableCell className="font-medium">
                        <Link href={`/assessments/${a.id}`} className="hover:underline">
                          {a.title || tc("untitled")}
                        </Link>
                        {/* HRP-333: shared employee summary — name, current
                            position and a status chip when not active. */}
                        {a.employee_name && (
                          <EmployeeSummaryLine
                            employee={{
                              user_name: a.employee_name,
                              position_title: a.employee_position_title,
                              status: a.employee_status,
                            }}
                            className="mt-0.5"
                            nameClassName="text-xs font-normal text-muted-foreground"
                            data-testid={`assessments-row-${a.id}-employee`}
                          />
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">
                          {assessmentTypeTitle(tRef, a)}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge data-testid={`assessments-row-${a.id}-status`} variant="secondary" className={statusColors[a.status_code] || ""}>
                          {assessmentStatusTitle(tRef, a)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {(() => {
                          const d = assessmentRowDate(a);
                          return t("rowDateLabeled", {
                            label: t(d.labelKey),
                            date: formatDate(d.iso),
                          });
                        })()}
                      </TableCell>
                      <TableCell>
                        {canManage && !TERMINAL_STATUSES.has(a.status_code) && (
                          <DropdownMenu>
                            <DropdownMenuTrigger data-testid={`assessments-row-${a.id}-actions`} render={<Button variant="ghost" size="icon-xs" />}>
                              <MoreHorizontal className="h-4 w-4" />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" data-testid={`assessments-row-${a.id}-actions-content`}>
                              <DropdownMenuItem onClick={() => openStatus(a)}>
                                {t("changeStatus")}
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                }

                if (item.kind === "group" && item.group) {
                  const g = item.group;
                  const isExpanded = expandedGroups.has(g.id);
                  const children = groupChildren[g.id] || [];
                  return (
                    <Fragment key={`g-${g.id}`}>
                      <TableRow className="bg-muted/30" data-testid={`assessments-group-${g.id}`}>
                        <TableCell className="w-8">
                          <button
                            data-testid={`assessments-group-${g.id}-toggle`}
                            className="rounded p-0.5 hover:bg-muted"
                            onClick={() => toggleGroup(g.id)}
                          >
                            {isExpanded ? (
                              <ChevronDown className="h-4 w-4" />
                            ) : (
                              <ChevronRight className="h-4 w-4" />
                            )}
                          </button>
                        </TableCell>
                        <TableCell className="font-medium">
                          <div className="flex items-center gap-2">
                            <Users className="h-4 w-4 text-muted-foreground" />
                            <Link
                              href={`/assessment-groups/${g.id}`}
                              className="hover:underline"
                              data-testid={`assessments-group-${g.id}-link`}
                            >
                              {g.title}
                            </Link>
                            <Badge variant="outline" className="text-xs">
                              {t("employeesCount", { count: g.assessment_count })}
                            </Badge>
                          </div>
                        </TableCell>
                        <TableCell>
                          {g.type_code && g.type_title && (
                            <Badge variant="secondary">
                              {assessmentTypeTitle(tRef, {
                                type_code: g.type_code,
                                type_title: g.type_title,
                              })}
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          <span className="text-sm text-muted-foreground">
                            {statusSummaryText(t, g.status_summary)}
                          </span>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {t("rowDateLabeled", {
                            label: t("dateCreated"),
                            date: formatDate(g.created_at),
                          })}
                        </TableCell>
                        <TableCell>
                          {canManage && (
                            <DropdownMenu>
                              <DropdownMenuTrigger render={<Button variant="ghost" size="icon-xs" />}>
                                <MoreHorizontal className="h-4 w-4" />
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuItem onClick={() => openBulkStatus(g.id)}>
                                  {t("changeStatusAll")}
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          )}
                        </TableCell>
                      </TableRow>
                      {isExpanded &&
                        children.map((a) => (
                          <TableRow key={`gc-${a.id}`} className="bg-muted/10" data-testid={`assessments-row-${a.id}`}>
                            <TableCell />
                            <TableCell className="font-medium pl-10">
                              <Link href={`/assessments/${a.id}`} className="hover:underline">
                                {a.employee_name || a.title || tc("untitled")}
                              </Link>
                              {/* HRP-333: position + status chip under the
                                  employee link (name already rendered). */}
                              <EmployeeSummaryLine
                                employee={{
                                  user_name: a.employee_name,
                                  position_title: a.employee_position_title,
                                  status: a.employee_status,
                                }}
                                hideName
                                data-testid={`assessments-row-${a.id}-employee`}
                              />
                            </TableCell>
                            <TableCell>
                        <Badge variant="secondary">
                          {assessmentTypeTitle(tRef, a)}
                        </Badge>
                      </TableCell>
                            <TableCell>
                              <Badge data-testid={`assessments-row-${a.id}-status`} variant="secondary" className={statusColors[a.status_code] || ""}>
                                {assessmentStatusTitle(tRef, a)}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-muted-foreground">
                              {(() => {
                                const d = assessmentRowDate(a);
                                return t("rowDateLabeled", {
                                  label: t(d.labelKey),
                                  date: formatDate(d.iso),
                                });
                              })()}
                            </TableCell>
                            <TableCell>
                              {canManage && !TERMINAL_STATUSES.has(a.status_code) && (
                                <DropdownMenu>
                                  <DropdownMenuTrigger data-testid={`assessments-row-${a.id}-actions`} render={<Button variant="ghost" size="icon-xs" />}>
                                    <MoreHorizontal className="h-4 w-4" />
                                  </DropdownMenuTrigger>
                                  <DropdownMenuContent align="end" data-testid={`assessments-row-${a.id}-actions-content`}>
                                    <DropdownMenuItem onClick={() => openStatus(a)}>
                                      {t("changeStatus")}
                                    </DropdownMenuItem>
                                  </DropdownMenuContent>
                                </DropdownMenu>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                    </Fragment>
                  );
                }
                return null;
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />

      {/* Create dialog — mode selection + single form */}
      <Dialog
        open={createOpen}
        onOpenChange={(val) => {
          setCreateOpen(val);
          if (!val) setCreateMode("select");
        }}
      >
        <DialogContent data-testid={createMode === "select" ? "assessments-modal-mode" : "assessments-modal-create"}>
          {createMode === "select" && (
            <>
              <DialogHeader><DialogTitle>{t("createAssessment")}</DialogTitle></DialogHeader>
              <div className="grid grid-cols-2 gap-3">
                <button
                  data-testid="assessments-modal-mode-btn-single"
                  className="flex flex-col items-center gap-2 rounded-lg border p-6 text-center hover:border-primary hover:bg-muted/50 transition-colors"
                  onClick={() => setCreateMode("single")}
                >
                  <User className="h-8 w-8 text-muted-foreground" />
                  <span className="text-sm font-medium">{t("modeSingle")}</span>
                  <span className="text-xs text-muted-foreground">{t("modeSingleHint")}</span>
                </button>
                <button
                  data-testid="assessments-modal-mode-btn-mass"
                  className="flex flex-col items-center gap-2 rounded-lg border p-6 text-center hover:border-primary hover:bg-muted/50 transition-colors"
                  onClick={() => {
                    setCreateOpen(false);
                    setCreateMode("select");
                    setMassOpen(true);
                  }}
                >
                  <Users className="h-8 w-8 text-muted-foreground" />
                  <span className="text-sm font-medium">{t("modeMass")}</span>
                  <span className="text-xs text-muted-foreground">{t("modeMassHint")}</span>
                </button>
              </div>
            </>
          )}

          {createMode === "single" && (
            <>
              <DialogHeader><DialogTitle>{t("createAssessment")}</DialogTitle></DialogHeader>
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label>{t("fieldTitle")}</Label>
                  <Input data-testid="assessments-modal-create-input-title" maxLength={100} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
                </div>
                <div className="space-y-2">
                  <Label>{tc("employee")}</Label>
                  <Select value={form.employee_id} onValueChange={(val) => setForm({ ...form, employee_id: val ?? "" })}>
                    <SelectTrigger className="w-full" data-testid="assessments-modal-create-select-employee">
                      <SelectValue placeholder={t("selectEmployee")}>
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
                  <Label>{t("fieldType")}</Label>
                  <Select value={form.type_code} onValueChange={(val) => setForm({ ...form, type_code: val ?? "" })}>
                    <SelectTrigger className="w-full" data-testid="assessments-modal-create-select-type">
                      <SelectValue>
                        {typeOptions.find((t) => t.value === form.type_code)?.label ?? ""}
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {typeOptions.map((t) => (
                        <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>{t("fieldEndDate")}</Label>
                  {/* HRP-335: shared DatePicker (HRP-152) instead of the
                      native date input. */}
                  <DatePicker
                    data-testid="assessments-modal-create-input-end-date"
                    min={todayLocalISO()}
                    value={form.ended_at}
                    onChange={(value) => setForm({ ...form, ended_at: value })}
                  />
                  {isPastDeadline(form.ended_at) && (
                    <p className="text-xs text-destructive">{t("errorDeadlineInPast")}</p>
                  )}
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setCreateMode("select")} disabled={saving}>{t("back")}</Button>
                <Button data-testid="assessments-modal-create-btn-submit" onClick={handleCreateSingle} disabled={saving}>{saving ? t("creating") : t("createShort")}</Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Mass create dialog */}
      <MassCreateDialog
        open={massOpen}
        onOpenChange={setMassOpen}
        onCreated={() => {
          setPage(1);
          loadData(1, { search: searchQuery, types: filterTypes, statuses: filterStatuses });
        }}
      />

      {/* Status dialog (single) */}
      <Dialog open={statusOpen} onOpenChange={setStatusOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{t("changeStatus")}</DialogTitle></DialogHeader>
          <div className="space-y-2">
            <Label>{t("newStatus")}</Label>
            <Select value={newStatus} items={statusItems} onValueChange={setNewStatus}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {statusOptions.map((s) => {
                  const forbidden = ASSESSMENT_MANUAL_FORBIDDEN_STATUSES.has(s);
                  return (
                    <SelectItem
                      key={s}
                      value={s}
                      disabled={forbidden}
                      data-testid={`assessments-status-option-${s}`}
                    >
                      {assessmentStatusLabel(t, s)}
                      {forbidden && (
                        <ManualForbiddenHint testId={`assessments-status-option-${s}-hint`} />
                      )}
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setStatusOpen(false)} disabled={saving}>{tc("cancel")}</Button>
            <Button onClick={handleStatus} disabled={saving}>{saving ? t("saving") : t("save")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk status dialog (group) */}
      <Dialog open={bulkStatusOpen} onOpenChange={setBulkStatusOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{t("changeStatusAllTitle")}</DialogTitle></DialogHeader>
          <div className="space-y-2">
            <Label>{t("newStatusAll")}</Label>
            <Select value={bulkNewStatus} items={statusItems} onValueChange={setBulkNewStatus}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {statusOptions.map((s) => {
                  const forbidden = ASSESSMENT_MANUAL_FORBIDDEN_STATUSES.has(s);
                  return (
                    <SelectItem
                      key={s}
                      value={s}
                      disabled={forbidden}
                      data-testid={`assessments-bulk-status-option-${s}`}
                    >
                      {assessmentStatusLabel(t, s)}
                      {forbidden && (
                        <ManualForbiddenHint testId={`assessments-bulk-status-option-${s}-hint`} />
                      )}
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setBulkStatusOpen(false)} disabled={saving}>{tc("cancel")}</Button>
            <Button onClick={handleBulkStatus} disabled={saving}>{saving ? t("saving") : t("applyToAll")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
