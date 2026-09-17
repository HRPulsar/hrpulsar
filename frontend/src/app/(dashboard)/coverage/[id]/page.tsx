"use client";

// HRP-756: one work container — a process or a project — with its
// breakdown into steps (Steps tab) and, per step, who covers it (Coverage
// tab, HRP-760) and what nobody covers yet (Gaps tab, HRP-759).

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Archive, Lock, Pencil, Sparkles, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LoadErrorState } from "@/components/load-error-state";
import { AccessDialog } from "@/components/coverage/access-dialog";
import { CoverageTab } from "@/components/coverage/coverage-tab";
import { GapsTab } from "@/components/coverage/gaps-tab";
import { GenerationProgress } from "@/components/coverage/generation-progress";
import { StepsEditor } from "@/components/coverage/steps-editor";
import { usePermissions } from "@/hooks/use-permissions";
import { BADGE_COLOR } from "@/lib/badge-tones";
import { newClientId } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { EECreditCostBadge } from "@/lib/ee-hooks";
import { ApiError } from "@/lib/api";
import {
  APPLY_WOULD_DISCARD,
  DECOMPOSITION_ACTION,
  type DecompositionSession,
  type Primitive,
  type WorkContainer,
  type WorkStep,
  isSessionRunning,
  workApi,
} from "@/lib/api/work";

const POLL_INTERVAL_MS = 5_000;

const STATUS_COLOR: Record<WorkContainer["status"], string> = {
  draft: BADGE_COLOR.neutral,
  active: BADGE_COLOR.green,
  archived: BADGE_COLOR.neutral,
};

export default function ContainerPage() {
  const { id } = useParams<{ id: string }>();
  // Walking from one process to another keeps this page mounted: without a
  // remount the previous container's steps, session and banner stay on the
  // screen until the new ones load.
  return <ContainerView key={id} id={id} />;
}

