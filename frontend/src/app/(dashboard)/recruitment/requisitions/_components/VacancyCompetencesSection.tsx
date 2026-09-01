"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import type {
  CompetenceGroupTree,
  Vacancy,
  VacancyCompetenceLink,
  VacancyProfile,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { CompetenceTreePicker } from "@/components/competence/competence-tree-picker";
import { useCompetenceTree } from "@/hooks/use-competence-tree";
import { usePermissions } from "@/hooks/use-permissions";
import {
  CompetenceTreeView,
  findUnnamedCompetence,
  sanitizeProfileData,
} from "@/components/recruitment/competence-tree-view";
import {
  ProfileGenerationStatus,
  sessionHasPendingResult,
  type ProfileSessionPayload,
} from "@/components/recruitment/profile-generation-status";
import { ProfileGenerationDialog } from "@/components/recruitment/profile-generation-dialog";
import { api } from "@/lib/api";
import { Sparkles, BookOpen, Pencil } from "lucide-react";
import { toast } from "sonner";

interface VacancyCompetencesSectionProps {
  vacancy: Vacancy;
  profile: VacancyProfile | null;
  canEdit: boolean;
  onProfileChange: () => void | Promise<void>;
  /** HRP-687: fired after the library-linked competence set changed, so
   *  the internal-candidates block re-reads `has_library_competences`
   *  and its "Post to talent market" button unlocks without an F5. */
  onLibraryCompetencesChange?: () => void;
}

