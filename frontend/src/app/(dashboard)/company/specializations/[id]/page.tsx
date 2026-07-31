"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { UsageReferencesList } from "@/components/specialization/usage-references-list";
import {
  dictionariesApi,
  type DictionaryItemUsage,
} from "@/lib/api/dictionaries";
import { usePermissions } from "@/hooks/use-permissions";
import {
  specializationsApi,
  type DivisionPositionsBlock,
  type MatrixBulk,
  type SpecializationDetail,
  type SpecializationEmployee,
  type SpecializationGrade,
} from "@/lib/api/specializations";
import type {
  Competence,
  CompetenceGroupTree,
  SkillLevel,
} from "@/lib/types";
import { useCompetenceTree } from "@/hooks/use-competence-tree";
import { CompanyTabs } from "@/components/company/company-tabs";
import { AddGradesModal } from "@/components/specialization/add-grades-modal";
import { AiHistoryTab } from "@/components/specialization/ai-history-tab";
import { GradeAttributesForm } from "@/components/specialization/grade-attributes-form";
import { MatrixEditor } from "@/components/specialization/matrix-editor";
import { PositionsSummary } from "@/components/specialization/positions-summary";
import {
  EmployeeList,
  type EmployeeListItem,
} from "@/components/employees/EmployeeListRow";
import { ActiveAiSessionBadge } from "@/components/competence-generation/ActiveAiSessionBadge";
import { GenerationDrawer } from "@/components/competence-generation/GenerationDrawer";
import {
  activeAiSessionsKey,
  useActiveAiSessions,
} from "@/hooks/use-active-ai-sessions";

// HRP-57 §3.1 (E4): four logical surfaces on a Specialization. The deep-link
// query-param keeps direct URLs stable across reloads and shareable.
type Tab = "grades" | "positions" | "employees" | "ai-history";
const TABS: { key: Tab; labelKey: string }[] = [
  { key: "grades", labelKey: "specTabGradesMatrix" },
  { key: "positions", labelKey: "specTabPositions" },
  { key: "employees", labelKey: "specTabEmployees" },
  { key: "ai-history", labelKey: "specTabAiHistory" },
];
const TAB_KEYS: Tab[] = TABS.map((entry) => entry.key);

function isTab(value: string | null | undefined): value is Tab {
  return !!value && (TAB_KEYS as string[]).includes(value);
}

function flattenCompetences(tree: CompetenceGroupTree[]): Competence[] {
  const out: Competence[] = [];
  function walk(node: CompetenceGroupTree) {
    for (const comp of node.competences) {
      if (comp.is_active) out.push(comp);
    }
    for (const child of node.children) walk(child);
  }
  for (const root of tree) walk(root);
  return out;
}