function ContainerView({ id }: { id: string }) {
  const t = useTranslations("coverage");
  const tc = useTranslations("common");
  const router = useRouter();
  const { canRecruit } = usePermissions();

  const [container, setContainer] = useState<WorkContainer | null>(null);
  const [steps, setSteps] = useState<WorkStep[]>([]);
  const [primitives, setPrimitives] = useState<Primitive[]>([]);
  const [session, setSession] = useState<DecompositionSession | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmReplace, setConfirmReplace] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // M3: the apply came back 409 - the draft would throw away steps that
  // carry a generated skill or the company's edits.
  const [confirmForceApply, setConfirmForceApply] = useState(false);
  const [editing, setEditing] = useState(false);
  const [accessOpen, setAccessOpen] = useState(false);
  // The Coverage tab is mounted by default and loads /coverage once: an
  // apply replaces the steps under it, so remount it to refetch.
  const [appliedCount, setAppliedCount] = useState(0);
  // One key per session: a retried Apply must not create the steps twice.
  const applyKeys = useRef<Map<string, string>>(new Map());
  // W6 (§5.5): the first generation applies itself, once per session.
  const autoApplied = useRef<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [c, s, p, latest] = await Promise.all([
        workApi.getContainer(id),
        workApi.listSteps(id),
        workApi.listPrimitives(),
        workApi.latestDecomposition(id),
      ]);
      setContainer(c);
      setSteps(s);
      setPrimitives(p);
      setSession(latest);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  // The banner follows the run by polling: WS delivery is best-effort. A
  // run that ends elsewhere (another admin applied or cancelled it) is
  // followed by a full reload so the steps match the record.
  const sessionId = session?.id;
  const sessionStatus = session?.status;
  useEffect(() => {
    if (!sessionId || !sessionStatus || !["pending", "running"].includes(sessionStatus)) {
      return;
    }
    let stale = false;
    const timer = window.setInterval(async () => {
      try {
        const next = await workApi.latestDecomposition(id);
        if (stale) return;
        setSession(next);
        if (next && !isSessionRunning(next) && next.status !== "ready") void load();
      } catch {
        // keep the last snapshot; the next tick retries
      }
    }, POLL_INTERVAL_MS);
    return () => {
      stale = true;
      window.clearInterval(timer);
    };
  }, [id, sessionId, sessionStatus, load]);

  // HRP-810: the process says what this caller may do with it.
  const access = container?.my_access ?? "read";
  const canEdit = access !== "read" && container?.status !== "archived";
  const canAccept = canEdit;
  // The agent registry and the hire handoff stay with the section's roles.
  const canManageSection = access === "manage";

  // §5.5: on the first generation there is nothing to replace, so the
  // Apply gate is a question with one answer. It applies itself and the
  // reader lands on Coverage with a number instead of on "9 steps
  // drafted". The gate survives only on a regeneration, where the
  // existing steps are about to be overwritten.
  const readyId = session?.status === "ready" ? session.id : null;
  useEffect(() => {
    if (readyId === null) return;
    // Decided once, when the run becomes ready - not re-evaluated as the
    // step list changes. Otherwise deleting the last remaining step while
    // a draft sits unapplied would apply that draft behind the user.
    if (autoApplied.current === readyId) return;
    autoApplied.current = readyId;
    if (steps.length > 0 || !canEdit) return;
    void applyGeneration();
    // ``applyGeneration`` is a hoisted declaration below, re-created on
    // every render; listing it would re-run the effect for no reason, and
    // the ref above already makes this fire once per session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readyId, steps.length, canEdit]);

  async function generate() {
    setConfirmReplace(false);
    setBusy(true);
    try {
      setSession(await workApi.startDecomposition(id));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function applyGeneration(force = false) {
    if (!session) return;
    setBusy(true);
    try {
      let key = applyKeys.current.get(session.id);
      if (!key) {
        key = newClientId();
        applyKeys.current.set(session.id, key);
      }
      await workApi.applyDecomposition(session.id, key, force);
      const [c, s, latest] = await Promise.all([
        workApi.getContainer(id),
        workApi.listSteps(id),
        workApi.latestDecomposition(id),
      ]);
      setContainer(c);
      setSteps(s);
      setSession(latest);
      setAppliedCount((n) => n + 1);
      setConfirmForceApply(false);
      toast.success(t("appliedToast", { count: s.length }));
    } catch (err) {
      // Not an error to report: the steps about to be lost are worth a
      // question, and the answer comes back as ``force``.
      if (err instanceof ApiError && err.code === APPLY_WOULD_DISCARD) {
        setConfirmForceApply(true);
      } else {
        toast.error(err instanceof Error ? err.message : t("saveFailed"));
      }
    } finally {
      setBusy(false);
    }
  }

  // A process created by mistake stays visible to the whole company until
  // it is archived or deleted; both are the section's roles only.
  async function archiveContainer() {
    setBusy(true);
    try {
      setContainer(await workApi.updateContainer(id, { status: "archived" }));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function deleteContainer() {
    setBusy(true);
    try {
      await workApi.deleteContainer(id);
      setConfirmDelete(false);
      router.push("/coverage");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function discardGeneration() {
    if (!session) return;
    setBusy(true);
    try {
      setSession(await workApi.cancelDecomposition(session.id));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  if (failed) {
    return <LoadErrorState onRetry={load} testIdPrefix="coverage-detail" />;
  }
  if (!container) {
    return <div className="py-12 text-center text-muted-foreground">{tc("loading")}</div>;
  }

  const showBanner =
    session !== null && ["pending", "running", "ready", "error"].includes(session.status);
  const draftedCount = session?.payload?.steps.length ?? 0;

  return (
    <div className="space-y-6" data-testid="coverage-detail">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold" data-testid="coverage-detail-title">
            {container.title}
          </h1>
          <Badge variant="outline">{t(`type_${container.type}`)}</Badge>
          <Badge
            className={STATUS_COLOR[container.status]}
            data-testid="coverage-detail-status"
            data-status={container.status}
          >
            {t(`status_${container.status}`)}
          </Badge>
          {canEdit && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setEditing(true)}
              data-testid="coverage-btn-edit"
            >
              <Pencil className="size-4" />
              {t("editContainer")}
            </Button>
          )}
          {container.my_access && container.my_access !== "read" && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setAccessOpen(true)}
              data-testid="coverage-btn-access"
            >
              <Lock className="size-4" />
              {t("accessButton")}
            </Button>
          )}
          {canManageSection && container.status !== "archived" && (
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => void archiveContainer()}
              data-testid="coverage-btn-archive"
            >
              <Archive className="size-4" />
              {t("archiveContainer")}
            </Button>
          )}
          {canManageSection && (
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => setConfirmDelete(true)}
              data-testid="coverage-btn-delete"
            >
              <Trash2 className="size-4" />
              {t("deleteContainer")}
            </Button>
          )}
        </div>
        {container.description && (
          <p className="max-w-3xl whitespace-pre-line text-sm text-muted-foreground">
            {container.description}
          </p>
        )}
        {container.goal && (
          <p className="max-w-3xl text-sm">
            <span className="font-medium">{t("goalLabel")}</span> {container.goal}
          </p>
        )}
      </div>

      {/* The run is about the whole container, not about one tab: the
          button and the banner sit above them, so a generation started
          from Coverage can be watched from Coverage. */}
      {canEdit && !showBanner && container.description && (
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => (steps.length > 0 ? setConfirmReplace(true) : void generate())}
            data-testid="coverage-btn-generate"
          >
            <Sparkles className="size-4" />
            {steps.length > 0 ? t("regenerateSteps") : t("generateSteps")}
            <EECreditCostBadge action={DECOMPOSITION_ACTION} />
          </Button>
        </div>
      )}

      {showBanner && session && (
        <div
          className="space-y-3 rounded-lg border bg-muted/40 p-3"
          data-testid="coverage-banner-generating"
          data-status={session.status}
          data-phase={session.phase ?? undefined}
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-64 flex-1 text-sm">
              {isSessionRunning(session) && (
                <GenerationProgress
                  phase={session.phase === "classifying" ? 2 : 1}
                  phases={2}
                  startedAt={session.created_at}
                  caption={t(
                    session.phase === "classifying" ? "generatingClassifying" : "generating",
                  )}
                  testId="coverage-generation-progress"
                />
              )}
              {session.status === "ready" && (
                <span>{t("generationReady", { count: draftedCount })}</span>
              )}
              {session.status === "error" && (
                <span className="text-destructive" data-testid="coverage-banner-error">
                  {t("generationFailed")}
                  {session.error_message ? ` ${session.error_message}` : ""}
                </span>
              )}
            </div>
              {canEdit && (
                <div className="flex gap-2">
                  {session.status === "ready" && (
                    <Button
                      size="sm"
                      disabled={busy}
                      onClick={() => void applyGeneration()}
                      data-testid="coverage-btn-apply-generation"
                    >
                      {t("applyGeneration")}
                    </Button>
                  )}
                  {session.status === "error" && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      onClick={generate}
                      data-testid="coverage-btn-retry-generation"
                    >
                      {t("tryAgain")}
                    </Button>
                  )}
                  {session.status !== "error" && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={discardGeneration}
                      data-testid="coverage-btn-discard-generation"
                    >
                      {t("discardGeneration")}
                    </Button>
                  )}
                  {session.status === "error" && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={discardGeneration}
                      data-testid="coverage-btn-dismiss-generation"
                    >
                      {t("dismiss")}
                    </Button>
                  )}
                </div>
              )}
          </div>

          {/* §5.13: the gate only survives on a regeneration, and that is
              exactly where "what am I about to lose" needs an answer.
              Titles side by side - two breakdowns of the same process
              cannot be diffed line by line, the wording changes wholesale. */}
          {session.status === "ready" && steps.length > 0 && (
            <details data-testid="coverage-draft-preview">
              <summary className="cursor-pointer list-none text-sm text-primary underline-offset-4 hover:underline">
                {t("draftPreviewOpen", { from: steps.length, to: draftedCount })}
              </summary>
              <div className="mt-3 grid gap-4 sm:grid-cols-2">
                <DraftColumn
                  title={t("draftCurrent", { count: steps.length })}
                  titles={steps.map((s) => s.title)}
                  testId="coverage-draft-current"
                />
                <DraftColumn
                  title={t("draftProposed", { count: draftedCount })}
                  titles={(session.payload?.steps ?? []).map((s) => s.title)}
                  testId="coverage-draft-proposed"
                />
              </div>
            </details>
          )}
        </div>
      )}

      <Tabs defaultValue="coverage">
        <TabsList>
          <TabsTrigger value="coverage" data-testid="coverage-tab-coverage">
            {t("tabCoverage")}
          </TabsTrigger>
          <TabsTrigger value="steps" data-testid="coverage-tab-steps">
            {t("tabSteps")}
          </TabsTrigger>
          <TabsTrigger value="gaps" data-testid="coverage-tab-gaps">
            {t("tabGaps")}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="coverage" className="pt-4">
          <CoverageTab
            key={appliedCount}
            containerId={id}
            steps={steps}
            primitives={primitives}
            canEdit={canEdit}
            canOpenHireNeed={canEdit && canManageSection && canRecruit}
            canRegisterAgent={canEdit && canManageSection}
            onStepsChanged={setSteps}
          />
        </TabsContent>

        <TabsContent value="steps" className="space-y-4 pt-4">
          {steps.length === 0 && !showBanner ? (
            <div className="rounded-lg border border-dashed p-8 text-center" data-testid="coverage-steps-empty">
              <p className="font-medium">{t("noStepsTitle")}</p>
              <p className="mt-1 text-sm text-muted-foreground">
                {container.description ? t("noStepsText") : t("noStepsNoDescription")}
              </p>
            </div>
          ) : null}

          <StepsEditor
            containerId={id}
            steps={steps}
            primitives={primitives}
            canEdit={canEdit}
            canAccept={canAccept}
            onStepsChange={setSteps}
            onAccepted={load}
          />
        </TabsContent>

        <TabsContent value="gaps" className="pt-4">
          <GapsTab
            containerId={id}
            primitives={primitives}
            canEdit={canEdit}
            canOpenHireNeed={canEdit && canManageSection && canRecruit}
            canRegisterAgent={canEdit && canManageSection}
            onStepsChanged={setSteps}
          />
        </TabsContent>
      </Tabs>

      {editing && (
        <EditContainerDialog
          container={container}
          t={t}
          onClose={() => setEditing(false)}
          onSaved={(updated) => {
            setContainer(updated);
            setEditing(false);
          }}
        />
      )}

      {accessOpen && (
        <AccessDialog
          containerId={container.id}
          canChangeOwner={container.my_access === "manage"}
          onClose={() => setAccessOpen(false)}
          onOwnerChanged={load}
        />
      )}

      <ConfirmDialog
        open={confirmReplace}
        onOpenChange={setConfirmReplace}
        title={t("regenerateSteps")}
        description={t("regenerateConfirm", { count: steps.length })}
        onConfirm={generate}
        confirmLabel={t("generateSteps")}
        confirmVariant="default"
      />

      <ConfirmDialog
        open={confirmForceApply}
        onOpenChange={setConfirmForceApply}
        title={t("applyForceTitle")}
        description={t("applyForceText")}
        onConfirm={() => void applyGeneration(true)}
        loading={busy}
        confirmLabel={t("applyGeneration")}
        confirmTestId="coverage-apply-force-confirm"
        cancelTestId="coverage-apply-force-cancel"
      />

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={t("deleteContainer")}
        description={t("deleteContainerConfirm", { title: container.title })}
        onConfirm={() => void deleteContainer()}
        loading={busy}
        confirmTestId="coverage-btn-delete-confirm"
      />
    </div>
  );
}

