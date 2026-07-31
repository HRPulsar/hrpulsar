"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  CircleSlash,
  GripVertical,
  Loader2,
  Lock,
  Pencil,
  Plus,
  Sparkles,
  Target,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { api, ApiError } from "@/lib/api";
import { invalidateCompetenceTree } from "@/hooks/use-competence-tree";
import type {
  CompetenceDetail,
  CompetenceGroup,
  CompetenceUsage,
  Indicator,
  Material,
  SkillLevel,
} from "@/lib/types";
import { IndicatorWeight } from "@/components/competence/indicator-weight";
import { MaterialOverridesPanel } from "@/components/competence/material-overrides-panel";
import { MaterialsAIDialog } from "@/components/competence/materials-ai-dialog";
import { levelTokens, type LevelTokens } from "@/lib/competences/level-tokens";
import { skillLevelLabel } from "@/lib/reference-labels";
import { cn } from "@/lib/utils";
import {
  DEFAULT_MATERIAL_TYPE,
  MATERIAL_FORMATS,
  MATERIAL_TYPES,
  materialFormatLabel,
  materialTypeOption,
} from "@/lib/competences/material-options";
import {
  CompetenceUsageBanner,
  CompetenceUsageWarningDialog,
} from "@/components/competence/usage-warning";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/confirm-dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
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
import { GenerationConfirmDialog } from "@/components/competence-generation/GenerationConfirmDialog";
import { GenerationDrawer } from "@/components/competence-generation/GenerationDrawer";
import { PreflightModal } from "@/components/competence-generation/PreflightModal";
import {
  type OtherActiveSession,
  competenceGenerationApi,
} from "@/lib/api/competence-generation";
import { useGenerationSession } from "@/hooks/use-generation-session";

interface IndicatorForm {
  title: string;
  weight: number;
  skill_level_id: string;
}

interface MaterialForm {
  title: string;
  format: string;
  link: string;
  study_time: string;
  comment: string;
  material_type: string;
  skill_level_id: string;
}

const emptyIndicatorForm: IndicatorForm = {
  title: "",
  weight: 1,
  skill_level_id: "",
};

const emptyMaterialForm: MaterialForm = {
  title: "",
  format: "",
  link: "",
  study_time: "",
  comment: "",
  material_type: DEFAULT_MATERIAL_TYPE,
  skill_level_id: "",
};