export default function SpecializationDetailPage() {
  const t = useTranslations("company");
  const tc = useTranslations("common");
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const id = params?.id;

  const [detail, setDetail] = useState<SpecializationDetail | null>(null);
  const [positions, setPositions] = useState<DivisionPositionsBlock[]>([]);
  const [employees, setEmployees] = useState<SpecializationEmployee[] | null>(
    null,
  );
  const [employeesLoading, setEmployeesLoading] = useState(false);
  // HRP-67: Specialization Builder bundles the competence matrix into the
  // Grades tab. The bulk + skill levels load lazily so other tabs don't pay
  // for them.
  const [matrixBulk, setMatrixBulk] = useState<MatrixBulk | null>(null);
  const [skillLevels, setSkillLevels] = useState<SkillLevel[]>([]);
  const [matrixLoading, setMatrixLoading] = useState(false);
  const [addGradesOpen, setAddGradesOpen] = useState(false);
  // HRP-93 Part 2: surface in-flight AI generations on this specialization
  // (own + other tenant admins') so users see what's running before they
  // start their own. Click on the badge opens the drawer read-only.
  const [aiDrawerOpen, setAiDrawerOpen] = useState(false);
  const [aiDrawerSessionId, setAiDrawerSessionId] = useState<string | null>(
    null,
  );
  const { byTarget: activeSessionsMap } = useActiveAiSessions();
  const specLevelSessions = id
    ? (activeSessionsMap.get(
        activeAiSessionsKey("specialization_matrix", id),
      ) ?? [])
    : [];
  function openAiDrawerForSession(sessionId: string) {
    setAiDrawerSessionId(sessionId);
    setAiDrawerOpen(true);
  }
  const { tree } = useCompetenceTree();
  const competencesPool = useMemo(() => flattenCompetences(tree), [tree]);
  const highlightedGradeId = searchParams?.get("grade_id") ?? null;
  // HRP-54: when the operator arrived here from a position, swap the
  // "All specializations" breadcrumb for a direct return link to that
  // position — losing the back navigation was a reported regression.
  const fromPositionId =
    searchParams?.get("from") === "position"
      ? searchParams?.get("position_id") ?? null
      : null;
  const [loading, setLoading] = useState(true);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  // HRP-103 redo: prefetch references when the confirm opens so the
  // operator sees the exact positions / grade chains to detach.
  const [deleteUsage, setDeleteUsage] = useState<DictionaryItemUsage | null>(
    null,
  );
  const { canManage } = usePermissions();

  const queryTab = searchParams?.get("tab");
  const tab: Tab = isTab(queryTab) ? queryTab : "grades";

  const setTab = useCallback(
    (next: Tab) => {
      const sp = new URLSearchParams(searchParams?.toString() ?? "");
      if (next === "grades") sp.delete("tab");
      else sp.set("tab", next);
      const qs = sp.toString();
      router.replace(qs ? `?${qs}` : "?", { scroll: false });
    },
    [router, searchParams],
  );

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        const [d, p] = await Promise.all([
          specializationsApi.get(id),
          specializationsApi.positions(id),
        ]);
        if (!cancelled) {
          setDetail(d);
          setPositions(p);
        }
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : t("toastSpecLoadFailed"),
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, t]);

  // HRP-67: matrix bulk + skill levels for the Builder; loaded the first
  // time the Grades tab is shown so the network cost lands only when
  // somebody actually opens the Builder.
  useEffect(() => {
    if (!id || tab !== "grades" || matrixBulk !== null) return;
    let cancelled = false;
    setMatrixLoading(true);
    (async () => {
      try {
        const [b, levels] = await Promise.all([
          specializationsApi.matrixBulk(id),
          api.get<SkillLevel[]>("/skill-levels"),
        ]);
        if (!cancelled) {
          setMatrixBulk(b);
          setSkillLevels(levels);
        }
      } catch (err) {
        if (!cancelled) {
          toast.error(
            err instanceof Error ? err.message : t("toastCompetenceMatrixLoadFailed"),
          );
        }
      } finally {
        if (!cancelled) setMatrixLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, tab, matrixBulk, t]);

  // Lazy-load Employees only when the tab is opened. Caches in component
  // state so flipping tabs doesn't refetch unless the page is reloaded.
  useEffect(() => {
    if (!id || tab !== "employees" || employees !== null) return;
    let cancelled = false;
    setEmployeesLoading(true);
    (async () => {
      try {
        const data = await specializationsApi.employees(id, true);
        if (!cancelled) setEmployees(data);
      } catch (err) {
        if (!cancelled) {
          toast.error(
            err instanceof Error ? err.message : t("toastSpecEmployeesFailed"),
          );
        }
      } finally {
        if (!cancelled) setEmployeesLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, tab, employees, t]);

  // HRP-103 redo: load usage every time the delete confirm opens so the
  // operator sees up-to-date references (positions / grade chains).
  useEffect(() => {
    if (!deleteOpen || !id) {
      setDeleteUsage(null);
      return;
    }
    let cancelled = false;
    setDeleteUsage(null);
    (async () => {
      try {
        const usage = await dictionariesApi.usage(id);
        if (!cancelled) setDeleteUsage(usage);
      } catch {
        // A failed preview shouldn't block delete attempts — the 409
        // path still surfaces a usable toast on the actual DELETE.
        if (!cancelled)
          setDeleteUsage({
            positions: [],
            chains: [],
            assessments_count: 0,
            assessment_groups_count: 0,
            pdps_count: 0,
            exam_pass_marks_count: 0,
            competences_count: 0,
          });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [deleteOpen, id]);

  const deleteHasReferences =
    deleteUsage !== null &&
    (deleteUsage.positions.length > 0 ||
      deleteUsage.chains.length > 0 ||
      deleteUsage.assessments_count > 0 ||
      deleteUsage.assessment_groups_count > 0 ||
      deleteUsage.pdps_count > 0 ||
      deleteUsage.exam_pass_marks_count > 0);

  async function handleDelete() {
    if (!id || !detail) return;
    setDeleteBusy(true);
    try {
      await api.delete(`/dictionaries/items/${id}`);
      toast.success(t("toastSpecDeleted", { title: detail.title }));
      router.replace("/company/specializations");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastDeleteFailed"));
      setDeleteBusy(false);
    }
  }

  function handleGradeSaved(next: SpecializationGrade) {
    if (!detail) return;
    setDetail({
      ...detail,
      grades: detail.grades.map((g) => (g.id === next.id ? next : g)),
    });
  }

  // Keeps `detail.grades`, the matrix header order and any open matrix
  // editing state in sync after Add Grades / drag-reorder / inline salary
  // edit / remove. We rebuild the matrix-bulk view by stitching new pairs
  // into the existing bulk so users editing competence levels don't lose
  // their unsaved cells when a grade is added or reordered.
  function applyGradesChange(next: SpecializationGrade[]) {
    if (!detail) return;
    setDetail({
      ...detail,
      grades: next,
      grade_count: next.length,
    });
    setMatrixBulk((prev) => {
      if (prev === null) return prev;
      const byId = new Map(prev.grades.map((b) => [b.grade_id, b]));
      const merged = next
        .slice()
        .sort((a, b) => a.sort_index - b.sort_index)
        .map((g) => {
          const existing = byId.get(g.grade_id);
          return (
            existing ?? {
              grade_id: g.grade_id,
              grade_title: g.grade_title,
              grade_sort_index: g.sort_index,
              links: [],
            }
          );
        });
      return { grades: merged };
    });
  }

  const employeeRows = useMemo<EmployeeListItem[]>(() => {
    if (!employees) return [];
    return employees.map((e) => ({
      id: e.id,
      user_name: e.user_name,
      user_email: e.user_email,
      position_title: e.position_title,
      specialization_title: e.specialization_title,
      grade_title: e.grade_title,
      // HRP-175: pass division_id so the Division cell becomes a link
      // back to `/company/divisions/{id}`.
      division_id: e.division_id,
      division_name: e.division_name,
      hire_date: e.hire_date,
      status: e.status,
      avatar_url: e.avatar_url,
      alert: e.alert,
    }));
  }, [employees]);

  if (loading) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground">
        {tc("loading")}
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground">
        {t("specializationNotFound")}
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="specialization-detail">
      <div className="flex items-center justify-between">
        <div>
          {fromPositionId ? (
            <Link
              href={`/company/positions/${fromPositionId}`}
              data-testid="specialization-detail-back-to-position"
              className="text-xs text-muted-foreground hover:underline"
            >
              {t("backToPosition")}
            </Link>
          ) : (
            <Link
              href="/company/specializations"
              className="text-xs text-muted-foreground hover:underline"
            >
              {t("allSpecializations")}
            </Link>
          )}
          <div className="flex items-center gap-2">
            <h1
              data-testid="specialization-detail-title"
              className="text-2xl font-semibold tracking-tight"
            >
              {detail.title}
            </h1>
            {specLevelSessions.length > 0 && (
              <ActiveAiSessionBadge
                sessions={specLevelSessions}
                onOpen={openAiDrawerForSession}
                testIdSuffix={`spec-${id}`}
              />
            )}
          </div>
          <p className="text-sm text-muted-foreground">
            {t("specSummary", {
              grades: detail.grade_count,
              positions: detail.position_count,
              assigned: detail.assigned_count,
              headcount: detail.headcount_total,
            })}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            data-testid="specialization-add-grades-btn"
            onClick={() => setAddGradesOpen(true)}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm font-medium hover:bg-accent"
          >
            {t("addGrades")}
          </button>
          <Link
            href={`/company/specializations/${id}/ai-generate`}
            data-testid="specialization-ai-generate-link"
            className="rounded-md border border-input bg-background px-3 py-2 text-sm font-medium hover:bg-accent"
          >
            {t("aiGenerateMatrix")}
          </Link>
          {canManage && (
            <button
              type="button"
              data-testid="specialization-detail-delete-btn"
              onClick={() => setDeleteOpen(true)}
              className="inline-flex items-center gap-1 rounded-md border border-destructive/40 bg-background px-3 py-2 text-sm font-medium text-destructive hover:bg-destructive/10"
            >
              <Trash2 className="h-4 w-4" />
              {tc("delete")}
            </button>
          )}
        </div>
      </div>

      <CompanyTabs />

      <div
        role="tablist"
        aria-label={t("specSectionsAria")}
        className="flex gap-1 border-b"
      >
        {TABS.map((entry) => {
          const active = tab === entry.key;
          return (
            <button
              key={entry.key}
              type="button"
              role="tab"
              aria-selected={active}
              data-testid={`specialization-tab-${entry.key}`}
              className={
                active
                  ? "border-b-2 border-primary px-4 py-2 text-sm font-medium text-primary"
                  : "border-b-2 border-transparent px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground"
              }
              onClick={() => setTab(entry.key)}
            >
              {t(entry.labelKey)}
            </button>
          );
        })}
      </div>

      {tab === "grades" ? (
        detail.grades.length === 0 ? (
          <div
            data-testid="specialization-grades-empty"
            className="space-y-3 rounded-lg border bg-muted/30 py-12 text-center"
          >
            <p className="text-sm text-muted-foreground">
              {t("specNoGrades")}
            </p>
            <p className="text-xs text-muted-foreground">
              {t("specNoGradesHint")}
            </p>
            <div className="flex justify-center gap-2 pt-1">
              <button
                type="button"
                data-testid="specialization-add-grades-empty-btn"
                onClick={() => setAddGradesOpen(true)}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                {t("addGrades")}
              </button>
              <Link
                href={`/company/specializations/${id}/ai-generate`}
                className="rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent"
              >
                {t("aiGenerateMatrix")}
              </Link>
            </div>
          </div>
        ) : (
          <div className="space-y-8" data-testid="specialization-builder">
            {/* HRP-57 §4.1 / §4.2 (E1 phase 1): the Builder collapses the old
                Grades-list + separate matrix-page detour into a single
                surface — competence matrix on top, per-grade attributes
                (description / requirements / salary) below. Drag-drop
                reorder, inline-add competence popovers and cascade preview
                land in phase 2 of HRP-67. */}
            <section className="space-y-3">
              <h2
                data-testid="specialization-builder-matrix-heading"
                className="text-base font-semibold tracking-tight"
              >
                {t("competenceMatrix")}
              </h2>
              <p className="text-xs text-muted-foreground">
                {t("matrixPageHint")}
              </p>
              {matrixLoading && matrixBulk === null ? (
                <p
                  data-testid="specialization-builder-matrix-loading"
                  className="py-8 text-center text-sm text-muted-foreground"
                >
                  {t("loadingMatrix")}
                </p>
              ) : matrixBulk === null ? null : matrixBulk.grades.length === 0 ? (
                <p
                  data-testid="specialization-builder-matrix-empty"
                  className="rounded-lg border bg-muted/30 py-12 text-center text-sm text-muted-foreground"
                >
                  {t("matrixNoGrades")}
                </p>
              ) : (
                <MatrixEditor
                  specId={id!}
                  bulk={matrixBulk}
                  skillLevels={skillLevels}
                  competencesPool={competencesPool}
                  competenceTree={tree}
                  highlightedGradeId={highlightedGradeId}
                  gradeMeta={detail.grades}
                  onSaved={(next) => setMatrixBulk(next)}
                  onGradesChanged={applyGradesChange}
                  activeSessionsMap={activeSessionsMap}
                  onOpenActiveSession={openAiDrawerForSession}
                />
              )}
            </section>

            <section className="space-y-3">
              <h2
                data-testid="specialization-builder-attrs-heading"
                className="text-base font-semibold tracking-tight"
              >
                {t("gradeAttributes")}
              </h2>
              <p className="text-xs text-muted-foreground">
                {t("gradeAttributesHint")}
              </p>
              <div className="space-y-4">
                {detail.grades.map((g) => (
                  <GradeAttributesForm
                    key={g.id}
                    grade={g}
                    specId={id}
                    onSaved={handleGradeSaved}
                  />
                ))}
              </div>
            </section>
          </div>
        )
      ) : null}

      {tab === "positions" ? <PositionsSummary blocks={positions} /> : null}

      {tab === "employees" ? (
        employeesLoading && employees === null ? (
          <p
            data-testid="specialization-employees-loading"
            className="py-8 text-center text-sm text-muted-foreground"
          >
            {t("loadingEmployees")}
          </p>
        ) : employeeRows.length === 0 ? (
          <p
            data-testid="specialization-employees-empty"
            className="py-8 text-center text-sm text-muted-foreground"
          >
            {t("specNoEmployees")}
          </p>
        ) : (
          /* HRP-175: shared EmployeeList wrapper enforces the 7-column
             layout across positions / divisions / specializations. */
          <div
            data-testid="specialization-employees"
            className="overflow-x-auto rounded-lg border"
          >
            <EmployeeList
              employees={employeeRows as EmployeeListItem[]}
              testIdPrefix="specialization-employees-row"
            />
          </div>
        )
      ) : null}

      {tab === "ai-history" && id ? <AiHistoryTab specializationId={id} /> : null}

      {id ? (
        <AddGradesModal
          open={addGradesOpen}
          specId={id}
          alreadyAdded={detail.grades}
          onClose={() => setAddGradesOpen(false)}
          onAdded={(grades) => applyGradesChange(grades)}
        />
      ) : null}

      {/* HRP-93 Part 2: read-only drawer for live AI sessions surfaced via
          the badge — matrix-row competence indicators, spec-level matrix
          generation by another admin, etc. */}
      <GenerationDrawer
        open={aiDrawerOpen}
        onOpenChange={(next) => {
          setAiDrawerOpen(next);
          if (!next) setAiDrawerSessionId(null);
        }}
        query={
          aiDrawerSessionId
            ? { sessionId: aiDrawerSessionId }
            : "active"
        }
      />

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={(open) => {
          if (!open && !deleteBusy) setDeleteOpen(false);
        }}
        title={t("deleteSpecialization")}
        description={
          detail
            ? deleteHasReferences
              ? t("deleteSpecReferenced", { title: detail.title })
              : t("deleteSpecConfirm", { title: detail.title })
            : ""
        }
        onConfirm={handleDelete}
        loading={deleteBusy}
        confirmDisabled={deleteHasReferences}
      >
        <UsageReferencesList usage={deleteUsage} />
      </ConfirmDialog>
    </div>
  );
}
