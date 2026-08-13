"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  CheckCircle2,
  ChevronRight,
  ExternalLink,
  Pencil,
  Plus,
  Settings2,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { getDefaultSalaryCurrency } from "@/lib/currency";
import { usePermissions } from "@/hooks/use-permissions";
import { inlineEditKeys, useInlineEdit } from "@/hooks/use-inline-edit";
import { useTreeExpansion } from "@/hooks/use-tree-expansion";
import type {
  Position,
  PositionLifecycleStatus,
  PositionMatrix,
  PositionMatrixCompetence,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { TreeExpandControls } from "@/components/ui/tree-expand-controls";
import {
  PositionStatusBadge,
  POSITION_LIFECYCLE_FLOW,
  POSITION_LIFECYCLE_LABEL_KEY,
} from "@/components/positions/PositionStatusBadge";
import { PositionAIGenerationCard } from "@/components/positions/PositionAIGenerationCard";
import { PositionEditDialog } from "@/components/positions/PositionEditDialog";
import {
  EmployeeList,
  type EmployeeListItem,
} from "@/components/employees/EmployeeListRow";
import { ActiveAiSessionBadge } from "@/components/competence-generation/ActiveAiSessionBadge";
import { GenerationDrawer } from "@/components/competence-generation/GenerationDrawer";
import {
  activeAiSessionsKey,
  useActiveAiSessions,
  type ActiveAiSession,
} from "@/hooks/use-active-ai-sessions";

// HRP-32 redo: bucket the flat competence list by group so the matrix
// can render as a two-level tree (group → competences) instead of one
// long flat list. Order is preserved by first-appearance to keep the
// visual cadence stable across reloads.
interface MatrixGroupBucket {
  groupId: string;
  groupTitle: string;
  competences: PositionMatrixCompetence[];
}

function bucketByGroup(
  competences: PositionMatrixCompetence[],
  ungroupedLabel: string,
): MatrixGroupBucket[] {
  const map = new Map<string, MatrixGroupBucket>();
  for (const c of competences) {
    const existing = map.get(c.group_id);
    if (existing) {
      existing.competences.push(c);
    } else {
      map.set(c.group_id, {
        groupId: c.group_id,
        groupTitle: c.group_title ?? ungroupedLabel,
        competences: [c],
      });
    }
  }
  return [...map.values()];
}

function MatrixTree({
  competences,
  activeSessionsMap,
  onOpenActiveSession,
}: {
  competences: PositionMatrixCompetence[];
  activeSessionsMap: Map<string, ActiveAiSession[]>;
  onOpenActiveSession: (sessionId: string) => void;
}) {
  const t = useTranslations("company");
  const buckets = useMemo(
    () => bucketByGroup(competences, t("ungrouped")),
    [competences, t],
  );
  const groupIds = useMemo(() => buckets.map((b) => b.groupId), [buckets]);
  const competenceIds = useMemo(
    () => competences.map((c) => c.competence_id),
    [competences],
  );

  // Groups default to expanded so the operator sees structure at a glance;
  // indicators stay folded behind each competence so the tree reads as a
  // compact list of (group → competence → required level) — Veronica's
  // ask in HRP-32 was that the page not feel like a flat dump.
  const groupExpansion = useTreeExpansion(groupIds, "all");
  const competenceExpansion = useTreeExpansion(competenceIds, "none");

  return (
    <div data-testid="position-detail-matrix" className="space-y-3">
      <div className="flex justify-end">
        <TreeExpandControls
          expandAll={competenceExpansion.expandAll}
          collapseAll={competenceExpansion.collapseAll}
          allExpanded={competenceExpansion.allExpanded}
          allCollapsed={competenceExpansion.allCollapsed}
          testIdPrefix="position-detail-matrix"
          size="xs"
        />
      </div>
      {buckets.map((bucket) => {
        const groupOpen = groupExpansion.isExpanded(bucket.groupId);
        return (
          <div
            key={bucket.groupId}
            data-testid={`position-detail-matrix-group-${bucket.groupId}`}
            className="rounded-md border"
          >
            <button
              type="button"
              data-testid={`position-detail-matrix-group-${bucket.groupId}-toggle`}
              aria-expanded={groupOpen}
              onClick={() => groupExpansion.toggle(bucket.groupId)}
              className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left transition-colors hover:bg-muted"
            >
              <ChevronRight
                className={`h-4 w-4 text-muted-foreground transition-transform ${groupOpen ? "rotate-90" : ""}`}
              />
              <span className="text-sm font-medium">{bucket.groupTitle}</span>
              <span className="ml-auto text-xs text-muted-foreground">
                {t("competenceCount", { count: bucket.competences.length })}
              </span>
            </button>
            {groupOpen ? (
              <ul className="border-t">
                {bucket.competences.map((c) => {
                  const compOpen = competenceExpansion.isExpanded(
                    c.competence_id,
                  );
                  const compSessions =
                    activeSessionsMap.get(
                      activeAiSessionsKey(
                        "competence_indicators",
                        c.competence_id,
                      ),
                    ) ?? [];
                  const compIsLitUp = compSessions.length > 0;
                  return (
                    <li
                      key={c.competence_id}
                      data-testid={`position-detail-matrix-row-${c.competence_id}`}
                      className={`border-t first:border-t-0 ${
                        compIsLitUp ? "bg-primary/5" : ""
                      }`}
                    >
                      <button
                        type="button"
                        data-testid={`position-detail-matrix-row-${c.competence_id}-toggle`}
                        aria-expanded={compOpen}
                        onClick={() =>
                          competenceExpansion.toggle(c.competence_id)
                        }
                        className="flex w-full items-center gap-2 px-3 py-2 pl-8 text-left transition-colors hover:bg-muted"
                      >
                        <ChevronRight
                          className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${compOpen ? "rotate-90" : ""} ${
                            c.indicators.length === 0
                              ? "invisible"
                              : ""
                          }`}
                        />
                        <span className="text-sm">{c.title}</span>
                        {compIsLitUp ? (
                          <ActiveAiSessionBadge
                            sessions={compSessions}
                            onOpen={onOpenActiveSession}
                            testIdSuffix={`position-comp-${c.competence_id}`}
                          />
                        ) : null}
                        <span className="ml-auto inline-flex items-center gap-2">
                          {c.skill_level_title ? (
                            <Badge
                              variant="outline"
                              data-testid={`position-detail-matrix-row-${c.competence_id}-level`}
                              className="text-[11px] font-normal"
                            >
                              {c.skill_level_title}
                            </Badge>
                          ) : (
                            <span className="text-[11px] text-muted-foreground">
                              {t("noLevel")}
                            </span>
                          )}
                        </span>
                      </button>
                      {compOpen && c.indicators.length > 0 ? (
                        <ul className="space-y-1 px-3 pb-3 pl-12 text-sm">
                          {c.description ? (
                            <li className="text-xs text-muted-foreground">
                              {c.description}
                            </li>
                          ) : null}
                          {c.indicators.map((ind) => (
                            <li
                              key={ind.id}
                              data-testid={`position-detail-matrix-row-${c.competence_id}-indicator-${ind.id}`}
                              className="rounded border-l-2 border-primary/40 bg-muted/30 px-2 py-1"
                            >
                              {ind.title}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

interface DetailState {
  position: Position | null;
  matrix: PositionMatrix | null;
  employees: EmployeeListItem[];
}

const initialState: DetailState = {
  position: null,
  matrix: null,
  employees: [],
};

// HRP-57 §6.2: Headcount block shows ●●●○○ — filled = assigned, hollow = open.
// Capped at 12 dots so a 50-headcount position doesn't blow up the layout;
// numeric label carries the precise figures alongside.
function HeadcountDots({
  assigned,
  headcount,
}: {
  assigned: number;
  headcount: number;
}) {
  const t = useTranslations("company");
  const cap = 12;
  const total = Math.min(headcount, cap);
  const filled = Math.min(assigned, total);
  const truncated = headcount > cap;
  return (
    <span
      data-testid="position-detail-headcount-dots"
      aria-label={t("headcountDotsAria", { assigned, headcount })}
      className="inline-flex items-center gap-0.5 text-xs leading-none"
    >
      {Array.from({ length: total }).map((_, i) => (
        <span
          key={i}
          className={
            i < filled
              ? "text-primary"
              : "text-muted-foreground/50"
          }
        >
          ●
        </span>
      ))}
      {truncated ? (
        <span className="ml-1 text-muted-foreground">…</span>
      ) : null}
    </span>
  );
}

function formatSalaryRange(
  min: number | null,
  max: number | null,
  currency: string | null,
  t: (key: string, values?: Record<string, string | number>) => string,
  locale: string,
): string | null {
  if (min == null && max == null) return null;
  const fmt = (n: number) => n.toLocaleString(locale);
  // HRP-439: display fallback for a range saved before the currency was
  // recorded — the installation's own, never a hardcoded literal.
  const cur = currency ?? getDefaultSalaryCurrency();
  if (min != null && max != null) {
    return `${fmt(min)} – ${fmt(max)} ${cur}`;
  }
  if (min != null) return t("salaryFrom", { amount: fmt(min), currency: cur });
  return t("salaryUpTo", { amount: fmt(max!), currency: cur });
}

export default function PositionDetailPage() {
  const t = useTranslations("company");
  const tc = useTranslations("common");
  const locale = useLocale();
  const { id } = useParams<{ id: string }>();
  const { canManage } = usePermissions();
  const [state, setState] = useState<DetailState>(initialState);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);

  // HRP-32 inline edits: simple field-by-field state. Cascade-heavy fields
  // (Specialization → Grade, Division, Salary) still go through PositionEditDialog.
  // HRP-110: inline-edit fields share a tiny hook. Validation, save and
  // toasts still live on the page — see `savePatch` below.
  const titleEdit = useInlineEdit<string>(() => "");
  const headcountEdit = useInlineEdit<string>(() => "");
  const descEdit = useInlineEdit<string>(() => "");
  const [saving, setSaving] = useState(false);
  // HRP-93 Part 2: highlight competences with a live AI session and let the
  // user open the drawer on it.
  const [aiDrawerOpen, setAiDrawerOpen] = useState(false);
  const [aiDrawerSessionId, setAiDrawerSessionId] = useState<string | null>(
    null,
  );
  const { byTarget: activeSessionsMap } = useActiveAiSessions();
  function openAiDrawerForSession(sessionId: string) {
    setAiDrawerSessionId(sessionId);
    setAiDrawerOpen(true);
  }

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const [position, matrix, employees] = await Promise.all([
        api.get<Position>(`/positions/${id}`),
        api.get<PositionMatrix>(`/positions/${id}/competences`),
        api.get<EmployeeListItem[]>(
          `/positions/${id}/employees?with_alerts=true`,
        ),
      ]);
      setState({ position, matrix, employees });
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t("toastPositionLoadFailed"),
      );
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function savePatch(
    patch: Partial<{
      title: string;
      description: string | null;
      headcount: number | null;
    }>,
  ) {
    if (!state.position) return;
    setSaving(true);
    try {
      await api.put(`/positions/${state.position.id}`, patch);
      await load();
      toast.success(t("toastSaved"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastSaveFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function setStatus(next: PositionLifecycleStatus) {
    if (!state.position) return;
    setSaving(true);
    try {
      await api.post(`/positions/${state.position.id}/status`, {
        lifecycle_status: next,
      });
      await load();
      toast.success(
        t("toastStatusChanged", {
          status: t(POSITION_LIFECYCLE_LABEL_KEY[next]),
        }),
      );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("toastStatusUpdateFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div
        data-testid="position-detail-loading"
        className="py-10 text-center text-sm text-muted-foreground"
      >
        {tc("loading")}
      </div>
    );
  }

  if (error || !state.position) {
    return (
      <div className="space-y-4">
        <Button
          variant="ghost"
          size="sm"
          render={<Link href="/company/positions" />}
        >
          <ArrowLeft className="mr-1 h-4 w-4" />
          {t("back")}
        </Button>
        <p
          data-testid="position-detail-error"
          className="text-sm text-destructive"
        >
          {error ?? t("positionNotFound")}
        </p>
      </div>
    );
  }

  const { position, matrix, employees } = state;
  // HRP-54: when we send the operator to the specialization matrix from a
  // position page, tag the URL so the destination renders a "Back to
  // position" affordance instead of dropping the user into a deep section
  // with no return path.
  const matrixHref =
    position.specialization_id && position.grade_id
      ? `/company/specializations/${position.specialization_id}/matrix?grade_id=${position.grade_id}&from=position&position_id=${position.id}`
      : null;
  const specHref = position.specialization_id
    ? `/company/specializations/${position.specialization_id}?from=position&position_id=${position.id}`
    : null;

  const headcountLabel =
    position.headcount != null
      ? `${position.employee_count}/${position.headcount}`
      : `${position.employee_count}`;
  const competenceCount = matrix?.competences.length ?? 0;
  const matrixDescribed =
    position.specialization_title && position.grade_title
      ? `${position.specialization_title} / ${position.grade_title}`
      : t("thisProfile");
  const salaryLabel = formatSalaryRange(
    position.salary_min,
    position.salary_max,
    position.salary_currency,
    t,
    locale,
  );

  return (
    <div data-testid="position-detail" className="space-y-6">
      <div className="flex items-center gap-4">
        <Button
          variant="ghost"
          size="icon-sm"
          render={<Link href="/company/positions" />}
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          {titleEdit.editing ? (() => {
            const commitTitle = () => {
              const next = titleEdit.draft.trim();
              if (next && next !== position.title) {
                void savePatch({ title: next }).then(titleEdit.close);
              } else {
                titleEdit.close();
              }
            };
            return (
            <div className="flex items-center gap-2">
              <Input
                data-testid="position-detail-title-input"
                value={titleEdit.draft}
                maxLength={255}
                disabled={saving}
                onChange={(e) => titleEdit.setDraft(e.target.value)}
                onKeyDown={inlineEditKeys({
                  onCommit: commitTitle,
                  onCancel: titleEdit.cancel,
                  disabled: saving,
                })}
                className="text-2xl font-semibold tracking-tight"
              />
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={t("saveTitle")}
                data-testid="position-detail-title-save"
                disabled={saving || !titleEdit.draft.trim()}
                onClick={commitTitle}
              >
                <Check className="h-4 w-4" />
              </Button>
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={t("cancelTitleEdit")}
                data-testid="position-detail-title-cancel"
                disabled={saving}
                onClick={titleEdit.cancel}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
            );
          })() : (
            <h1
              data-testid="position-detail-title"
              className="group flex items-center gap-2 text-2xl font-semibold tracking-tight"
            >
              {position.title}
              {canManage && position.lifecycle_status !== "closed" ? (
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label={t("editTitle")}
                  data-testid="position-detail-title-edit"
                  className="opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                  onClick={() => titleEdit.start(position.title)}
                >
                  <Pencil className="h-4 w-4" />
                </Button>
              ) : null}
            </h1>
          )}
          <p className="text-sm text-muted-foreground">
            {[position.specialization_title, position.grade_title]
              .filter(Boolean)
              .join(" · ") || "—"}
          </p>
        </div>
        {canManage ? (
          <DropdownMenu>
            <DropdownMenuTrigger
              data-testid="position-detail-status-trigger"
              disabled={saving}
              render={
                <button
                  type="button"
                  aria-label={t("changeStatus")}
                  className="rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                >
                  <PositionStatusBadge
                    status={position.lifecycle_status}
                    testId="position-detail-status"
                    className="cursor-pointer"
                  />
                </button>
              }
            />
            <DropdownMenuContent align="end">
              {POSITION_LIFECYCLE_FLOW[position.lifecycle_status].map((next) => (
                <DropdownMenuItem
                  key={next}
                  data-testid={`position-detail-status-set-${next}`}
                  onClick={() => void setStatus(next)}
                >
                  {t("setStatusTo", {
                    status: t(POSITION_LIFECYCLE_LABEL_KEY[next]),
                  })}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <PositionStatusBadge
            status={position.lifecycle_status}
            testId="position-detail-status"
          />
        )}
        {canManage ? (
          <Button
            size="sm"
            variant="outline"
            data-testid="position-detail-btn-edit"
            onClick={() => setEditOpen(true)}
            disabled={position.lifecycle_status === "closed"}
            title={
              position.lifecycle_status === "closed"
                ? t("closedReadOnlyHint")
                : t("editFieldsHint")
            }
          >
            <Pencil className="mr-1 h-4 w-4" />
            {t("edit")}
          </Button>
        ) : null}
      </div>

      <PositionEditDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        position={position}
        onSaved={load}
      />

      <PositionAIGenerationCard position={position} onApplied={load} />

      {/* HRP-57 §6.6: matrix-state banner. Sits above Profile/Overview so the
          state is the first thing the operator sees on the page. */}
      {position.specialization_id && position.grade_id ? (
        position.matrix_configured ? (
          <div
            data-testid="position-detail-matrix-banner-ok"
            className="flex flex-wrap items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm dark:border-emerald-900 dark:bg-emerald-950"
          >
            <CheckCircle2 className="h-4 w-4 text-emerald-700 dark:text-emerald-300" />
            <span className="font-medium text-emerald-900 dark:text-emerald-200">
              {t("matrixConfigured")}
            </span>
            <span className="text-emerald-800 dark:text-emerald-300">
              {t("matrixCompetenceCountSuffix", { count: competenceCount })}
            </span>
            {salaryLabel ? (
              <span className="text-emerald-800 dark:text-emerald-300">
                · {salaryLabel}
              </span>
            ) : null}
          </div>
        ) : (
          <div
            data-testid="position-detail-matrix-banner-missing"
            className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm dark:border-amber-800 dark:bg-amber-950"
          >
            <p className="flex items-center gap-2 font-medium text-amber-900 dark:text-amber-200">
              <AlertTriangle className="h-4 w-4" />
              {t("matrixNotConfiguredFor", { profile: matrixDescribed })}
            </p>
            <p className="mt-1 text-xs text-amber-800 dark:text-amber-300">
              {t("matrixMissingHint")}
            </p>
            {matrixHref ? (
              <Link
                href={matrixHref}
                data-testid="position-detail-matrix-banner-configure"
                className="mt-2 inline-block text-sm font-medium text-amber-900 underline underline-offset-2 dark:text-amber-200"
              >
                {t("configureMatrixLink")}
              </Link>
            ) : null}
          </div>
        )
      ) : null}

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-4">
          <CardTitle className="text-base">{t("overview")}</CardTitle>
          {/* HRP-54: Edit button attached directly to the Overview card so
              the operator doesn't have to scan the page top for the global
              Edit button. Same dialog covers spec/grade/division/salary —
              the cascading fields that inline edits intentionally skip. */}
          {canManage && position.lifecycle_status !== "closed" ? (
            <Button
              size="sm"
              variant="outline"
              data-testid="position-detail-overview-btn-edit"
              onClick={() => setEditOpen(true)}
            >
              <Pencil className="mr-1 h-4 w-4" />
              {t("edit")}
            </Button>
          ) : null}
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-4 text-sm md:grid-cols-3">
            <div>
              <dt className="text-muted-foreground">{t("specialization")}</dt>
              <dd
                data-testid="position-detail-specialization"
                className="font-medium"
              >
                {position.specialization_id &&
                position.specialization_title &&
                specHref ? (
                  <Link
                    href={specHref}
                    className="text-primary hover:underline"
                    data-testid="position-detail-specialization-link"
                  >
                    {position.specialization_title}
                  </Link>
                ) : canManage ? (
                  <Button
                    variant="link"
                    size="sm"
                    className="h-auto p-0 text-sm"
                    data-testid="position-detail-overview-btn-set-specialization"
                    onClick={() => setEditOpen(true)}
                  >
                    <Plus className="mr-1 h-3 w-3" />
                    {t("setSpecialization")}
                  </Button>
                ) : (
                  (position.specialization_title ?? "—")
                )}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("grade")}</dt>
              <dd data-testid="position-detail-grade" className="font-medium">
                {position.specialization_id &&
                position.grade_id &&
                position.grade_title ? (
                  <Link
                    href={`/company/specializations/${position.specialization_id}/matrix?grade_id=${position.grade_id}&from=position&position_id=${position.id}`}
                    className="text-primary hover:underline"
                    data-testid="position-detail-grade-link"
                  >
                    {position.grade_title}
                  </Link>
                ) : canManage ? (
                  <Button
                    variant="link"
                    size="sm"
                    className="h-auto p-0 text-sm"
                    data-testid="position-detail-overview-btn-set-grade"
                    onClick={() => setEditOpen(true)}
                  >
                    <Plus className="mr-1 h-3 w-3" />
                    {t("setGrade")}
                  </Button>
                ) : (
                  (position.grade_title ?? "—")
                )}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("division")}</dt>
              <dd
                data-testid="position-detail-division"
                className="font-medium"
              >
                {position.division_name ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("headcount")}</dt>
              <dd
                data-testid="position-detail-headcount"
                className="font-medium"
              >
                {headcountEdit.editing ? (() => {
                  const commitHeadcount = () => {
                    const raw = headcountEdit.draft.trim();
                    const parsed = raw === "" ? null : Number(raw);
                    if (parsed != null && (Number.isNaN(parsed) || parsed < 0)) {
                      toast.error(t("errorHeadcountNegative"));
                      return;
                    }
                    void savePatch({ headcount: parsed }).then(headcountEdit.close);
                  };
                  return (
                  <span className="inline-flex items-center gap-1">
                    <Input
                      data-testid="position-detail-headcount-input"
                      type="number"
                      min={0}
                      value={headcountEdit.draft}
                      disabled={saving}
                      onChange={(e) => headcountEdit.setDraft(e.target.value)}
                      onKeyDown={inlineEditKeys({
                        onCommit: commitHeadcount,
                        onCancel: headcountEdit.cancel,
                        disabled: saving,
                      })}
                      className="h-8 w-24"
                    />
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label={t("saveHeadcount")}
                      data-testid="position-detail-headcount-save"
                      disabled={saving}
                      onClick={commitHeadcount}
                    >
                      <Check className="h-4 w-4" />
                    </Button>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label={t("cancelHeadcountEdit")}
                      data-testid="position-detail-headcount-cancel"
                      disabled={saving}
                      onClick={headcountEdit.cancel}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </span>
                  );
                })() : (
                  <span className="group inline-flex flex-wrap items-center gap-2">
                    <span>{headcountLabel}</span>
                    {position.headcount != null && position.headcount > 0 ? (
                      <HeadcountDots
                        assigned={position.employee_count}
                        headcount={position.headcount}
                      />
                    ) : null}
                    {position.vacancy_count != null &&
                    position.vacancy_count > 0 ? (
                      <span
                        data-testid="position-detail-vacancy-count"
                        className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-200"
                      >
                        <AlertTriangle className="h-3 w-3" />
                        {t("vacancyCount", { count: position.vacancy_count })}
                      </span>
                    ) : null}
                    {canManage && position.lifecycle_status !== "closed" ? (
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={t("editHeadcount")}
                        data-testid="position-detail-headcount-edit"
                        className="opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                        onClick={() =>
                          headcountEdit.start(
                            position.headcount != null
                              ? String(position.headcount)
                              : "",
                          )
                        }
                      >
                        <Pencil className="h-3 w-3" />
                      </Button>
                    ) : null}
                  </span>
                )}
              </dd>
            </div>
            {salaryLabel ? (
              <div>
                <dt className="text-muted-foreground">{t("salary")}</dt>
                <dd
                  data-testid="position-detail-salary"
                  className="font-medium"
                  title={t("salaryInheritedHint")}
                >
                  {salaryLabel}
                </dd>
              </div>
            ) : null}
            <div>
              <dt className="text-muted-foreground">{t("colSource")}</dt>
              <dd className="font-medium capitalize">
                {position.source.replace("_", " ")}
              </dd>
            </div>
          </dl>
          <div className="mt-4">
            <div className="flex items-center justify-between">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">
                {t("descriptionOverride")}
              </p>
              {!descEdit.editing &&
              canManage &&
              position.lifecycle_status !== "closed" ? (
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label={t("editDescription")}
                  data-testid="position-detail-description-edit"
                  onClick={() => descEdit.start(position.description ?? "")}
                >
                  <Pencil className="h-3 w-3" />
                </Button>
              ) : null}
            </div>
            {descEdit.editing ? (
              <div className="mt-1 space-y-2">
                <Textarea
                  data-testid="position-detail-description-input"
                  value={descEdit.draft}
                  disabled={saving}
                  onChange={(e) => descEdit.setDraft(e.target.value)}
                  rows={4}
                />
                <div className="flex justify-end gap-1">
                  <Button
                    size="sm"
                    variant="outline"
                    data-testid="position-detail-description-cancel"
                    disabled={saving}
                    onClick={descEdit.cancel}
                  >
                    {tc("cancel")}
                  </Button>
                  <Button
                    size="sm"
                    data-testid="position-detail-description-save"
                    disabled={saving}
                    onClick={() => {
                      const next = descEdit.draft.trim();
                      void savePatch({
                        description: next === "" ? null : next,
                      }).then(descEdit.close);
                    }}
                  >
                    {t("save")}
                  </Button>
                </div>
              </div>
            ) : position.description ? (
              <p
                data-testid="position-detail-description"
                className="mt-1 whitespace-pre-line text-sm"
              >
                {position.description}
              </p>
            ) : (
              <p
                data-testid="position-detail-description-empty"
                className="mt-1 text-sm italic text-muted-foreground"
              >
                {t("noDescriptionOverride")}
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle className="text-base">
              {t("competencesAndIndicators")}
            </CardTitle>
            <CardDescription>
              {t("competencesAndIndicatorsHint")}
            </CardDescription>
          </div>
          {matrixHref ? (
            <Button
              size="sm"
              variant="outline"
              data-testid="position-detail-btn-configure-matrix"
              render={<Link href={matrixHref} />}
            >
              <Settings2 className="mr-1 h-4 w-4" />
              {t("configureMatrix")}
              <ExternalLink className="ml-1 h-3 w-3" />
            </Button>
          ) : null}
        </CardHeader>
        <CardContent>
          {!matrix || !matrix.configured ? (
            <div
              data-testid="position-detail-matrix-empty"
              className="space-y-3 py-3 text-sm text-muted-foreground"
            >
              {/* HRP-54: three explicit states for the empty matrix — what
                  the operator should do depends entirely on whether spec,
                  grade, or matrix is the gap. Generic "configure matrix"
                  hides which knob to turn. */}
              {!position.specialization_id ? (
                <div
                  data-testid="position-detail-matrix-empty-no-spec"
                  className="space-y-2"
                >
                  <p>{t("matrixEmptyNoSpec")}</p>
                  {canManage ? (
                    <Button
                      size="sm"
                      data-testid="position-detail-matrix-empty-btn-pick-spec"
                      onClick={() => setEditOpen(true)}
                    >
                      <Plus className="mr-1 h-4 w-4" />
                      {t("pickSpecializationAndGrade")}
                    </Button>
                  ) : null}
                </div>
              ) : !position.grade_id ? (
                <div
                  data-testid="position-detail-matrix-empty-no-grade"
                  className="space-y-2"
                >
                  <p>{t("matrixEmptyNoGrade")}</p>
                  <div className="flex flex-wrap gap-2">
                    {canManage ? (
                      <Button
                        size="sm"
                        data-testid="position-detail-matrix-empty-btn-pick-grade"
                        onClick={() => setEditOpen(true)}
                      >
                        <Plus className="mr-1 h-4 w-4" />
                        {t("pickGrade")}
                      </Button>
                    ) : null}
                    {specHref ? (
                      <Button
                        size="sm"
                        variant="outline"
                        data-testid="position-detail-matrix-empty-spec-link"
                        render={<Link href={specHref} />}
                      >
                        {t("openSpecialization")}
                        <ExternalLink className="ml-1 h-3 w-3" />
                      </Button>
                    ) : null}
                  </div>
                </div>
              ) : (
                <div
                  data-testid="position-detail-matrix-empty-no-links"
                  className="space-y-2"
                >
                  <p>{t("matrixEmptyNoLinks")}</p>
                  {matrixHref ? (
                    <Button
                      size="sm"
                      data-testid="position-detail-matrix-empty-btn-configure"
                      render={<Link href={matrixHref} />}
                    >
                      <Settings2 className="mr-1 h-4 w-4" />
                      {t("configureMatrix")}
                      <ExternalLink className="ml-1 h-3 w-3" />
                    </Button>
                  ) : null}
                </div>
              )}
            </div>
          ) : (
            <MatrixTree
              competences={matrix.competences}
              activeSessionsMap={activeSessionsMap}
              onOpenActiveSession={openAiDrawerForSession}
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle className="text-base">{t("employees")}</CardTitle>
            <CardDescription>{t("employeesColumnsHint")}</CardDescription>
          </div>
          <span className="text-sm text-muted-foreground">
            {headcountLabel}
          </span>
        </CardHeader>
        <CardContent>
          {employees.length === 0 ? (
            <p
              data-testid="position-detail-employees-empty"
              className="py-3 text-sm text-muted-foreground"
            >
              {t("positionNoEmployees")}
            </p>
          ) : (
            /* HRP-175: use the unified EmployeeList wrapper so the position
               detail page renders the same 7-column layout as the
               drilldown modal and division detail. */
            <div
              data-testid="position-detail-employees"
              className="overflow-x-auto rounded-lg border"
            >
              <EmployeeList
                employees={employees as EmployeeListItem[]}
                testIdPrefix="position-detail-employees-row"
              />
            </div>
          )}
        </CardContent>
      </Card>

      {/* HRP-93 Part 2: read-only drawer for live AI sessions surfaced via
          the badge on any competence in the matrix above. */}
      <GenerationDrawer
        open={aiDrawerOpen}
        onOpenChange={(next) => {
          setAiDrawerOpen(next);
          if (!next) setAiDrawerSessionId(null);
        }}
        query={
          aiDrawerSessionId ? { sessionId: aiDrawerSessionId } : "active"
        }
      />
    </div>
  );
}