function DraftColumn({
  title,
  titles,
  testId,
}: {
  title: string;
  titles: string[];
  testId: string;
}) {
  return (
    <div data-testid={testId}>
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      <ol className="mt-1 space-y-0.5 text-sm">
        {titles.map((step, i) => (
          <li key={`${i}-${step}`} className="flex gap-2">
            <span className="w-5 shrink-0 tabular-nums text-muted-foreground">{i + 1}</span>
            <span>{step}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function EditContainerDialog({
  container,
  t,
  onClose,
  onSaved,
}: {
  container: WorkContainer;
  t: (key: string) => string;
  onClose: () => void;
  onSaved: (container: WorkContainer) => void;
}) {
  const [title, setTitle] = useState(container.title);
  const [description, setDescription] = useState(container.description ?? "");
  const [goal, setGoal] = useState(container.goal ?? "");
  const [saving, setSaving] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setSaving(true);
    try {
      onSaved(
        await workApi.updateContainer(container.id, {
          title: title.trim(),
          description: description.trim() || null,
          goal: goal.trim() || null,
        }),
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="coverage-modal-edit">
        <form onSubmit={save} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{t("editContainer")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="coverage-edit-title">{t("fieldTitle")}</Label>
            <Input
              id="coverage-edit-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={300}
              required
              data-testid="coverage-edit-input-title"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="coverage-edit-description">{t("fieldDescription")}</Label>
            <Textarea
              id="coverage-edit-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={6}
              data-testid="coverage-edit-textarea-description"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="coverage-edit-goal">{t("fieldGoal")}</Label>
            <Textarea
              id="coverage-edit-goal"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              rows={2}
              data-testid="coverage-edit-textarea-goal"
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={saving || !title.trim()} data-testid="coverage-btn-edit-save">
              {t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
