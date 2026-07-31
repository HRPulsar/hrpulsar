"use client";

import { Fragment, useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type {
  Position,
  PositionLifecycleStatus,
  PositionList,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { CostConfirmDialog } from "@/components/billing/cost-confirm-dialog";
import { CompanyTabs } from "@/components/company/company-tabs";
import {
  PositionStatusBadge,
  POSITION_LIFECYCLE_FLOW,
  POSITION_LIFECYCLE_LABEL_KEY,
} from "@/components/positions/PositionStatusBadge";
import { PositionOccupancyDrilldown } from "@/components/positions/PositionOccupancyDrilldown";
import { PositionEditDialog } from "@/components/positions/PositionEditDialog";
import { ActiveAiSessionBadge } from "@/components/competence-generation/ActiveAiSessionBadge";
import { useActiveAiSessions } from "@/hooks/use-active-ai-sessions";
import { findMatrixSessionForSpec } from "@/lib/active-ai-session-match";
import { activeSessionRoute } from "@/lib/active-ai-session-route";
import { usePermissions } from "@/hooks/use-permissions";
import { useCostConfirmationDialog } from "@/hooks/use-cost-confirmation";
import { toast } from "sonner";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  MoreHorizontal,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";

const LIFECYCLE_OPTIONS: PositionLifecycleStatus[] = [
  "active",
  "on_hold",
  "frozen",
  "closed",
];

// HRP-57 § 7.3 (E6): non-empty filter set the list page exposes. `lifecycle`
// is server-side; `vacancies` and `unconfigured` are toggle pills.
type LifecycleFilter = PositionLifecycleStatus | "all";
type GroupBy = "none" | "division" | "specialization";

export default function PositionsPage() {
  const t = useTranslations("company");
  const tc = useTranslations("common");
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  // HRP-72: server-side filters drive the request; group-by is purely a
  // client-side reorder of the same rows.
  const [lifecycleFilter, setLifecycleFilter] = useState<LifecycleFilter>("all");
  const [hasVacancies, setHasVacancies] = useState(false);
  const [matrixUnconfigured, setMatrixUnconfigured] = useState(false);
  const [groupBy, setGroupBy] = useState<GroupBy>("none");

  // Single dialog drives both create (editingPosition === null) and edit
  // (editingPosition === <row>). Reference data + cascade live in
  // PositionEditDialog itself.
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingPosition, setEditingPosition] = useState<Position | null>(null);

  // Delete
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletingPos, setDeletingPos] = useState<Position | null>(null);
  const [saving, setSaving] = useState(false);

  // Action loading (approve/reject)
  const [actionLoading, setActionLoading] = useState(false);

  // AI generation
  const [generating, setGenerating] = useState(false);

  // Headcount drill-down
  const [drilldownOpen, setDrilldownOpen] = useState(false);
  const [drilldownPosition, setDrilldownPosition] = useState<Position | null>(
    null,
  );

  function openHeadcountDrilldown(pos: Position) {
    setDrilldownPosition(pos);
    setDrilldownOpen(true);
  }

  const { canManage } = usePermissions();
  const router = useRouter();
  // HRP-33 REDO: highlight rows whose specialization currently has an
  // active AI matrix session, so the operator can spot in-flight work
  // from the list view and one-click jump back to the live drawer.
  const { all: activeAiSessions } = useActiveAiSessions();

  async function loadPositions() {
    try {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      if (lifecycleFilter !== "all")
        params.set("lifecycle_status", lifecycleFilter);
      if (hasVacancies) params.set("has_vacancies", "true");
      if (matrixUnconfigured) params.set("matrix_unconfigured", "true");
      params.set("limit", "100");
      const data = await api.get<PositionList>(`/positions?${params}`);
      setPositions(data.items);
    } catch {
      toast.error(t("toastPositionsLoadFailed"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadPositions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Search is debounced; structured filters apply immediately.
  useEffect(() => {
    const timeout = setTimeout(loadPositions, 300);
    return () => clearTimeout(timeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  useEffect(() => {
    void loadPositions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lifecycleFilter, hasVacancies, matrixUnconfigured]);

  function openCreate() {
    setEditingPosition(null);
    setDialogOpen(true);
  }

  function openEdit(pos: Position) {
    if (pos.lifecycle_status === "closed") {
      toast.error(t("errorPositionClosed"));
      return;
    }
    setEditingPosition(pos);
    setDialogOpen(true);
  }

  async function handleSetStatus(
    pos: Position,
    next: PositionLifecycleStatus,
  ) {
    try {
      await api.post(`/positions/${pos.id}/status`, {
        lifecycle_status: next,
      });
      toast.success(
        t("toastStatusChanged", { status: t(POSITION_LIFECYCLE_LABEL_KEY[next]) }),
      );
      await loadPositions();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("toastStatusUpdateFailed"),
      );
    }
  }

  // Delete
  function openDelete(pos: Position) {
    setDeletingPos(pos);
    setDeleteOpen(true);
  }

  async function confirmDelete() {
    if (!deletingPos) return;
    setSaving(true);
    try {
      await api.delete(`/positions/${deletingPos.id}`);
      toast.success(t("toastPositionDeleted"));
      setDeleteOpen(false);
      await loadPositions();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastDeleteFailed"));
    } finally {
      setSaving(false);
    }
  }

  const aiGenerateConfirm = useCostConfirmationDialog(
    "ai.generate_positions",
    t("aiPositionGeneration"),
  );

  async function runAIGenerate() {
    setGenerating(true);
    try {
      await api.postAndWait("/ai/generate-positions");
      toast.success(t("toastAiPositionsGenerated"));
      await loadPositions();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastAiGenerateFailed"));
    } finally {
      setGenerating(false);
    }
  }

  async function handleAIGenerate() {
    try {
      await aiGenerateConfirm.runWithConfirmation(runAIGenerate);
    } catch (err) {
      if (err instanceof Error && err.message === "cancelled") return;
      throw err;
    }
  }

  async function handleBulkAction(action: "approve" | "reject") {
    const draftIds = positions
      .filter((p) => p.source === "ai_draft")
      .map((p) => p.id);
    if (draftIds.length === 0) return;
    setActionLoading(true);
    try {
      await api.post("/positions/bulk-action", { ids: draftIds, action });
      toast.success(
        action === "approve"
          ? t("toastDraftsApproved")
          : t("toastDraftsRejected"),
      );
      await loadPositions();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastActionFailed"));
    } finally {
      setActionLoading(false);
    }
  }

  async function handleApprove(id: string) {
    setActionLoading(true);
    try {
      await api.post("/positions/bulk-action", {
        ids: [id],
        action: "approve",
      });
      toast.success(t("toastPositionApproved"));
      await loadPositions();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastApproveFailed"));
    } finally {
      setActionLoading(false);
    }
  }

  async function handleReject(id: string) {
    setActionLoading(true);
    try {
      await api.post("/positions/bulk-action", {
        ids: [id],
        action: "reject",
      });
      toast.success(t("toastPositionRejected"));
      await loadPositions();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastRejectFailed"));
    } finally {
      setActionLoading(false);
    }
  }

  const approved = positions.filter((p) => p.source !== "ai_draft");
  const drafts = positions.filter((p) => p.source === "ai_draft");

  // HRP-72 § 7.3: client-side group-by (Division / Specialization / none).
  // Server returns the rows already filtered; grouping is purely a visual
  // reorder that inserts header rows. "Unassigned" buckets the null case.
  const approvedGroups: { key: string; label: string; rows: Position[] }[] = (() => {
    if (groupBy === "none") {
      return [{ key: "all", label: "", rows: approved }];
    }
    const buckets = new Map<string, { label: string; rows: Position[] }>();
    for (const pos of approved) {
      const label =
        groupBy === "division"
          ? pos.division_name ?? t("unassigned")
          : pos.specialization_title ?? t("noSpecialization");
      const bucket = buckets.get(label) ?? { label, rows: [] };
      bucket.rows.push(pos);
      buckets.set(label, bucket);
    }
    return [...buckets.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, b]) => ({ key, ...b }));
  })();
  const filtersActive =
    lifecycleFilter !== "all" || hasVacancies || matrixUnconfigured;
  function clearFilters() {
    setLifecycleFilter("all");
    setHasVacancies(false);
    setMatrixUnconfigured(false);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        {tc("loading")}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
          <p className="text-sm text-muted-foreground">{t("subtitle")}</p>
        </div>
      </div>

      <CompanyTabs />

      {/* Header actions */}
      <div className="flex items-center justify-between">
        <Input
          data-testid="positions-search"
          placeholder={t("searchPositionsPlaceholder")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        {canManage && (
          <div className="flex gap-2">
            <Button
              data-testid="positions-btn-ai-generate"
              variant="outline"
              size="sm"
              onClick={handleAIGenerate}
              disabled={generating}
            >
              <Sparkles className="mr-1 h-4 w-4" />
              {generating ? t("generating") : t("aiGenerate")}
            </Button>
            <Button
              data-testid="positions-btn-create"
              size="sm"
              onClick={openCreate}
            >
              <Plus className="mr-1 h-4 w-4" />
              {t("addPosition")}
            </Button>
          </div>
        )}
      </div>

      {/* HRP-60: AI-generated drafts requiring validation are surfaced at the
          top of the page so the operator sees them before the approved list. */}
      {drafts.length > 0 && (
        <Card
          data-testid="positions-draft-card"
          className="border-blue-200 bg-blue-50/40 dark:border-blue-900 dark:bg-blue-950/40"
        >
          <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
            <CardTitle className="text-base">
              {t("draftsAwaitingReview", { count: drafts.length })}
            </CardTitle>
            <div className="flex gap-2">
              <Button
                data-testid="positions-btn-approve-all"
                size="sm"
                variant="outline"
                onClick={() => handleBulkAction("approve")}
                disabled={actionLoading}
              >
                <Check className="mr-1 h-4 w-4" />
                {t("approveAll")}
              </Button>
              <Button
                data-testid="positions-btn-reject-all"
                size="sm"
                variant="outline"
                onClick={() => handleBulkAction("reject")}
                disabled={actionLoading}
              >
                <X className="mr-1 h-4 w-4" />
                {t("rejectAllDrafts")}
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="overflow-hidden rounded-lg border">
              <Table data-testid="positions-draft-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("colPositionTitle")}</TableHead>
                    <TableHead>{t("specialization")}</TableHead>
                    <TableHead>{t("grade")}</TableHead>
                    <TableHead>{t("division")}</TableHead>
                    <TableHead>{t("colFilledPlan")}</TableHead>
                    <TableHead className="w-32" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {drafts.map((pos) => (
                    <TableRow
                      key={pos.id}
                      data-testid={`positions-row-${pos.id}`}
                      className="bg-blue-50/50 dark:bg-blue-950/20"
                    >
                      <TableCell className="font-medium">{pos.title}</TableCell>
                      <TableCell>{pos.specialization_title || "—"}</TableCell>
                      <TableCell>{pos.grade_title || "—"}</TableCell>
                      <TableCell data-testid={`positions-row-${pos.id}-division`}>
                        {pos.division_name || "—"}
                      </TableCell>
                      <TableCell>
                        {pos.headcount != null ? `0/${pos.headcount}` : "—"}
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          <Button
                            data-testid={`positions-row-${pos.id}-btn-approve`}
                            variant="ghost"
                            size="icon-xs"
                            onClick={() => handleApprove(pos.id)}
                            title={t("approve")}
                            aria-label={t("approve")}
                            disabled={actionLoading}
                          >
                            <Check className="h-4 w-4 text-green-600" />
                          </Button>
                          <Button
                            data-testid={`positions-row-${pos.id}-btn-reject`}
                            variant="ghost"
                            size="icon-xs"
                            onClick={() => handleReject(pos.id)}
                            title={t("reject")}
                            aria-label={t("reject")}
                            disabled={actionLoading}
                          >
                            <X className="h-4 w-4 text-red-600" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            onClick={() => openEdit(pos)}
                            title={t("editBeforeApproving")}
                            aria-label={t("editBeforeApproving")}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* HRP-72 § 7.3: filters + grouping toolbar. Filters are server-side
          (re-fetch on change); grouping is client-only (re-render only). */}
      <div
        data-testid="positions-filters"
        className="flex flex-wrap items-center gap-2"
      >
        <Select
          value={lifecycleFilter}
          onValueChange={(v) => setLifecycleFilter(v as LifecycleFilter)}
        >
          <SelectTrigger
            className="w-44"
            data-testid="positions-filter-lifecycle"
          >
            <SelectValue>
              {lifecycleFilter === "all"
                ? t("allStatuses")
                : t(POSITION_LIFECYCLE_LABEL_KEY[lifecycleFilter])}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("allStatuses")}</SelectItem>
            {LIFECYCLE_OPTIONS.map((status) => (
              <SelectItem key={status} value={status}>
                {t(POSITION_LIFECYCLE_LABEL_KEY[status])}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button
          data-testid="positions-filter-vacancies"
          size="sm"
          variant={hasVacancies ? "default" : "outline"}
          onClick={() => setHasVacancies((v) => !v)}
        >
          <AlertTriangle className="mr-1 h-4 w-4" />
          {t("hasVacancies")}
        </Button>

        <Button
          data-testid="positions-filter-matrix-unconfigured"
          size="sm"
          variant={matrixUnconfigured ? "default" : "outline"}
          onClick={() => setMatrixUnconfigured((v) => !v)}
        >
          <AlertTriangle className="mr-1 h-4 w-4" />
          {t("matrixNotConfigured")}
        </Button>

        {filtersActive ? (
          <Button
            data-testid="positions-filter-clear"
            size="sm"
            variant="ghost"
            onClick={clearFilters}
          >
            <X className="mr-1 h-4 w-4" />
            {t("clear")}
          </Button>
        ) : null}

        <div className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
          <span>{t("groupBy")}</span>
          {(["none", "division", "specialization"] as GroupBy[]).map((g) => (
            <Button
              key={g}
              data-testid={`positions-group-${g}`}
              size="sm"
              variant={groupBy === g ? "default" : "ghost"}
              onClick={() => setGroupBy(g)}
            >
              {g === "none"
                ? t("none")
                : g === "division"
                  ? t("division")
                  : t("specialization")}
            </Button>
          ))}
        </div>
      </div>

      {/* Table */}
      <Table data-testid="positions-table">
        <TableHeader>
          <TableRow>
            <TableHead>{t("colPositionTitle")}</TableHead>
            <TableHead>{t("specialization")}</TableHead>
            <TableHead>{t("grade")}</TableHead>
            <TableHead>{t("division")}</TableHead>
            <TableHead>{t("status")}</TableHead>
            <TableHead>{t("colFilledPlan")}</TableHead>
            <TableHead>{t("colMatrix")}</TableHead>
            <TableHead>{t("colSource")}</TableHead>
            <TableHead className="w-12" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {approvedGroups.map((group) => (
            <Fragment key={group.key}>
              {groupBy !== "none" ? (
                <TableRow
                  data-testid={`positions-group-header-${group.key}`}
                  className="bg-muted/40"
                >
                  <TableCell
                    colSpan={9}
                    className="py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground"
                  >
                    {group.label} · {group.rows.length}
                  </TableCell>
                </TableRow>
              ) : null}
              {group.rows.map((pos) => {
                const activeSession = findMatrixSessionForSpec(
                  activeAiSessions,
                  pos.specialization_id,
                );
                return (
                <TableRow
                  key={pos.id}
                  data-testid={`positions-row-${pos.id}`}
                  className={activeSession ? "bg-primary/5" : undefined}
                >
                  <TableCell className="font-medium">
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/company/positions/${pos.id}`}
                        data-testid={`positions-row-${pos.id}-link`}
                        className="hover:underline"
                      >
                        {pos.title}
                      </Link>
                      {activeSession ? (
                        <ActiveAiSessionBadge
                          sessions={[activeSession]}
                          onOpen={() =>
                            router.push(
                              activeSessionRoute({
                                id: activeSession.session_id,
                                scope: activeSession.scope,
                                target_id: activeSession.target_id,
                                status: activeSession.status,
                                // HRP-33 review fix: only carry the
                                // session's true originating position id —
                                // not this row's id. Routing the badge to
                                // an unrelated position would land Apply
                                // on the wrong page.
                                params: {
                                  position_id: activeSession.position_id,
                                },
                              }),
                            )
                          }
                          testIdSuffix={`positions-row-${pos.id}`}
                        />
                      ) : null}
                    </div>
                  </TableCell>
                  {/* HRP-54: clickable spec/grade in the column when set,
                      CTA «Set» to open the edit dialog when missing — so the
                      operator can wire spec/grade in without navigating to
                      the detail page first. */}
                  <TableCell>
                    {pos.specialization_id && pos.specialization_title ? (
                      <Link
                        href={`/company/specializations/${pos.specialization_id}`}
                        data-testid={`positions-row-${pos.id}-specialization-link`}
                        className="text-primary hover:underline"
                      >
                        {pos.specialization_title}
                      </Link>
                    ) : canManage ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        data-testid={`positions-row-${pos.id}-btn-set-specialization`}
                        onClick={() => openEdit(pos)}
                      >
                        <Plus className="mr-1 h-3 w-3" />
                        {t("setSpecialization")}
                      </Button>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell>
                    {pos.grade_id && pos.grade_title ? (
                      pos.specialization_id ? (
                        <Link
                          href={`/company/specializations/${pos.specialization_id}/matrix?grade_id=${pos.grade_id}`}
                          data-testid={`positions-row-${pos.id}-grade-link`}
                          className="text-primary hover:underline"
                        >
                          {pos.grade_title}
                        </Link>
                      ) : (
                        pos.grade_title
                      )
                    ) : canManage ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        data-testid={`positions-row-${pos.id}-btn-set-grade`}
                        onClick={() => openEdit(pos)}
                      >
                        <Plus className="mr-1 h-3 w-3" />
                        {t("setGrade")}
                      </Button>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell data-testid={`positions-row-${pos.id}-division`}>
                    {pos.division_name || "—"}
                  </TableCell>
                  <TableCell>
                    <PositionStatusBadge
                      status={pos.lifecycle_status}
                      testId={`positions-row-${pos.id}-status`}
                    />
                  </TableCell>
                  <TableCell>
                    <button
                      type="button"
                      data-testid={`positions-row-${pos.id}-headcount`}
                      className="text-left underline-offset-2 hover:underline"
                      onClick={() => openHeadcountDrilldown(pos)}
                    >
                      {pos.headcount != null
                        ? `${pos.employee_count}/${pos.headcount}`
                        : pos.employee_count}
                    </button>
                  </TableCell>
                  <TableCell data-testid={`positions-row-${pos.id}-matrix`}>
                    {pos.specialization_id && pos.grade_id ? (
                      pos.matrix_configured ? (
                        <span
                          className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-400"
                          title={t("matrixConfigured")}
                        >
                          <CheckCircle2 className="h-4 w-4" />
                        </span>
                      ) : (
                        <span
                          className="inline-flex items-center gap-1 text-amber-700 dark:text-amber-400"
                          title={t("matrixNotConfiguredProfile")}
                        >
                          <AlertTriangle className="h-4 w-4" />
                        </span>
                      )
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
              <TableCell>
                <Badge variant="outline">
                  {pos.source === "ai_approved" ? t("sourceAi") : t("sourceManual")}
                </Badge>
              </TableCell>
              <TableCell>
                {canManage && (
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      render={<Button variant="ghost" size="icon-xs" />}
                      data-testid={`positions-row-${pos.id}-actions`}
                    >
                      <MoreHorizontal className="h-4 w-4" />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        onClick={() => openEdit(pos)}
                        disabled={pos.lifecycle_status === "closed"}
                        data-testid={`positions-row-${pos.id}-btn-edit`}
                      >
                        <Pencil className="mr-2 h-4 w-4" />
                        {t("edit")}
                      </DropdownMenuItem>
                      {POSITION_LIFECYCLE_FLOW[pos.lifecycle_status].map(
                        (next) => (
                          <DropdownMenuItem
                            key={next}
                            onClick={() => handleSetStatus(pos, next)}
                            data-testid={`positions-row-${pos.id}-btn-status-${next}`}
                          >
                            {t("setStatusTo", {
                              status: t(POSITION_LIFECYCLE_LABEL_KEY[next]),
                            })}
                          </DropdownMenuItem>
                        ),
                      )}
                      {pos.employee_count === 0 && (
                        <DropdownMenuItem
                          variant="destructive"
                          onClick={() => openDelete(pos)}
                        >
                          <Trash2 className="mr-2 h-4 w-4" />
                          {tc("delete")}
                        </DropdownMenuItem>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </TableCell>
            </TableRow>
                );
              })}
            </Fragment>
          ))}
          {approved.length === 0 && (
            <TableRow>
              <TableCell
                colSpan={9}
                className="py-8 text-center text-muted-foreground"
              >
                {filtersActive
                  ? t("positionsNoMatches")
                  : t("positionsEmpty")}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      {/* HRP-69: Single dialog handles both create and edit. The component
          fetches its own reference data and runs the Spec → Grade cascade. */}
      <PositionEditDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        position={editingPosition}
        onSaved={loadPositions}
      />

      {/* Delete confirmation */}
      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={t("deletePosition")}
        description={t("deletePositionConfirm", {
          title: deletingPos?.title ?? "",
        })}
        onConfirm={confirmDelete}
        loading={saving}
      />

      <CostConfirmDialog
        open={aiGenerateConfirm.open}
        onOpenChange={aiGenerateConfirm.setOpen}
        actionLabel={aiGenerateConfirm.pendingLabel}
        cost={aiGenerateConfirm.cost}
        threshold={aiGenerateConfirm.threshold}
        onConfirm={aiGenerateConfirm.confirm}
        onCancel={aiGenerateConfirm.cancel}
        testId="ai-positions-cost-confirm"
      />

      {/* Headcount drill-down */}
      <PositionOccupancyDrilldown
        open={drilldownOpen}
        onOpenChange={setDrilldownOpen}
        position={
          drilldownPosition
            ? {
                id: drilldownPosition.id,
                title: drilldownPosition.title,
                headcount: drilldownPosition.headcount,
                employee_count: drilldownPosition.employee_count,
              }
            : null
        }
      />
    </div>
  );
}