// HRP-318: the Edit affordance now lives inline on the section card — the
// same UX pattern as the Overview block above. Cancel and Save replace the
// Edit button while editing; Regenerate and Add from dictionary stay docked
// in the header so the recruiter can still pivot mid-edit. The modal dialog
// is reserved for the LLM Generate / Regenerate flow.
export function VacancyCompetencesSection({
  vacancy,
  profile,
  canEdit,
  onProfileChange,
  onLibraryCompetencesChange,
}: VacancyCompetencesSectionProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draftData, setDraftData] = useState<Record<string, unknown> | null>(
    null,
  );
  const [saving, setSaving] = useState(false);
  // HRP-339: optimistic lock — the profile version the edit started from.
  // Save sends it as base_version; the backend 409s if the profile moved
  // on (generation applied in another tab, a concurrent recruiter save).
  const [baseVersion, setBaseVersion] = useState<number | null>(null);
  // HRP-318 REDO: empty just-added groups/subgroups live inside the tree
  // component (the flat payload cannot hold them), so the dirty check
  // cannot see them — the tree reports their presence for the Cancel
  // confirm instead.
  const [hasPendingSections, setHasPendingSections] = useState(false);
  // HRP-235 REDO (QA cases 2-4): the status banner mirrors the polled
  // session up here so the action buttons can lock while a generation is
  // running or a finished result is still pending review — otherwise a
  // second session could be started (or the profile edited) underneath
  // the unreviewed result.
  const [activeSession, setActiveSession] =
    useState<ProfileSessionPayload | null>(null);
  const [statusRefreshKey, setStatusRefreshKey] = useState(0);

  // HRP-687: library-linked competences (`VacancyCompetence`) live beside
  // the AI profile, not inside it — the profile carries free-text slugs,
  // these carry real dictionary ids and are what the talent-market matcher
  // (and therefore the "Post to talent market" bridge) reads.
  const { tree } = useCompetenceTree();
  // PATCH …/competences is require_role("admin", "recruiter") while this
  // page is open to every recruitment viewer — same rule, same shape as
  // the internal-candidates block: disabled with the reason, not a 403
  // at the end of the flow.
  const { isAdmin, isRecruiter } = usePermissions();
  const canManageLibrary = isAdmin || isRecruiter;
  const [libraryRows, setLibraryRows] = useState<VacancyCompetenceLink[]>([]);
  // The GET is the baseline for a replace-set PATCH, so a failed read is
  // not "no competences" — it is "we do not know", and nothing may be
  // saved from it.
  const [libraryLoadFailed, setLibraryLoadFailed] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerIds, setPickerIds] = useState<Set<string>>(() => new Set());
  const [savingLibrary, setSavingLibrary] = useState(false);

  const sessionBlocksActions =
    activeSession?.status === "running" || sessionHasPendingResult(activeSession);

  const loadLibrary = useCallback(async () => {
    try {
      setLibraryRows(
        await api.get<VacancyCompetenceLink[]>(
          `/recruitment/vacancies/${vacancy.id}/competences`,
        ),
      );
      setLibraryLoadFailed(false);
    } catch {
      // Never fall back to an empty list: the picker seeds itself from
      // these rows and saves the result as a replace-set, so one failed
      // GET used to wipe every library competence on the vacancy — with a
      // success toast on top of it.
      setLibraryLoadFailed(true);
    }
  }, [vacancy.id]);

  useEffect(() => {
    void loadLibrary();
  }, [loadLibrary]);

  const titleByCompetenceId = useMemo(() => {
    const map = new Map<string, string>();
    const walk = (groups: CompetenceGroupTree[]) => {
      for (const g of groups) {
        for (const c of g.competences || []) map.set(c.id, c.title);
        if (g.children?.length) walk(g.children);
      }
    };
    walk(tree);
    return map;
  }, [tree]);

  function openPicker() {
    if (libraryLoadFailed) {
      // Refuse and retry in the same click — the editor reopens by
      // itself on the next press once the read comes back.
      toast.error(t("vacancyLibraryLoadFailed"));
      void loadLibrary();
      return;
    }
    setPickerIds(new Set(libraryRows.map((r) => r.competence_id)));
    setPickerOpen(true);
  }

  async function saveLibrary() {
    // Second lock on the same door: the payload below is only as complete
    // as the rows we read.
    if (libraryLoadFailed || !canManageLibrary) return;
    setSavingLibrary(true);
    try {
      // PATCH …/competences is a replace-set, so a row that survives the
      // edit has to be sent back with the levels and source it already
      // carries — otherwise re-opening the picker would silently strip
      // the target levels a seeded or API-set row came with.
      const existing = new Map(libraryRows.map((r) => [r.competence_id, r]));
      const rows = await api.patch<VacancyCompetenceLink[]>(
        `/recruitment/vacancies/${vacancy.id}/competences`,
        {
          competences: [...pickerIds].map((id) => ({
            competence_id: id,
            skill_level_ids: existing.get(id)?.skill_level_ids ?? [],
            source: existing.get(id)?.source ?? "library",
          })),
        },
      );
      setLibraryRows(rows);
      setPickerOpen(false);
      toast.success(t("vacancyLibraryToastSaved"));
      onLibraryCompetencesChange?.();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("vacancyLibrarySaveFailed"),
      );
    } finally {
      setSavingLibrary(false);
    }
  }

  // Stable identity: the dialog's polling effect lists onOpenChange in
  // its deps — an inline arrow would tear the interval down and fire an
  // immediate extra tick on every parent re-render.
  const handleDialogOpenChange = useCallback((next: boolean) => {
    setDialogOpen(next);
    // Re-poll the banner the moment the dialog closes so an
    // apply/discard/cancel is reflected without waiting out the next
    // polling tick.
    if (!next) setStatusRefreshKey((k) => k + 1);
  }, []);

  const profileData = profile?.profile_data as
    | Record<string, unknown>
    | undefined;
  const hasProfile = Boolean(
    profileData &&
      Array.isArray((profileData as { competences?: unknown }).competences) &&
      (((profileData as { competences: unknown[] }).competences ?? []).length ?? 0) >
        0,
  );

  // Reset the working copy whenever the upstream profile changes — covers
  // a successful Generate that lands a brand-new draft while we are not in
  // edit mode, plus the regenerate path that bypasses the inline editor.
  useEffect(() => {
    if (!editing) {
      setDraftData(null);
    }
  }, [editing, profile]);

  const initialJson = useMemo(
    () => (profileData ? JSON.stringify(profileData) : ""),
    [profileData],
  );
  const draftJson = useMemo(
    () => (draftData ? JSON.stringify(draftData) : ""),
    [draftData],
  );
  const isDirty = editing && draftJson !== "" && draftJson !== initialJson;

  function openGenerate() {
    setDialogOpen(true);
  }

  function startEdit() {
    if (!hasProfile || !profileData) {
      toast.info(t("vacancyCompetencesGenerateFirst"));
      return;
    }
    // Deep clone via JSON so the tree mutates a working copy and Cancel
    // keeps the saved profile untouched.
    setDraftData(JSON.parse(JSON.stringify(profileData)));
    setBaseVersion(profile?.version ?? null);
    setHasPendingSections(false);
    setEditing(true);
  }

  function handleCancel() {
    if (
      (isDirty || hasPendingSections) &&
      !window.confirm(t("vacancyCompetencesDiscardConfirm"))
    ) {
      return;
    }
    setDraftData(null);
    setHasPendingSections(false);
    setEditing(false);
  }

  async function handleSave() {
    if (!isDirty || !draftData) return;
    // HRP-318 REDO: a freshly added competence starts with an empty name;
    // block Save until it is filled so the payload never carries nameless
    // entries (assessment sheets key their labels off the name). Point at
    // the offending section — the card may sit in a collapsed subgroup.
    const unnamed = findUnnamedCompetence(draftData);
    if (unnamed) {
      const where = [unnamed.group, unnamed.subgroup]
        .filter(Boolean)
        .join(" → ");
      toast.error(
        where
          ? t("vacancyCompetencesUnnamedWhere", { where })
          : t("vacancyCompetencesUnnamed"),
      );
      return;
    }
    setSaving(true);
    try {
      await api.put(`/recruitment/vacancies/${vacancy.id}/profile`, {
        // Empty indicator/question rows the recruiter added but never
        // filled are dropped, not persisted as blank bullets.
        profile_data: sanitizeProfileData(draftData),
        base_version: baseVersion,
      });
      toast.success(t("vacancyProfileToastSaved"));
      await onProfileChange();
      setEditing(false);
      setDraftData(null);
      setHasPendingSections(false);
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : t("vacancyCompetencesSaveFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  const treeData = editing ? draftData : (profileData ?? null);

  return (
    <Card data-testid="vacancy-section-competences" id="competences">
      <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <CardTitle>{t("vacancyCompetencesTitle")}</CardTitle>
          {/* HRP-235 REDO (QA case 1): the structure hint only makes sense
              once there is a tree to read — hide it for the empty state. */}
          {hasProfile && (
            <p className="text-sm text-muted-foreground">
              {t("vacancyCompetencesHint")}
            </p>
          )}
        </div>
        {canEdit && (
          <div className="flex flex-wrap items-center gap-2">
            {editing ? (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleCancel}
                  disabled={saving}
                  data-testid="vacancy-competences-cancel-btn"
                >
                  {tc("cancel")}
                </Button>
                <Button
                  size="sm"
                  onClick={handleSave}
                  disabled={saving || !isDirty}
                  data-testid="vacancy-competences-save-btn"
                >
                  {saving ? t("actionSaving") : t("save")}
                </Button>
              </>
            ) : (
              hasProfile && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={startEdit}
                  disabled={sessionBlocksActions}
                  data-testid="vacancy-competences-edit-btn"
                >
                  <Pencil className="mr-1 size-4" />
                  {t("actionEdit")}
                </Button>
              )
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={openGenerate}
              disabled={editing || sessionBlocksActions}
              data-testid={
                hasProfile
                  ? "vacancy-competences-regenerate-btn"
                  : "vacancy-competences-generate-btn"
              }
            >
              <Sparkles className="mr-1 size-4" />
              {hasProfile
                ? t("vacancyCompetencesRegenerate")
                : t("vacancyCompetencesGenerate")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              data-testid="vacancy-competences-add-from-dict-btn"
              disabled={editing || sessionBlocksActions || !canManageLibrary}
              title={
                canManageLibrary ? undefined : t("vacancyLibraryNoPermission")
              }
              onClick={openPicker}
            >
              <BookOpen className="mr-1 size-4" />
              {t("vacancyCompetencesAddFromDict")}
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <ProfileGenerationStatus
          vacancyId={vacancy.id}
          onSessionChange={setActiveSession}
          onReview={openGenerate}
          refreshKey={statusRefreshKey}
        />
        {libraryRows.length > 0 && (
          <div className="space-y-1.5" data-testid="vacancy-library-competences">
            <p className="text-sm font-medium">
              {t("vacancyLibraryCompetencesTitle")}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {libraryRows.map((row) => (
                <Badge
                  key={row.id}
                  variant="secondary"
                  data-testid={`vacancy-library-competence-${row.competence_id}`}
                >
                  {titleByCompetenceId.get(row.competence_id) ?? "—"}
                </Badge>
              ))}
            </div>
          </div>
        )}
        {hasProfile ? (
          <CompetenceTreeView
            profileData={treeData}
            readOnly={!editing}
            editable={editing}
            onChange={editing ? setDraftData : undefined}
            onPendingChange={editing ? setHasPendingSections : undefined}
          />
        ) : (
          <div
            className="rounded-md border border-dashed p-8 text-center"
            data-testid="vacancy-competences-empty-state"
          >
            <Sparkles className="mx-auto mb-2 size-8 text-muted-foreground opacity-40" />
            <p className="text-sm font-medium text-muted-foreground">
              {t("vacancyCompetencesEmpty")}
            </p>
            {canEdit && (
              <div className="mt-4 flex justify-center gap-2">
                <Button
                  size="sm"
                  onClick={openGenerate}
                  disabled={sessionBlocksActions}
                  data-testid="vacancy-competences-generate-btn"
                >
                  <Sparkles className="mr-1 size-4" />
                  {t("vacancyCompetencesGenerateWithAi")}
                </Button>
              </div>
            )}
          </div>
        )}
      </CardContent>
      <ProfileGenerationDialog
        open={dialogOpen}
        onOpenChange={handleDialogOpenChange}
        vacancy={vacancy}
        initialProfile={profile}
        activeSession={activeSession}
        onProfileChange={onProfileChange}
      />
      <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
        <DialogContent
          data-testid="vacancy-competences-library-dialog"
          className="max-h-[85vh] overflow-y-auto sm:max-w-xl"
        >
          <DialogHeader>
            <DialogTitle>{t("vacancyLibraryDialogTitle")}</DialogTitle>
            <DialogDescription>
              {t("vacancyLibraryDialogHint")}
            </DialogDescription>
          </DialogHeader>
          <CompetenceTreePicker
            tree={tree}
            selectedIds={pickerIds}
            onChange={setPickerIds}
            testIdPrefix="vacancy-competences-library-picker"
          />
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setPickerOpen(false)}
              disabled={savingLibrary}
              data-testid="vacancy-competences-library-cancel-btn"
            >
              {tc("cancel")}
            </Button>
            <Button
              onClick={saveLibrary}
              disabled={savingLibrary}
              data-testid="vacancy-competences-library-save-btn"
            >
              {savingLibrary ? t("actionSaving") : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