export default function CompetenceDetailPage() {
  const t = useTranslations("competences");
  const tc = useTranslations("common");
  const tRef = useTranslations("reference");
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [detail, setDetail] = useState<CompetenceDetail | null>(null);
  const [group, setGroup] = useState<CompetenceGroup | null>(null);
  const [skillLevels, setSkillLevels] = useState<SkillLevel[]>([]);
  const [usage, setUsage] = useState<CompetenceUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // HRP-102: confirm overlay shown before an indicator change is persisted on
  // a competence that is referenced elsewhere (matrices, assessments, IDPs).
  const [usageConfirm, setUsageConfirm] = useState<
    | { kind: "save"; run: () => Promise<void> }
    | { kind: "delete"; run: () => Promise<void> }
    | null
  >(null);

  // HRP-102 follow-up: the AI Apply path now goes through the same
  // blocking confirm as manual save/delete when the competence is in use.
  // ApplyDialog calls our guard before invoking onApply; we hold the
  // resolver here and let the user click Confirm/Cancel in the dialog to
  // unblock it.
  const aiApplyResolverRef = useRef<((proceed: boolean) => void) | null>(null);
  const [aiApplyConfirmOpen, setAiApplyConfirmOpen] = useState(false);

  // Indicator dialog
  const [indDialogOpen, setIndDialogOpen] = useState(false);
  const [indForm, setIndForm] = useState<IndicatorForm>(emptyIndicatorForm);
  const [editingInd, setEditingInd] = useState<Indicator | null>(null);

  // Material dialog
  const [matDialogOpen, setMatDialogOpen] = useState(false);
  const [matForm, setMatForm] = useState<MaterialForm>(emptyMaterialForm);
  const [editingMat, setEditingMat] = useState<Material | null>(null);

  // Delete confirmations
  const [deleting, setDeleting] = useState<
    | { kind: "indicator"; id: string; title: string }
    | { kind: "material"; id: string; title: string }
    | null
  >(null);

  // AI indicator generation. HRP-122 REDO #3: the AI button used to hold
  // its own activeSession useState updated only by a WS handler, which
  // missed every dropped compgen.session.updated push. Route through
  // useGenerationSession so the 5s REST polling keeps it in sync.
  const {
    session: activeSession,
    loading: activeSessionLoading,
    refresh: refreshActiveSession,
  } = useGenerationSession("active");
  const [aiConfirmOpen, setAiConfirmOpen] = useState(false);
  const [aiPreflightOpen, setAiPreflightOpen] = useState(false);
  const [aiOthers, setAiOthers] = useState<OtherActiveSession[]>([]);
  const [aiDrawerOpen, setAiDrawerOpen] = useState(false);
  const [aiStarting, setAiStarting] = useState(false);

  // HRP-51: AI material generation (separate from indicators flow).
  const [materialsAiOpen, setMaterialsAiOpen] = useState(false);

  const refresh = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const [d, levels, use] = await Promise.all([
        api.get<CompetenceDetail>(`/competences/${id}`),
        api.get<SkillLevel[]>("/skill-levels"),
        api
          .get<CompetenceUsage>(`/competences/${id}/usage`)
          .catch(() => null),
      ]);
      setDetail(d);
      setSkillLevels(levels);
      setUsage(use);
      // Resolve the group lazily — there's no /competence-groups/{id} endpoint,
      // so reuse the tree (cheap and already cached by the shared hook).
      try {
        const tree = await api.get<{ id: string; title: string; competences: { id: string }[]; children: unknown[] }[]>("/competence-tree");
        const findGroup = (
          nodes: { id: string; title: string; competences: { id: string }[]; children: unknown[] }[],
        ): { id: string; title: string } | null => {
          for (const n of nodes) {
            if (n.competences.some((c) => c.id === d.group_id)) return n;
            const inner = findGroup(
              n.children as { id: string; title: string; competences: { id: string }[]; children: unknown[] }[],
            );
            if (inner) return inner;
          }
          return null;
        };
        const found = findGroup(tree);
        setGroup(found ? ({ id: found.id, title: found.title } as CompetenceGroup) : null);
      } catch {
        // best-effort
      }
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("errorLoadCompetence"),
      );
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // HRP-122 REDO #3: WS subscription used to live here too. Snapshot is
  // now driven by useGenerationSession (polling + WS in one hook).

  // Re-open the drawer if returning here with ?compgen=open (e.g. from a notification).
  useEffect(() => {
    if (
      searchParams.get("compgen") === "open" &&
      activeSession &&
      activeSession.target_id === id
    ) {
      setAiDrawerOpen(true);
      router.replace(`/competences/${id}`);
    }
  }, [searchParams, activeSession, id, router]);

  const isOrigin = detail?.is_origin ?? false;
  const canEditMeta = !isOrigin;

  // HRP-102: the matrix cell link puts `?from=matrix&specialization_id=…`
  // on the URL. We thread that spec id into (a) the breadcrumb (Back to
  // matrix) and (b) the AI session params (so the LLM sees the career
  // ladder). Both readers used to duplicate the inline ternary — memoised
  // once here keeps them in sync if the contract ever changes.
  const fromMatrixSpecId = useMemo(
    () =>
      searchParams.get("from") === "matrix"
        ? searchParams.get("specialization_id")
        : null,
    [searchParams],
  );

  // AI indicator generation — derived UI state.
  // HRP-47: any active session (even for a different scope/competence) should
  // surface as a clickable button that opens the drawer. The button label
  // mirrors GenerationStatusButton on the list page so the UX is consistent.
  const aiActiveAny =
    !!activeSession &&
    activeSession.status !== "applied" &&
    activeSession.status !== "cancelled";
  const aiIsForThisCompetence =
    aiActiveAny &&
    activeSession?.scope === "competence_indicators" &&
    activeSession?.target_id === id;
  const aiBusyElsewhere = aiActiveAny && !aiIsForThisCompetence;
  const aiStatus = aiActiveAny ? activeSession?.status ?? null : null;
  const aiRunning = aiStatus === "pending" || aiStatus === "running";
  const aiReady = aiStatus === "ready";

  async function handleAiButtonClick() {
    if (aiActiveAny) {
      setAiDrawerOpen(true);
      return;
    }
    try {
      const others = await competenceGenerationApi.getActiveOthers();
      if (others.length > 0) {
        setAiOthers(others);
        setAiPreflightOpen(true);
        return;
      }
    } catch {
      // best-effort, fall through to confirm
    }
    setAiConfirmOpen(true);
  }

  async function startIndicatorGeneration(params: { with_indicators: boolean }) {
    if (!detail) return;
    setAiStarting(true);
    try {
      await competenceGenerationApi.create({
        scope: "competence_indicators",
        target_id: detail.id,
        params: fromMatrixSpecId
          ? { ...params, specialization_id: fromMatrixSpecId }
          : params,
      });
      // HRP-122 REDO #3: kick a refetch so the AI button flips to the
      // "running" label without waiting for the next polling tick.
      void refreshActiveSession();
      setAiDrawerOpen(true);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("errorStartAiGeneration"),
      );
    } finally {
      setAiStarting(false);
    }
  }

  const indicatorsByLevel = useMemo(() => {
    const map = new Map<string, Indicator[]>();
    for (const lv of skillLevels) map.set(lv.id, []);
    if (!detail) return map;
    for (const ind of detail.indicators) {
      const bucket = map.get(ind.skill_level_id) ?? [];
      bucket.push(ind);
      map.set(ind.skill_level_id, bucket);
    }
    for (const arr of map.values()) {
      arr.sort((a, b) => a.sort_index - b.sort_index);
    }
    return map;
  }, [detail, skillLevels]);

  const materialsByLevel = useMemo(() => {
    const map = new Map<string, Material[]>();
    for (const lv of skillLevels) map.set(lv.id, []);
    if (!detail) return map;
    for (const mat of detail.materials) {
      const bucket = map.get(mat.skill_level_id) ?? [];
      bucket.push(mat);
      map.set(mat.skill_level_id, bucket);
    }
    for (const arr of map.values()) {
      arr.sort((a, b) => a.sort_index - b.sort_index);
    }
    return map;
  }, [detail, skillLevels]);

  const orderedLevels = useMemo(
    () => [...skillLevels].sort((a, b) => a.sort_index - b.sort_index),
    [skillLevels],
  );

  // Display-only lookups for the dialog Select triggers — the forms keep
  // storing `skill_level_id`, so the localized label never reaches a payload.
  const selectedIndLevel = orderedLevels.find(
    (lv) => lv.id === indForm.skill_level_id,
  );
  const selectedMatLevel = orderedLevels.find(
    (lv) => lv.id === matForm.skill_level_id,
  );

  // --- Publish / activate ---

  async function publish() {
    if (!detail) return;
    setSaving(true);
    try {
      await api.post(`/competences/${detail.id}/publish`);
      toast.success(t("toastCompetencePublished"));
      await Promise.all([refresh(), invalidateCompetenceTree()]);
    } catch (err) {
      toast.error(formatUsageError(err, t("errorCannotPublish")));
    } finally {
      setSaving(false);
    }
  }

  async function unpublish() {
    if (!detail) return;
    setSaving(true);
    try {
      await api.post(`/competences/${detail.id}/unpublish`);
      toast.success(t("toastCompetenceUnpublished"));
      await Promise.all([refresh(), invalidateCompetenceTree()]);
    } catch (err) {
      toast.error(formatUsageError(err, t("errorCannotUnpublish")));
    } finally {
      setSaving(false);
    }
  }

  async function toggleActive() {
    if (!detail) return;
    setSaving(true);
    try {
      const path = detail.is_active ? "deactivate" : "activate";
      await api.patch(`/competences/${detail.id}/${path}`);
      toast.success(
        detail.is_active
          ? t("toastHiddenFromUsers")
          : t("toastVisibleToUsers"),
      );
      await Promise.all([refresh(), invalidateCompetenceTree()]);
    } catch (err) {
      toast.error(formatUsageError(err, t("errorUpdateVisibility")));
    } finally {
      setSaving(false);
    }
  }

  // --- Indicator CRUD ---

  function openCreateIndicator(skillLevelId: string) {
    setEditingInd(null);
    setIndForm({ ...emptyIndicatorForm, skill_level_id: skillLevelId });
    setIndDialogOpen(true);
  }
  function openEditIndicator(ind: Indicator) {
    setEditingInd(ind);
    setIndForm({
      title: ind.title,
      weight: ind.weight,
      skill_level_id: ind.skill_level_id,
    });
    setIndDialogOpen(true);
  }
  async function persistIndicator() {
    if (!detail) return;
    setSaving(true);
    try {
      if (editingInd) {
        await api.put(`/indicators/${editingInd.id}`, {
          title: indForm.title,
          weight: indForm.weight,
          skill_level_id: indForm.skill_level_id,
        });
      } else {
        await api.post(`/competences/${detail.id}/indicators`, {
          title: indForm.title,
          weight: indForm.weight,
          skill_level_id: indForm.skill_level_id,
        });
      }
      toast.success(
        editingInd ? t("toastIndicatorUpdated") : t("toastIndicatorAdded"),
      );
      setIndDialogOpen(false);
      setUsageConfirm(null);
      await refresh();
      await invalidateCompetenceTree();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("errorSaveIndicator"),
      );
    } finally {
      setSaving(false);
    }
  }

  /**
   * Inline weight edit from the indicator row. Bypasses the full edit
   * dialog — the field is small, conflict-free, and HR users tune it in
   * bulk; the usage warning still fires through the same guard as the
   * dialog save path.
   */
  async function updateIndicatorWeight(ind: Indicator, nextWeight: number) {
    if (!detail) return;
    if (nextWeight === ind.weight) return;
    const run = async () => {
      try {
        await api.put(`/indicators/${ind.id}`, {
          title: ind.title,
          weight: nextWeight,
          skill_level_id: ind.skill_level_id,
        });
        setUsageConfirm(null);
        await refresh();
        await invalidateCompetenceTree();
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : t("errorSaveWeight"),
        );
      }
    };
    if (usage?.is_used) {
      setUsageConfirm({ kind: "save", run });
      return;
    }
    await run();
  }

  async function saveIndicator() {
    if (!detail) return;
    if (!indForm.title.trim()) {
      toast.error(t("errorTitleRequired"));
      return;
    }
    // HRP-102: edits to a referenced competence ripple into every consumer —
    // matrices, employee cards, assessments. Surface the warning before the
    // mutation lands.
    if (usage?.is_used) {
      setUsageConfirm({ kind: "save", run: persistIndicator });
      return;
    }
    await persistIndicator();
  }

  // --- Material CRUD ---

  function openCreateMaterial(skillLevelId: string) {
    setEditingMat(null);
    setMatForm({ ...emptyMaterialForm, skill_level_id: skillLevelId });
    setMatDialogOpen(true);
  }
  function openEditMaterial(mat: Material) {
    setEditingMat(mat);
    setMatForm({
      title: mat.title,
      format: mat.format ?? "",
      link: mat.link ?? "",
      study_time: mat.study_time != null ? String(mat.study_time) : "",
      comment: mat.comment ?? "",
      material_type: mat.material_type ?? "",
      skill_level_id: mat.skill_level_id,
    });
    setMatDialogOpen(true);
  }
  async function saveMaterial() {
    if (!detail) return;
    if (!matForm.title.trim()) {
      toast.error(t("errorTitleRequired"));
      return;
    }
    if (!matForm.material_type) {
      toast.error(t("errorTypeRequired"));
      return;
    }
    setSaving(true);
    try {
      const payload = {
        title: matForm.title,
        format: matForm.format || null,
        link: matForm.link || null,
        study_time: matForm.study_time ? Number(matForm.study_time) : null,
        comment: matForm.comment || null,
        material_type: matForm.material_type || null,
        skill_level_id: matForm.skill_level_id,
      };
      if (editingMat) {
        await api.put(`/materials/${editingMat.id}`, payload);
      } else {
        await api.post(`/competences/${detail.id}/materials`, payload);
      }
      toast.success(
        editingMat ? t("toastMaterialUpdated") : t("toastMaterialAdded"),
      );
      setMatDialogOpen(false);
      await refresh();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("errorSaveMaterial"),
      );
    } finally {
      setSaving(false);
    }
  }

  // --- Delete ---

  async function persistDelete() {
    if (!deleting) return;
    setSaving(true);
    try {
      const path = deleting.kind === "indicator" ? "indicators" : "materials";
      await api.delete(`/${path}/${deleting.id}`);
      toast.success(t("toastDeleted"));
      setDeleting(null);
      setUsageConfirm(null);
      await refresh();
      await invalidateCompetenceTree();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorDelete"));
    } finally {
      setSaving(false);
    }
  }

  async function confirmDelete() {
    if (!deleting) return;
    // HRP-102: only indicator deletions cascade across matrices/assessments;
    // material deletions stay scoped to the competence detail page.
    if (deleting.kind === "indicator" && usage?.is_used) {
      setUsageConfirm({ kind: "delete", run: persistDelete });
      return;
    }
    await persistDelete();
  }

  // --- DnD: move indicator/material between levels (or within) ---

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  function findIndicator(itemId: string): Indicator | null {
    return detail?.indicators.find((i) => i.id === itemId) ?? null;
  }
  function findMaterial(itemId: string): Material | null {
    return detail?.materials.find((m) => m.id === itemId) ?? null;
  }

  async function handleIndicatorDragEnd(e: DragEndEvent) {
    const activeId = String(e.active.id);
    const overId = e.over ? String(e.over.id) : null;
    if (!overId) return;
    if (activeId === overId) return;

    const ind = findIndicator(activeId);
    if (!ind) return;
    // overId might be a level dropzone ("level-<lvId>") or another indicator id.
    let targetLevelId: string;
    let targetSortIndex = 0;
    if (overId.startsWith("level-")) {
      targetLevelId = overId.slice("level-".length);
      const bucket = indicatorsByLevel.get(targetLevelId) ?? [];
      targetSortIndex = bucket.length;
    } else {
      const targetInd = findIndicator(overId);
      if (!targetInd) return;
      targetLevelId = targetInd.skill_level_id;
      targetSortIndex = targetInd.sort_index;
    }
    if (
      targetLevelId === ind.skill_level_id &&
      targetSortIndex === ind.sort_index
    ) {
      return;
    }
    try {
      await api.post(`/indicators/${ind.id}/move`, {
        new_skill_level_id: targetLevelId,
        new_sort_index: targetSortIndex,
      });
      await refresh();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("errorMoveIndicator"),
      );
    }
  }

  async function handleMaterialDragEnd(e: DragEndEvent) {
    const activeId = String(e.active.id);
    const overId = e.over ? String(e.over.id) : null;
    if (!overId) return;
    if (activeId === overId) return;

    const mat = findMaterial(activeId);
    if (!mat) return;
    let targetLevelId: string;
    let targetSortIndex = 0;
    if (overId.startsWith("matlevel-")) {
      targetLevelId = overId.slice("matlevel-".length);
      const bucket = materialsByLevel.get(targetLevelId) ?? [];
      targetSortIndex = bucket.length;
    } else {
      const targetMat = findMaterial(overId);
      if (!targetMat) return;
      targetLevelId = targetMat.skill_level_id;
      targetSortIndex = targetMat.sort_index;
    }
    if (
      targetLevelId === mat.skill_level_id &&
      targetSortIndex === mat.sort_index
    ) {
      return;
    }
    try {
      await api.post(`/materials/${mat.id}/move`, {
        new_skill_level_id: targetLevelId,
        new_sort_index: targetSortIndex,
      });
      await refresh();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("errorMoveMaterial"),
      );
    }
  }

  if (loading) {
    return (
      <div className="space-y-4 p-6">
        <p className="text-sm text-muted-foreground">{t("loadingEllipsis")}</p>
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="space-y-4 p-6">
        <p className="text-sm text-muted-foreground">
          {t("competenceNotFound")}
        </p>
        <Link href="/competences" className="text-sm text-primary hover:underline">
          {t("backToLibrary")}
        </Link>
      </div>
    );
  }

  const allIndicatorIds = detail.indicators.map((i) => i.id);
  const allMaterialIds = detail.materials.map((m) => m.id);

  return (
    <div className="space-y-4 p-6" data-testid="competence-detail">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        {fromMatrixSpecId ? (
          <Link
            href={`/company/specializations/${fromMatrixSpecId}/matrix`}
            data-testid="competence-detail-back-to-matrix"
            className="flex items-center gap-1 hover:text-foreground"
          >
            <ArrowLeft className="size-3.5" />
            {t("backToMatrix")}
          </Link>
        ) : (
          <Link
            href="/competences"
            className="flex items-center gap-1 hover:text-foreground"
          >
            <ArrowLeft className="size-3.5" />
            {t("title")}
          </Link>
        )}
        {group && (
          <>
            <span>/</span>
            <span>{group.title}</span>
          </>
        )}
      </div>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-3">
          <div className="flex-1 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle data-testid="competence-detail-title">
                {detail.title}
              </CardTitle>
              {isOrigin && (
                <Badge
                  variant="outline"
                  className="gap-1"
                  data-testid="competence-detail-origin-badge"
                >
                  <Lock className="size-3" />
                  {t("badgeOrigin")}
                </Badge>
              )}
              {detail.is_published ? (
                <Badge
                  variant="default"
                  className="gap-1 bg-emerald-600"
                  data-testid="competence-detail-published-badge"
                >
                  <CheckCircle2 className="size-3" />
                  {t("badgePublished")}
                </Badge>
              ) : (
                <Badge
                  variant="secondary"
                  className="gap-1"
                  data-testid="competence-detail-unpublished-badge"
                >
                  <CircleSlash className="size-3" />
                  {t("badgeUnpublished")}
                </Badge>
              )}
              {!detail.is_active && (
                <Badge
                  variant="outline"
                  data-testid="competence-detail-hidden-badge"
                >
                  {t("badgeHiddenCapital")}
                </Badge>
              )}
            </div>
            {detail.description && (
              <p className="text-sm text-muted-foreground">
                {detail.description}
              </p>
            )}
          </div>
          {canEditMeta && (
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              <AiIndicatorsButton
                checking={activeSessionLoading && !activeSession}
                running={aiRunning}
                ready={aiReady}
                busyElsewhere={aiBusyElsewhere}
                starting={aiStarting}
                hasIndicators={detail.indicators.length > 0}
                onClick={handleAiButtonClick}
              />
              {detail.is_published ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={unpublish}
                  disabled={saving}
                  data-testid="competence-detail-btn-unpublish"
                >
                  {t("unpublish")}
                </Button>
              ) : (
                <Button
                  size="sm"
                  onClick={publish}
                  disabled={saving}
                  data-testid="competence-detail-btn-publish"
                >
                  {t("publish")}
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={toggleActive}
                disabled={saving}
                data-testid="competence-detail-btn-toggle-active"
              >
                {detail.is_active ? t("hideFromUsers") : t("showToUsers")}
              </Button>
            </div>
          )}
        </CardHeader>
      </Card>

      {/* Inline navigation between sections — easier than a sticky bar on
          competences with little scroll, still useful on long ones. */}
      <SectionNav />

      {/* Indicators per level — “what people should be able to do”. */}
      <section id="indicators-section" data-testid="competence-detail-section-indicators">
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
            <div className="flex items-start gap-2">
              <span className="mt-0.5 inline-flex size-7 items-center justify-center rounded-md bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                <Target className="size-4" aria-hidden />
              </span>
              <div className="space-y-1">
                <CardTitle>{t("indicatorsByLevel")}</CardTitle>
                <p className="text-xs text-muted-foreground">
                  {t("indicatorsByLevelHint")}
                </p>
              </div>
            </div>
            <Tooltip>
              <TooltipTrigger
                render={
                  <span
                    tabIndex={0}
                    className="inline-flex cursor-help items-center gap-1 rounded-md border bg-background px-2 py-1 text-xs text-muted-foreground"
                    data-testid="competence-detail-indicators-header-weight-help"
                  >
                    <span>{t("aboutWeights")}</span>
                  </span>
                }
              />
              <TooltipContent className="max-w-sm">
                {t("aboutWeightsTooltip")}
              </TooltipContent>
            </Tooltip>
          </CardHeader>
          <CardContent className="space-y-4">
            {usage?.is_used && canEditMeta && (
              <CompetenceUsageBanner
                usage={usage}
                testIdPrefix="competence-detail-usage"
              />
            )}
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleIndicatorDragEnd}
            >
              <SortableContext
                items={allIndicatorIds}
                strategy={verticalListSortingStrategy}
              >
                {orderedLevels.map((level, idx) => (
                  <LevelIndicatorsBlock
                    key={level.id}
                    level={level}
                    tokens={levelTokens(level, idx)}
                    indicators={indicatorsByLevel.get(level.id) ?? []}
                    canEdit={canEditMeta}
                    competenceId={detail.id}
                    onAdd={() => openCreateIndicator(level.id)}
                    onEdit={openEditIndicator}
                    onDelete={(ind) =>
                      setDeleting({
                        kind: "indicator",
                        id: ind.id,
                        title: ind.title,
                      })
                    }
                    onWeightChange={updateIndicatorWeight}
                    onBulkSaved={refresh}
                  />
                ))}
              </SortableContext>
            </DndContext>
          </CardContent>
        </Card>
      </section>

      <section
        id="materials-context-section"
        data-testid="competence-detail-section-materials-context"
      >
        <MaterialOverridesPanel
          competenceId={detail.id}
          baseMaterials={detail.materials}
          canEdit={canEditMeta}
        />
      </section>

      {/* Materials per level — “how people get there”. */}
      <section
        id="materials-level-section"
        data-testid="competence-detail-section-materials-level"
      >
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
            <div className="flex items-start gap-2">
              <span className="mt-0.5 inline-flex size-7 items-center justify-center rounded-md bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-200">
                <BookOpen className="size-4" aria-hidden />
              </span>
              <div className="space-y-1">
                <CardTitle>{t("materialsByLevel")}</CardTitle>
                <p className="text-xs text-muted-foreground">
                  {t("materialsByLevelHint")}
                </p>
              </div>
            </div>
            {canEditMeta && (
              <Button
                size="sm"
                variant="default"
                data-testid="materials-ai-open"
                onClick={() => setMaterialsAiOpen(true)}
              >
                <Sparkles className="mr-2 h-4 w-4" />
                {t("generateWithAi")}
              </Button>
            )}
          </CardHeader>
          <CardContent className="space-y-4">
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleMaterialDragEnd}
            >
              <SortableContext
                items={allMaterialIds}
                strategy={verticalListSortingStrategy}
              >
                {orderedLevels.map((level, idx) => (
                  <LevelMaterialsBlock
                    key={level.id}
                    level={level}
                    tokens={levelTokens(level, idx)}
                    materials={materialsByLevel.get(level.id) ?? []}
                    indicatorsCount={
                      indicatorsByLevel.get(level.id)?.length ?? 0
                    }
                    canEdit={canEditMeta}
                    onAdd={() => openCreateMaterial(level.id)}
                    onEdit={openEditMaterial}
                    onDelete={(mat) =>
                      setDeleting({
                        kind: "material",
                        id: mat.id,
                        title: mat.title,
                      })
                    }
                    onGenerate={() => setMaterialsAiOpen(true)}
                  />
                ))}
              </SortableContext>
            </DndContext>
          </CardContent>
        </Card>
      </section>

      {/* Indicator dialog */}
      <Dialog open={indDialogOpen} onOpenChange={setIndDialogOpen}>
        <DialogContent data-testid="competence-detail-indicator-dialog">
          <DialogHeader>
            <DialogTitle>
              {editingInd ? t("editIndicator") : t("addIndicator")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label>{t("fieldTitle")}</Label>
              <Textarea
                value={indForm.title}
                rows={2}
                onChange={(e) => setIndForm({ ...indForm, title: e.target.value })}
                data-testid="competence-detail-indicator-input-title"
              />
            </div>
            <div className="space-y-1.5">
              <Label>{t("fieldSkillLevel")}</Label>
              <Select
                value={indForm.skill_level_id}
                onValueChange={(v) => setIndForm({ ...indForm, skill_level_id: v })}
              >
                <SelectTrigger
                  className="w-full"
                  data-testid="competence-detail-indicator-select-level"
                >
                  <SelectValue placeholder={t("pickLevel")}>
                    {selectedIndLevel
                      ? skillLevelLabel(tRef, selectedIndLevel)
                      : undefined}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {orderedLevels.map((lv) => (
                    <SelectItem key={lv.id} value={lv.id}>
                      {skillLevelLabel(tRef, lv)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>{t("fieldWeight")}</Label>
              <Input
                type="number"
                value={indForm.weight}
                onChange={(e) =>
                  setIndForm({ ...indForm, weight: Number(e.target.value) })
                }
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIndDialogOpen(false)}
              disabled={saving}
            >
              {tc("cancel")}
            </Button>
            <Button
              onClick={saveIndicator}
              disabled={saving}
              data-testid="competence-detail-indicator-btn-save"
            >
              {saving
                ? t("savingEllipsis")
                : editingInd
                  ? t("save")
                  : t("add")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Material dialog */}
      <Dialog open={matDialogOpen} onOpenChange={setMatDialogOpen}>
        <DialogContent data-testid="competence-detail-material-dialog">
          <DialogHeader>
            <DialogTitle>
              {editingMat ? t("editMaterial") : t("addMaterial")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label>{t("fieldTitle")}</Label>
              <Input
                value={matForm.title}
                onChange={(e) =>
                  setMatForm({ ...matForm, title: e.target.value })
                }
                data-testid="competence-detail-material-input-title"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>{t("fieldSkillLevel")}</Label>
                <Select
                  value={matForm.skill_level_id}
                  onValueChange={(v) =>
                    setMatForm({ ...matForm, skill_level_id: v })
                  }
                >
                  <SelectTrigger
                    className="w-full"
                    data-testid="competence-detail-material-select-level"
                  >
                    <SelectValue placeholder={t("pickLevel")}>
                      {selectedMatLevel
                        ? skillLevelLabel(tRef, selectedMatLevel)
                        : undefined}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {orderedLevels.map((lv) => (
                      <SelectItem key={lv.id} value={lv.id}>
                        {skillLevelLabel(tRef, lv)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>{t("fieldFormat")}</Label>
                <Select
                  value={matForm.format}
                  onValueChange={(v) =>
                    setMatForm({ ...matForm, format: v })
                  }
                >
                  <SelectTrigger
                    className="w-full"
                    data-testid="competence-detail-material-select-format"
                  >
                    <SelectValue placeholder={t("pickFormat")}>
                      {materialFormatLabel(t, matForm.format) ?? undefined}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">{t("formatUnspecified")}</SelectItem>
                    {MATERIAL_FORMATS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {t(opt.labelKey)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>{t("fieldLink")}</Label>
              <Input
                value={matForm.link}
                onChange={(e) =>
                  setMatForm({ ...matForm, link: e.target.value })
                }
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>{t("fieldStudyTime")}</Label>
                <Input
                  type="number"
                  value={matForm.study_time}
                  onChange={(e) =>
                    setMatForm({ ...matForm, study_time: e.target.value })
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>
                  {t("fieldType")}
                  <span className="text-destructive"> *</span>
                </Label>
                <Select
                  value={matForm.material_type}
                  onValueChange={(v) =>
                    setMatForm({ ...matForm, material_type: v })
                  }
                >
                  <SelectTrigger
                    className="w-full"
                    data-testid="competence-detail-material-select-type"
                  >
                    <SelectValue placeholder={t("pickType")}>
                      {(() => {
                        const opt = materialTypeOption(matForm.material_type);
                        if (!opt) return undefined;
                        const Icon = opt.icon;
                        return (
                          <span className="flex items-center gap-1.5">
                            <Icon className="size-3.5 text-muted-foreground" />
                            {t(opt.labelKey)}
                          </span>
                        );
                      })()}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {MATERIAL_TYPES.map((opt) => {
                      const Icon = opt.icon;
                      return (
                        <SelectItem key={opt.value} value={opt.value}>
                          <Icon className="size-3.5 text-muted-foreground" />
                          {t(opt.labelKey)}
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>{t("fieldComment")}</Label>
              <Textarea
                rows={2}
                value={matForm.comment}
                onChange={(e) =>
                  setMatForm({ ...matForm, comment: e.target.value })
                }
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setMatDialogOpen(false)}
              disabled={saving}
            >
              {tc("cancel")}
            </Button>
            <Button
              onClick={saveMaterial}
              disabled={saving}
              data-testid="competence-detail-material-btn-save"
            >
              {saving
                ? t("savingEllipsis")
                : editingMat
                  ? t("save")
                  : t("add")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => {
          if (!o) setDeleting(null);
        }}
        title={
          deleting
            ? deleting.kind === "indicator"
              ? t("deleteIndicator")
              : t("deleteMaterial")
            : tc("delete")
        }
        description={
          deleting
            ? t("deleteSimpleDescription", { title: deleting.title })
            : ""
        }
        onConfirm={confirmDelete}
        loading={saving}
      />

      {/* HRP-102: usage warning shown when persisting indicator changes on a
          competence that already participates in matrices/assessments. */}
      <CompetenceUsageWarningDialog
        open={usageConfirm !== null}
        onOpenChange={(o) => {
          if (!o) setUsageConfirm(null);
        }}
        usage={usage}
        title={
          usageConfirm?.kind === "delete"
            ? t("usageDeleteAnywayTitle")
            : t("usageSaveAnywayTitle")
        }
        body={
          usageConfirm?.kind === "delete"
            ? t("usageDeleteAnywayBody")
            : t("usageSaveAnywayBody")
        }
        confirmLabel={
          usageConfirm?.kind === "delete"
            ? t("usageDeleteAnywayConfirm")
            : t("usageSaveAnywayConfirm")
        }
        onConfirm={() => {
          if (usageConfirm) void usageConfirm.run();
        }}
        loading={saving}
      />

      {/* AI indicator generation flow */}
      <GenerationConfirmDialog
        open={aiConfirmOpen}
        onOpenChange={setAiConfirmOpen}
        scope="competence_indicators"
        targetTitle={detail.title}
        targetId={detail.id}
        onSubmit={async (params) => {
          await startIndicatorGeneration(params);
        }}
      />
      <PreflightModal
        open={aiPreflightOpen}
        onOpenChange={(v) => {
          setAiPreflightOpen(v);
          if (!v) setAiOthers([]);
        }}
        hasOwnSession={false}
        others={aiOthers}
      />
      <GenerationDrawer
        open={aiDrawerOpen}
        onOpenChange={setAiDrawerOpen}
        targetTitleResolver={(targetId) =>
          targetId === detail.id ? detail.title : null
        }
        applyWarning={
          usage?.is_used ? (
            <CompetenceUsageBanner
              usage={usage}
              testIdPrefix="competence-detail-ai-usage"
            />
          ) : null
        }
        applyGuard={async () => {
          if (!usage?.is_used) return true;
          return new Promise<boolean>((resolve) => {
            aiApplyResolverRef.current = resolve;
            setAiApplyConfirmOpen(true);
          });
        }}
        onApplied={() => {
          void refreshActiveSession();
          refresh();
        }}
      />

      <CompetenceUsageWarningDialog
        open={aiApplyConfirmOpen}
        onOpenChange={(open) => {
          if (!open && aiApplyResolverRef.current) {
            aiApplyResolverRef.current(false);
            aiApplyResolverRef.current = null;
          }
          setAiApplyConfirmOpen(open);
        }}
        usage={usage}
        title={t("usageApplyAiTitle")}
        body={t("usageApplyAiBody")}
        confirmLabel={t("usageApplyAiConfirm")}
        onConfirm={() => {
          if (aiApplyResolverRef.current) {
            aiApplyResolverRef.current(true);
            aiApplyResolverRef.current = null;
          }
          setAiApplyConfirmOpen(false);
        }}
      />

      {detail && (
        <MaterialsAIDialog
          competenceId={detail.id}
          open={materialsAiOpen}
          onOpenChange={setMaterialsAiOpen}
          skillLevels={orderedLevels}
          onSaved={() => {
            refresh();
          }}
        />
      )}
    </div>
  );
}

/**
 * Inline jump menu — fast nav across the three sections without the
 * weight of a sticky bar. Each link is a plain anchor so keyboard users
 * get native focus behaviour.
 */
function SectionNav() {
  const t = useTranslations("competences");
  const items: { id: string; label: string; testId: string }[] = [
    {
      id: "indicators-section",
      label: t("sectionIndicators"),
      testId: "competence-detail-nav-indicators",
    },
    {
      id: "materials-context-section",
      label: t("sectionMaterialsByContext"),
      testId: "competence-detail-nav-materials-context",
    },
    {
      id: "materials-level-section",
      label: t("materialsByLevel"),
      testId: "competence-detail-nav-materials-level",
    },
  ];
  return (
    <nav
      aria-label={t("jumpToSectionAria")}
      className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"
      data-testid="competence-detail-section-nav"
    >
      <span>{t("jumpTo")}</span>
      {items.map((item) => (
        <a
          key={item.id}
          href={`#${item.id}`}
          className="rounded-md border bg-background px-2 py-1 hover:bg-muted/60 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          data-testid={item.testId}
        >
          {item.label}
        </a>
      ))}
    </nav>
  );
}

function AiIndicatorsButton({
  checking,
  running,
  ready,
  busyElsewhere,
  starting,
  hasIndicators,
  onClick,
}: {
  /** HRP-122 REDO #3: surface a "Checking session…" state while the
   *  hook's initial fetch resolves so we don't briefly show a Generate
   *  affordance for a competence that already has a session in flight. */
  checking: boolean;
  running: boolean;
  ready: boolean;
  busyElsewhere: boolean;
  starting: boolean;
  /** HRP-102: switches the idle CTA between Generate (empty competence)
   *  and Augment (already has at least one indicator). */
  hasIndicators: boolean;
  onClick: () => void;
}) {
  const t = useTranslations("competences");
  let label = hasIndicators
    ? t("augmentIndicatorsAi")
    : t("generateIndicatorsAi");
  let testId = hasIndicators
    ? "competence-detail-btn-ai-augment-indicators"
    : "competence-detail-btn-ai-generate-indicators";
  let icon = <Sparkles className="mr-1 size-4" />;
  let variant: "default" | "outline" = "outline";
  if (checking) {
    label = t("genCheckingSession");
    testId = "competence-detail-btn-ai-checking";
    icon = <Loader2 className="mr-1 size-4 animate-spin" />;
  } else if (running) {
    label = t("genInProgress");
    testId = "competence-detail-btn-ai-running";
    icon = <Loader2 className="mr-1 size-4 animate-spin" />;
  } else if (ready) {
    label = t("genOpenActiveSession");
    testId = "competence-detail-btn-ai-ready";
    variant = "default";
  }
  const button = (
    <Button
      variant={variant}
      size="sm"
      onClick={onClick}
      disabled={starting || checking}
      data-testid={testId}
      aria-busy={checking || undefined}
    >
      {icon}
      {label}
    </Button>
  );
  if (!busyElsewhere) return button;
  return (
    <Tooltip>
      <TooltipTrigger render={<span tabIndex={-1} className="inline-flex" />}>
        {button}
      </TooltipTrigger>
      <TooltipContent data-testid="competence-detail-btn-ai-tooltip">
        {ready ? t("aiTooltipReady") : t("aiTooltipBusy")}
      </TooltipContent>
    </Tooltip>
  );
}

function formatUsageError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message || fallback;
  if (err instanceof Error) return err.message || fallback;
  return fallback;
}

function LevelIndicatorsBlock({
  level,
  tokens,
  indicators,
  canEdit,
  competenceId,
  onAdd,
  onEdit,
  onDelete,
  onWeightChange,
  onBulkSaved,
}: {
  level: SkillLevel;
  tokens: LevelTokens;
  indicators: Indicator[];
  canEdit: boolean;
  competenceId: string;
  onAdd: () => void;
  onEdit: (ind: Indicator) => void;
  onDelete: (ind: Indicator) => void;
  onWeightChange: (ind: Indicator, next: number) => Promise<void>;
  onBulkSaved: () => void;
}) {
  const t = useTranslations("competences");
  const tc = useTranslations("common");
  const tRef = useTranslations("reference");
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkText, setBulkText] = useState("");
  const [bulkSaving, setBulkSaving] = useState(false);

  async function handleBulkSave() {
    const lines = bulkText
      .split(/\r?\n/)
      .map((t) => t.trim())
      .filter((t) => t.length > 0);
    if (lines.length === 0) {
      toast.error(t("errorBulkNeedIndicator"));
      return;
    }
    setBulkSaving(true);
    try {
      const baseSort = indicators.length;
      await api.post(`/competences/${competenceId}/indicators/bulk`, {
        indicators: lines.map((title, idx) => ({
          title,
          skill_level_id: level.id,
          sort_index: baseSort + idx,
        })),
      });
      toast.success(t("toastIndicatorsBulkAdded", { count: lines.length }));
      setBulkText("");
      setBulkOpen(false);
      onBulkSaved();
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail || err.message
          : err instanceof Error
            ? err.message
            : t("errorSave");
      toast.error(String(msg));
    } finally {
      setBulkSaving(false);
    }
  }

  return (
    <div
      data-testid={`competence-detail-level-${level.id}`}
      className={cn(
        "relative overflow-hidden rounded-md border p-3",
        tokens.bg,
        tokens.border,
      )}
    >
      <span
        aria-hidden
        className={cn("absolute inset-y-0 left-0 w-1", tokens.rail)}
      />
      <div className="mb-2 flex items-center justify-between gap-2 pl-2">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className={cn("size-2 rounded-full", tokens.dot)}
          />
          <h3 className="text-sm font-medium">
            {skillLevelLabel(tRef, level)}
          </h3>
          <Badge
            variant="outline"
            className="h-5 px-1.5 text-[10px]"
            data-testid={`competence-detail-level-${level.id}-count`}
          >
            {t("indicatorCount", { count: indicators.length })}
          </Badge>
        </div>
        {canEdit && (
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setBulkOpen((v) => !v)}
              data-testid={`competence-detail-level-${level.id}-btn-add-bulk`}
            >
              <Plus className="mr-1 size-3.5" />
              {bulkOpen ? t("hideBulkAdd") : t("addMultiple")}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onAdd}
              data-testid={`competence-detail-level-${level.id}-btn-add-indicator`}
            >
              <Plus className="mr-1 size-3.5" />
              {t("addIndicator")}
            </Button>
          </div>
        )}
      </div>

      {canEdit && bulkOpen && (
        <div
          data-testid={`competence-detail-level-${level.id}-bulk-form`}
          className="mb-3 space-y-2 rounded-md border border-dashed bg-muted/40 p-2"
        >
          <p className="text-xs text-muted-foreground">
            {t("bulkIndicatorsHint")}
          </p>
          <textarea
            data-testid={`competence-detail-level-${level.id}-bulk-textarea`}
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
            rows={Math.min(8, Math.max(4, bulkText.split(/\r?\n/).length))}
            placeholder={t("bulkIndicatorsPlaceholder")}
            className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            disabled={bulkSaving}
          />
          <div className="flex items-center justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setBulkOpen(false);
                setBulkText("");
              }}
              disabled={bulkSaving}
            >
              {tc("cancel")}
            </Button>
            <Button
              size="sm"
              data-testid={`competence-detail-level-${level.id}-bulk-save`}
              onClick={handleBulkSave}
              disabled={bulkSaving || bulkText.trim().length === 0}
            >
              {bulkSaving ? t("savingEllipsis") : t("saveIndicators")}
            </Button>
          </div>
        </div>
      )}

      {indicators.length === 0 ? (
        <p
          className="py-2 pl-2 text-xs text-muted-foreground"
          data-testid={`competence-detail-level-${level.id}-empty`}
        >
          {t("levelNoIndicators")}
        </p>
      ) : (
        <ul className="space-y-1 pl-2">
          {indicators.map((ind) => (
            <SortableIndicatorRow
              key={ind.id}
              indicator={ind}
              canEdit={canEdit}
              onEdit={() => onEdit(ind)}
              onDelete={() => onDelete(ind)}
              onWeightChange={(next) => onWeightChange(ind, next)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function SortableIndicatorRow({
  indicator,
  canEdit,
  onEdit,
  onDelete,
  onWeightChange,
}: {
  indicator: Indicator;
  canEdit: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onWeightChange: (next: number) => Promise<void>;
}) {
  const t = useTranslations("competences");
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: indicator.id, disabled: !canEdit });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : undefined,
  };
  // Suspiciously short titles ("xx", "aa", single letters) slip in when
  // users hit Save by mistake — flag them so the content owner sees
  // them at a glance. Threshold matches the TZ (≤ 3 chars).
  const trimmedTitle = indicator.title.trim();
  const looksSuspicious = trimmedTitle.length > 0 && trimmedTitle.length <= 3;
  return (
    <li
      ref={setNodeRef}
      style={style}
      data-testid={`competence-detail-indicator-${indicator.id}`}
      className="flex items-center gap-2 rounded-md border bg-background px-2 py-1.5"
    >
      {canEdit && (
        <button
          type="button"
          className="cursor-grab text-muted-foreground"
          aria-label={t("dragIndicatorAria")}
          data-testid={`competence-detail-indicator-${indicator.id}-handle`}
          {...attributes}
          {...listeners}
        >
          <GripVertical className="size-4" />
        </button>
      )}
      <span className="flex-1 text-sm">{indicator.title}</span>
      {looksSuspicious && (
        <Tooltip>
          <TooltipTrigger
            render={
              <span
                tabIndex={0}
                className="inline-flex cursor-help text-amber-600 dark:text-amber-400"
                data-testid={`competence-detail-indicator-${indicator.id}-warning-suspicious-text`}
                aria-label={t("indicatorLooksIncomplete")}
              />
            }
          >
            <AlertTriangle className="size-3.5" />
          </TooltipTrigger>
          <TooltipContent>{t("indicatorLooksIncomplete")}</TooltipContent>
        </Tooltip>
      )}
      <IndicatorWeight
        value={indicator.weight}
        editable={canEdit}
        onChange={onWeightChange}
        testIdPrefix={`competence-detail-indicator-${indicator.id}-weight`}
      />
      {canEdit && (
        <>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onEdit}
            data-testid={`competence-detail-indicator-${indicator.id}-btn-edit`}
          >
            <Pencil className="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onDelete}
            data-testid={`competence-detail-indicator-${indicator.id}-btn-delete`}
          >
            <Trash2 className="size-3.5" />
          </Button>
        </>
      )}
    </li>
  );
}

function LevelMaterialsBlock({
  level,
  tokens,
  materials,
  indicatorsCount,
  canEdit,
  onAdd,
  onEdit,
  onDelete,
  onGenerate,
}: {
  level: SkillLevel;
  tokens: LevelTokens;
  materials: Material[];
  indicatorsCount: number;
  canEdit: boolean;
  onAdd: () => void;
  onEdit: (mat: Material) => void;
  onDelete: (mat: Material) => void;
  onGenerate: () => void;
}) {
  const t = useTranslations("competences");
  const tRef = useTranslations("reference");
  // “N materials for M indicators” — when M > 0 and N = 0, the level
  // isn’t closed yet; nudge the operator to add or generate.
  const hasGap = materials.length === 0 && indicatorsCount > 0;
  return (
    <div
      data-testid={`competence-detail-matlevel-${level.id}`}
      className={cn(
        "relative overflow-hidden rounded-md border p-3",
        tokens.bg,
        tokens.border,
      )}
    >
      <span
        aria-hidden
        className={cn("absolute inset-y-0 left-0 w-1", tokens.rail)}
      />
      <div className="mb-2 flex items-center justify-between gap-2 pl-2">
        <div className="flex flex-wrap items-center gap-2">
          <span
            aria-hidden
            className={cn("size-2 rounded-full", tokens.dot)}
          />
          <h3 className="text-sm font-medium">
            {skillLevelLabel(tRef, level)}
          </h3>
          <Badge
            variant="outline"
            className={cn(
              "h-5 px-1.5 text-[10px]",
              hasGap && "border-amber-400 bg-amber-50 text-amber-800 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200",
            )}
            data-testid={`competence-detail-matlevel-${level.id}-count`}
          >
            {t("materialsForIndicators", {
              materials: materials.length,
              indicators: indicatorsCount,
            })}
          </Badge>
        </div>
        {canEdit && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onAdd}
            data-testid={`competence-detail-matlevel-${level.id}-btn-add-material`}
          >
            <Plus className="mr-1 size-3.5" />
            {t("addMaterial")}
          </Button>
        )}
      </div>
      {materials.length === 0 ? (
        hasGap && canEdit ? (
          <div
            className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-dashed border-amber-300 bg-amber-50/60 px-2 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
            data-testid={`competence-detail-matlevel-${level.id}-warning-empty`}
          >
            <span>
              {t("indicatorsNoMaterials", { count: indicatorsCount })}
            </span>
            <Button
              size="sm"
              variant="outline"
              className="h-7 border-amber-300 bg-background"
              onClick={onGenerate}
              data-testid={`competence-detail-matlevel-${level.id}-btn-generate-ai`}
            >
              <Sparkles className="mr-1 size-3.5" />
              {t("generateWithAi")}
            </Button>
          </div>
        ) : (
          <p
            className="py-2 pl-2 text-xs text-muted-foreground"
            data-testid={`competence-detail-matlevel-${level.id}-empty`}
          >
            {t("levelNoMaterials")}
          </p>
        )
      ) : (
        <ul className="space-y-1 pl-2">
          {materials.map((mat) => (
            <SortableMaterialRow
              key={mat.id}
              material={mat}
              canEdit={canEdit}
              onEdit={() => onEdit(mat)}
              onDelete={() => onDelete(mat)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function SortableMaterialRow({
  material,
  canEdit,
  onEdit,
  onDelete,
}: {
  material: Material;
  canEdit: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const t = useTranslations("competences");
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: material.id, disabled: !canEdit });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : undefined,
  };
  return (
    <li
      ref={setNodeRef}
      style={style}
      data-testid={`competence-detail-material-${material.id}`}
      className="flex items-center gap-2 rounded-md border bg-background px-2 py-1.5"
    >
      {canEdit && (
        <button
          type="button"
          className="cursor-grab text-muted-foreground"
          aria-label={t("dragMaterialAria")}
          data-testid={`competence-detail-material-${material.id}-handle`}
          {...attributes}
          {...listeners}
        >
          <GripVertical className="size-4" />
        </button>
      )}
      <span className="flex-1 text-sm">{material.title}</span>
      {(() => {
        const typeOpt = materialTypeOption(material.material_type);
        if (!typeOpt) return null;
        const Icon = typeOpt.icon;
        return (
          <Icon
            className="size-3.5 text-muted-foreground"
            aria-label={t(typeOpt.labelKey)}
          />
        );
      })()}
      {material.format && (
        <span className="text-xs text-muted-foreground">
          {materialFormatLabel(t, material.format)}
        </span>
      )}
      {canEdit && (
        <>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onEdit}
            data-testid={`competence-detail-material-${material.id}-btn-edit`}
          >
            <Pencil className="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onDelete}
            data-testid={`competence-detail-material-${material.id}-btn-delete`}
          >
            <Trash2 className="size-3.5" />
          </Button>
        </>
      )}
    </li>
  );
}
