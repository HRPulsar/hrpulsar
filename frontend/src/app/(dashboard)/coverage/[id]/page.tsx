"use client";

// HRP-756: one work container — a process or a project — with its
// breakdown into steps (Steps tab) and, per step, who covers it (Coverage
// tab, HRP-760) and what nobody covers yet (Gaps tab, HRP-759).

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { ChevronDown, ChevronRight, ChevronUp, Signpost, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LoadErrorState } from "@/components/load-error-state";
import { useSectionTab } from "@/components/section-tabs";
import { ContainerActions } from "@/components/coverage/container-actions";
import { CoverageTab } from "@/components/coverage/coverage-tab";
import { GapsTab } from "@/components/coverage/gaps-tab";
import { generationErrorText } from "@/components/coverage/generation-errors";
import { GenerationProgress } from "@/components/coverage/generation-progress";
import { StepsEditor } from "@/components/coverage/steps-editor";
import { useSkillWatch } from "@/components/coverage/use-skill-watch";
import {
  WhatNextDialog,
  markWhatNextShown,
  whatNextShown,
  whenDemoIsClear,
} from "@/components/coverage/what-next-dialog";
import { useAuth } from "@/context/auth-context";
import { usePermissions } from "@/hooks/use-permissions";
import { BADGE_COLOR } from "@/lib/badge-tones";
import { trimLongText } from "@/lib/long-text";
import { cn, newClientId } from "@/lib/utils";
import { EECreditCostBadge } from "@/lib/ee-hooks";
import { ApiError } from "@/lib/api";
import {
  APPLY_WOULD_DISCARD,
  type Coverage,
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

/** The first one is what a bare address opens. */
const TABS = ["coverage", "steps", "gaps"] as const;

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
  // The open tab rides in `?tab=`, as on the section lists, so a link can
  // open one: the demo route's "Go" leads to To do (HRP-1234).
  const tab = useSectionTab(TABS);
  // HRP-830: a hire need drafts a vacancy - `manage` on recruitment.
  const canRunHiring = usePermissions().canManageSection("recruitment");
  // HRP-1192: one poll for the skills being written, whichever tab is open.
  const skillWatch = useSkillWatch();

  const [container, setContainer] = useState<WorkContainer | null>(null);
  const [steps, setSteps] = useState<WorkStep[]>([]);
  const [primitives, setPrimitives] = useState<Primitive[]>([]);
  const [session, setSession] = useState<DecompositionSession | null>(null);
  const [failed, setFailed] = useState(false);
  // HRP-853: a 404 - hidden by the access rules or deleted - is "not found",
  // not a failure worth a retry.
  const [notFound, setNotFound] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmReplace, setConfirmReplace] = useState(false);
  // M3: the apply came back 409 - the draft would throw away steps that
  // carry a generated skill or the company's edits.
  const [confirmForceApply, setConfirmForceApply] = useState(false);
  // The Coverage tab is mounted by default and loads /coverage once: an
  // apply replaces the steps under it, so remount it to refetch.
  const [appliedCount, setAppliedCount] = useState(0);
  // One key per session: a retried Apply must not create the steps twice.
  const applyKeys = useRef<Map<string, string>>(new Map());
  // W6 (§5.5): the first generation applies itself, once per session.
  const autoApplied = useRef<string | null>(null);
  // HRP-1205: "What's next" reads what the Coverage tab last loaded. In a
  // demo sandbox it also opens by itself, once per process, when a breakdown
  // finishes in front of the visitor: a run seen in flight on this page,
  // then applied, then its coverage computed - never on opening a process
  // that was broken down before.
  const isDemo = !!useAuth().user?.tenant_is_demo;
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [whatNextOpen, setWhatNextOpen] = useState(false);
  const [whatNextDue, setWhatNextDue] = useState(false);
  const runSeen = useRef(false);
  const finishedLive = useRef(false);
  // HRP-1206: "To do (N)" - the rows the tab lists, known on opening the page
  // from the coverage the Coverage tab loads, then from every load of the tab
  // itself after an action there. Null until either arrives.
  const [todoCount, setTodoCount] = useState<number | null>(null);
  const onCoverage = useCallback(
    (fresh: Coverage) => {
      setCoverage(fresh);
      setTodoCount(fresh.steps.filter((s) => s.todo).length);
      if (!finishedLive.current || fresh.mapping_pending) return;
      finishedLive.current = false;
      if (isDemo && !whatNextShown(id)) setWhatNextDue(true);
    },
    [id, isDemo],
  );
  // The Coverage tab is unmounted while another tab is open: what changes
  // there (steps edited, people confirmed on To do) reaches the count and
  // "What's next" only through a fetch of its own.
  const refreshCoverage = useCallback(
    () => workApi.getCoverage(id).then(onCoverage).catch(() => undefined),
    [id, onCoverage],
  );
  // Opened straight on another tab (`?tab=`), so is the page itself: the
  // Coverage tab has not loaded the count and "What's next" for it.
  const openedOn = useRef(tab);
  useEffect(() => {
    if (openedOn.current !== TABS[0]) void refreshCoverage();
  }, [refreshCoverage]);
  useEffect(() => {
    if (!whatNextDue) return;
    return whenDemoIsClear(() => {
      markWhatNextShown(id);
      setWhatNextDue(false);
      setWhatNextOpen(true);
    });
  }, [whatNextDue, id]);

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
      setNotFound(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setNotFound(true);
      else setFailed(true);
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
    if (isSessionRunning(session)) runSeen.current = true;
  }, [session]);
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
      finishedLive.current = runSeen.current;
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

  if (notFound) {
    return (
      <div
        className="rounded-lg border border-dashed p-12 text-center text-muted-foreground"
        data-testid="coverage-detail-not-found"
      >
        <p>{t("notFound")}</p>
        <Link
          href="/coverage"
          className={`${buttonVariants({ variant: "outline", size: "sm" })} mt-4`}
          data-testid="coverage-detail-not-found-link"
        >
          {t("backToList")}
        </Link>
      </div>
    );
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
          {coverage?.steps.some((s) => s.in_scope) && (
            // HRP-1182 (QA 20.11): filled, like the other buttons that matter.
            <Button
              size="sm"
              onClick={() => void refreshCoverage().then(() => setWhatNextOpen(true))}
              data-testid="coverage-btn-what-next"
            >
              <Signpost className="size-4" />
              {t("whatNextButton")}
            </Button>
          )}
          {/* HRP-1228: Edit, Access, Archive and Delete, behind a kebab on
              the right - as on a vacancy. */}
          <div className="ml-auto">
            <ContainerActions
              container={container}
              testIdPrefix="coverage-btn"
              // A run in flight kept Archive and Delete off before, too.
              disabled={busy}
              onChanged={(updated) => (updated ? setContainer(updated) : void load())}
              onDeleted={() => router.push("/coverage")}
              onBusyChange={setBusy}
            />
          </div>
        </div>
        {/* HRP-1229: the goal and the description side by side, the goal
            first; a long one folds, as on a vacancy. */}
        {(container.goal || container.description) && (
          <div
            className={cn(
              "grid gap-3",
              container.goal && container.description && "sm:grid-cols-2",
            )}
          >
            {container.goal && (
              <LongText testId="coverage-detail-goal" title={t("goalTitle")} text={container.goal} />
            )}
            {container.description && (
              <LongText
                testId="coverage-detail-description"
                title={t("fieldDescription")}
                text={container.description}
              />
            )}
          </div>
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
                  {generationErrorText(
                    t,
                    session.error_code,
                    session.error_message,
                    "generationFailed",
                  )}
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
            <details className="group" data-testid="coverage-draft-preview">
              {/* HRP-949 REDO: the chevron says the line opens, as on the
                  step details (HRP-904). */}
              <summary className="flex w-fit cursor-pointer list-none items-center gap-1 text-sm text-primary underline-offset-4 hover:underline [&::-webkit-details-marker]:hidden">
                <ChevronRight
                  aria-hidden="true"
                  className="size-4 shrink-0 transition-transform group-open:rotate-90"
                  data-testid="coverage-draft-preview-chevron"
                />
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

      <Tabs
        defaultValue={TABS[0]}
        value={tab}
        // The History API, not the router: all three tabs are on the page
        // already, and a switch must not wait for the server.
        onValueChange={(next) => window.history.replaceState(null, "", `?tab=${next}`)}
      >
        <TabsList>
          <TabsTrigger value="coverage" data-testid="coverage-tab-coverage">
            {t("tabCoverage")}
          </TabsTrigger>
          <TabsTrigger value="steps" data-testid="coverage-tab-steps">
            {t("tabStepsCount", { count: steps.length })}
          </TabsTrigger>
          <TabsTrigger value="gaps" data-testid="coverage-tab-gaps" data-count={todoCount ?? undefined}>
            {todoCount === null ? t("tabGaps") : t("tabGapsCount", { count: todoCount })}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="coverage" className="pt-4">
          <CoverageTab
            key={appliedCount}
            containerId={id}
            skillWatch={skillWatch}
            steps={steps}
            primitives={primitives}
            canEdit={canEdit}
            canOpenHireNeed={canEdit && canManageSection && canRunHiring}
            canRegisterAgent={canEdit && canManageSection}
            onStepsChanged={setSteps}
            onCoverage={onCoverage}
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
            onStepsChange={(update) => {
              setSteps(update);
              void refreshCoverage();
            }}
            onAccepted={() => {
              void load();
              void refreshCoverage();
            }}
          />
        </TabsContent>

        <TabsContent value="gaps" className="pt-4">
          <GapsTab
            key={appliedCount}
            containerId={id}
            skillWatch={skillWatch}
            primitives={primitives}
            canEdit={canEdit}
            canOpenHireNeed={canEdit && canManageSection && canRunHiring}
            canRegisterAgent={canEdit && canManageSection}
            onStepsChanged={setSteps}
            onLoaded={setTodoCount}
          />
        </TabsContent>
      </Tabs>

      {whatNextOpen && coverage && (
        <WhatNextDialog steps={coverage.steps} onClose={() => setWhatNextOpen(false)} />
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
    </div>
  );
}

/** How many lines of a folded text show: a description pasted as a list is
 * short in characters and long on the screen. */
const FOLDED_LINES = 4;

/** A text of the process in its own card (HRP-1229): a long one shows its
 * beginning and unfolds - the vacancy's own limit and wording, plus a limit
 * on lines, since this text keeps its line breaks. */
function LongText({ testId, title, text }: { testId: string; title: string; text: string }) {
  const t = useTranslations("coverage");
  const [expanded, setExpanded] = useState(false);
  const trimmed = trimLongText(text, expanded);
  const lines = trimmed.visible.split("\n");
  const tall = text.split("\n").length > FOLDED_LINES;
  const isLong = trimmed.isLong || tall;
  const visible =
    expanded || lines.length <= FOLDED_LINES
      ? trimmed.visible
      : `${lines.slice(0, FOLDED_LINES).join("\n")}…`;
  return (
    <div className="rounded-md bg-muted/50 p-3" data-testid={testId}>
      <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide">{title}</h2>
      <p className="whitespace-pre-line break-words text-sm text-muted-foreground">{visible}</p>
      {isLong && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="mt-2 inline-flex items-center gap-1 text-sm text-primary hover:underline"
          data-testid={`${testId}-toggle`}
        >
          {expanded ? t("showLess") : t("showMore")}
          {expanded ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
        </button>
      )}
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
