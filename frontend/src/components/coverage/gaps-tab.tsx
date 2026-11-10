"use client";

// HRP-759 / W6 (§5.10): the To do tab of a work container — everything
// unclosed, in two sections. "Nobody does this" hands one step or a
// selection to Recruitment as one draft vacancy, through the same window
// the Coverage row opens (HRP-801, QA 23.10 e: the route - inside first,
// outside, agency - is chosen there, not on a label per row); "work for an
// agent" is the work an agent type covers where
// something is still missing: `gap_kind` keeps a step here while no agent
// is registered OR its skill file is not ready, so a step whose agent the
// company already registered stays until the instruction is written
// (HRP-859: the skill file is what makes a client's own agent do the step
// the way this breakdown describes it). The link back to a vacancy comes from work_hire_needs,
// never from the vacancy itself. A gap can also be closed by naming the
// person who does it (HRP-809), skills or not.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Briefcase, FileText, Sparkles, UserRound } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { LoadErrorState } from "@/components/load-error-state";
import { AssignPersonDialog } from "@/components/coverage/assign-person-dialog";
import { HireFromStepDialog } from "@/components/coverage/hire-from-step-dialog";
import { RegisterAgentInline } from "@/components/coverage/register-agent-inline";
import { VacancyLink } from "@/components/coverage/row-links";
import { SkillDialog } from "@/components/coverage/skill-dialog";
import { BADGE_COLOR } from "@/lib/badge-tones";
import { EECreditCostBadge } from "@/lib/ee-hooks";
import { useCostConfirmation } from "@/hooks/use-cost-confirmation";
import { ApiError, isCreditLimitResponse } from "@/lib/api";
import {
  type AutomationMode,
  type Gap,
  type Primitive,
  SKILL_ACTION,
  type WorkStep,
  workApi,
} from "@/lib/api/work";

/** A capability's name in the interface language; the code never reaches
 * the screen unless the catalog does not know it. */
export function useCapabilityLabel(primitives: Primitive[]): (code: string) => string {
  const tRef = useTranslations("reference");
  return useMemo(() => {
    const byCode = new Map(primitives.map((p) => [p.code, p.i18n_key]));
    return (code: string) => {
      const key = byCode.get(code);
      return key ? tRef(`primitive.${key}.label`) : code;
    };
  }, [primitives, tRef]);
}

export const MODE_COLOR: Record<AutomationMode, string> = {
  automatable: BADGE_COLOR.green,
  draft_then_review: BADGE_COLOR.blue,
  review_required: BADGE_COLOR.amber,
  blocked_judgment: BADGE_COLOR.neutral,
  blocked_physical: BADGE_COLOR.neutral,
};

/** A row the hire window may still take: nobody does it and no vacancy
 * carries it yet. */
function hireable(gap: Gap): boolean {
  return gap.kind === "no_owner" && !gap.hire_need?.vacancy_id;
}

interface GapsTabProps {
  containerId: string;
  primitives: Primitive[];
  canEdit: boolean;
  canOpenHireNeed: boolean;
  /** HRP-810: the agent registry is the section's roles', not the owner's. */
  canRegisterAgent: boolean;
  /** An assignment changes the step: keep the Steps tab's copy in sync. */
  onStepsChanged: (updater: (prev: WorkStep[]) => WorkStep[]) => void;
}

export function GapsTab({
  containerId,
  primitives,
  canEdit,
  canOpenHireNeed,
  canRegisterAgent,
  onStepsChanged,
}: GapsTabProps) {
  const t = useTranslations("coverage");
  const tc = useTranslations("common");
  const [gaps, setGaps] = useState<Gap[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [skillStep, setSkillStep] = useState<Gap | null>(null);
  const [assignStep, setAssignStep] = useState<Gap | null>(null);
  // HRP-801: the rows the hire window is open for - one, or the selection.
  const [hireSteps, setHireSteps] = useState<Gap[] | null>(null);
  const [confirmBulk, setConfirmBulk] = useState(false);
  // The unit price, so the bulk confirmation can name the total rather
  // than let the company find out after N charges (§9).
  const { cost } = useCostConfirmation(SKILL_ACTION);
  const labelOf = useCapabilityLabel(primitives);

  const load = useCallback(async () => {
    try {
      const fresh = await workApi.listGaps(containerId);
      setGaps(fresh);
      setFailed(false);
      // Only the "nobody does this" rows not handed over yet are
      // selectable: a step that moved to the other section, or got its
      // vacancy, must leave the selection, not keep the button counting it
      // while the handoff would be refused.
      setSelected(
        (prev) =>
          new Set([...prev].filter((id) => fresh.some((g) => g.step_id === id && hireable(g)))),
      );
    } catch {
      setFailed(true);
    }
  }, [containerId]);

  useEffect(() => {
    // The state writes happen after the await, not in the effect body;
    // the rule cannot see through the async boundary (as on coverage-tab).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const noOwner = useMemo(() => gaps?.filter((g) => g.kind === "no_owner") ?? [], [gaps]);
  const notAutomated = useMemo(
    () => gaps?.filter((g) => g.kind === "not_automated_yet") ?? [],
    [gaps],
  );
  // "generating" is excluded as well as "ready": start_step_skill answers 409
  // for those, so counting them over-quotes the bulk cost and the loop spends
  // its requests on guaranteed refusals.
  const pendingSkills = notAutomated.filter(
    (g) => g.skill_status !== "ready" && g.skill_status !== "generating",
  );

  function toggle(stepId: string, checked: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(stepId);
      else next.delete(stepId);
      return next;
    });
  }

  async function generateAll() {
    setConfirmBulk(false);
    setBusy(true);
    let queued = 0;
    let attempted = 0;
    let refused = 0;
    let lastError: string | null = null;
    // Each POST only queues a task. One row the server refuses - a step
    // already generating, or one an agent of the tenant matched but the
    // catalog blocks - must not abandon the rows behind it, so the failure
    // is collected and the loop goes on. Out of credits is the exception -
    // 402, or the demo sandbox's 429 quota (HRP-1172): every request after
    // it is a guaranteed refusal.
    for (const gap of pendingSkills) {
      attempted += 1;
      try {
        await workApi.generateSkill(gap.step_id);
        queued += 1;
      } catch (err) {
        refused += 1;
        lastError = err instanceof Error ? err.message : t("saveFailed");
        if (err instanceof ApiError && isCreditLimitResponse(err.status, { code: err.code })) break;
      }
    }
    if (queued > 0) toast.success(t("bulkSkillQueued", { count: queued }));
    // One toast for the whole run: ten refusals used to be one message,
    // the last one, with no hint that the other nine happened at all.
    if (refused > 0) {
      toast.error(
        t("bulkSkillFailed", {
          failed: refused,
          total: attempted,
          reason: lastError ?? t("saveFailed"),
        }),
      );
    }
    await load();
    setBusy(false);
  }

  if (failed) {
    return <LoadErrorState onRetry={load} testIdPrefix="coverage-gaps" />;
  }
  if (gaps === null) {
    return <div className="py-12 text-center text-muted-foreground">{tc("loading")}</div>;
  }

  if (gaps.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center" data-testid="coverage-gaps-empty">
        <p className="font-medium">{t("gapsEmptyTitle")}</p>
        <p className="mt-1 text-sm text-muted-foreground">{t("gapsEmptyText")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {noOwner.length > 0 && (
        <section className="space-y-4" data-testid="coverage-todo-no-owner">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="max-w-2xl">
              <h2 className="font-medium">{t("todoNoOwnerTitle")}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{t("gapsHint")}</p>
            </div>
            {canOpenHireNeed && (
              <Button
                onClick={() => setHireSteps(noOwner.filter((g) => selected.has(g.step_id)))}
                disabled={busy || selected.size === 0}
                data-testid="coverage-gap-btn-hire-need"
              >
                <Briefcase className="size-4" />
                {t("openHireNeed", { count: selected.size })}
              </Button>
            )}
          </div>

          <ol className="space-y-3" data-testid="coverage-gaps-list">
            {noOwner.map((gap) => {
              const testId = `coverage-gap-row-${gap.step_id}`;
              return (
                <li key={gap.step_id} data-testid={testId} className="rounded-lg border bg-background p-3">
                  <div className="flex items-start gap-3">
                    {canOpenHireNeed && (
                      <Checkbox
                        className="mt-1"
                        checked={selected.has(gap.step_id)}
                        // Handed over already: a second need is refused.
                        disabled={!hireable(gap)}
                        title={hireable(gap) ? undefined : t("gapHandedOverHint")}
                        onCheckedChange={(checked) => toggle(gap.step_id, checked === true)}
                        aria-label={t("selectGapAria", { title: gap.title })}
                        data-testid={`${testId}-checkbox`}
                      />
                    )}
                    <span className="mt-0.5 w-6 shrink-0 text-sm tabular-nums text-muted-foreground">
                      {gap.position}
                    </span>
                    <div className="flex-1 space-y-2">
                      <GapHeadline gap={gap} testId={testId} t={t} />
                      <Capabilities gap={gap} testId={testId} labelOf={labelOf} />
                    </div>
                    {/* HRP-801 (QA 23.10, e): the row's way out on the
                        right, as on the Coverage row - the vacancy it was
                        handed to, or the window that hands it over. */}
                    <div className="flex shrink-0 flex-wrap items-center justify-end gap-3">
                      {gap.hire_need?.vacancy_id ? (
                        <VacancyLink
                          need={gap.hire_need}
                          label={t(gap.hire_need.label === "agency" ? "goToVacancyAgency" : "goToVacancy")}
                          testId={`${testId}-link-vacancy`}
                        />
                      ) : (
                        canOpenHireNeed && (
                          <Button
                            size="sm"
                            variant="link"
                            className="h-auto p-0"
                            onClick={() => setHireSteps([gap])}
                            data-testid={`${testId}-btn-hire`}
                          >
                            {t("openHireNeedOne")}
                          </Button>
                        )
                      )}
                      {canEdit && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setAssignStep(gap)}
                          data-testid={`${testId}-btn-assign`}
                        >
                          <UserRound className="size-4" />
                          {t("assignExecutor")}
                        </Button>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      )}

      {notAutomated.length > 0 && (
        <section className="space-y-4" data-testid="coverage-todo-not-automated">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="max-w-2xl">
              <h2 className="font-medium">{t("todoAgentTitle")}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{t("todoAgentHint")}</p>
            </div>
            {canEdit && pendingSkills.length > 0 && (
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => setConfirmBulk(true)}
                data-testid="coverage-btn-generate-all-skills"
              >
                <Sparkles className="size-4" />
                {t("bulkSkillGenerate", { count: pendingSkills.length })}
              </Button>
            )}
          </div>

          <ol className="space-y-3" data-testid="coverage-todo-list">
            {notAutomated.map((gap) => {
              const testId = `coverage-todo-row-${gap.step_id}`;
              return (
                <li key={gap.step_id} data-testid={testId} className="rounded-lg border bg-background p-3">
                  <div className="flex items-start gap-3">
                    <span className="mt-0.5 w-6 shrink-0 text-sm tabular-nums text-muted-foreground">
                      {gap.position}
                    </span>
                    <div className="flex-1 space-y-2">
                      <GapHeadline gap={gap} testId={testId} t={t} />
                      <Capabilities gap={gap} testId={testId} labelOf={labelOf} />
                      {canRegisterAgent && gap.agent?.pack_id && !gap.agent.agent_id && (
                        <RegisterAgentInline
                          packId={gap.agent.pack_id}
                          testId={`${testId}-btn-use-agent`}
                          onRegistered={load}
                        />
                      )}
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <Button
                        size="sm"
                        variant={gap.skill_status === "ready" ? "outline" : "default"}
                        disabled={gap.skill_status === "generating" || (!canEdit && gap.skill_status !== "ready")}
                        title={!canEdit && gap.skill_status !== "ready" ? t("skillReadOnlyHint") : undefined}
                        onClick={() => setSkillStep(gap)}
                        data-testid={`${testId}-btn-skill`}
                      >
                        <FileText className="size-4" />
                        {gap.skill_status === "ready" ? t("openSkill") : t("getSkill")}
                        {gap.skill_status !== "ready" && canEdit && (
                          <EECreditCostBadge action={SKILL_ACTION} />
                        )}
                      </Button>
                      <span
                        className="text-xs text-muted-foreground"
                        data-testid={`${testId}-skill-status`}
                        data-status={gap.skill_status}
                      >
                        {t(`skillStatus_${gap.skill_status}`)}
                      </span>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      )}

      {assignStep && (
        <AssignPersonDialog
          containerId={containerId}
          stepId={assignStep.step_id}
          field="executor_employee_id"
          // A gap has no active executor; a terminated one is replaced.
          currentId={null}
          onClose={() => setAssignStep(null)}
          onSaved={(step) => {
            // The step is covered now: it leaves this list.
            onStepsChanged((prev) => prev.map((s) => (s.id === step.id ? step : s)));
            void load();
          }}
        />
      )}

      {hireSteps && (
        <HireFromStepDialog
          containerId={containerId}
          steps={hireSteps.map((g) => ({ id: g.step_id, title: g.title }))}
          onClose={() => setHireSteps(null)}
          onCreated={() => {
            setSelected(new Set());
            void load();
          }}
        />
      )}

      {skillStep && (
        <SkillDialog
          // The one-generation-per-open ref inside is only correct while
          // each step gets its own instance.
          key={skillStep.step_id}
          step={skillStep}
          canEdit={canEdit}
          onClose={() => setSkillStep(null)}
          onChanged={load}
        />
      )}

      <ConfirmDialog
        open={confirmBulk}
        onOpenChange={setConfirmBulk}
        title={t("bulkSkillGenerate", { count: pendingSkills.length })}
        description={
          cost === null
            ? t("bulkSkillConfirm", { count: pendingSkills.length })
            : t("bulkSkillConfirmCost", {
                count: pendingSkills.length,
                total: cost * pendingSkills.length,
              })
        }
        onConfirm={generateAll}
        confirmLabel={t("getSkill")}
        confirmVariant="default"
      />
    </div>
  );
}

function GapHeadline({
  gap,
  testId,
  t,
}: {
  gap: Gap;
  testId: string;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <p className="font-medium" data-testid={`${testId}-title`}>
        {gap.title}
      </p>
      {gap.mode && (
        <Badge className={MODE_COLOR[gap.mode]} data-testid={`${testId}-mode`}>
          {t(`mode_${gap.mode}`)}
        </Badge>
      )}
    </div>
  );
}

function Capabilities({
  gap,
  testId,
  labelOf,
}: {
  gap: Gap;
  testId: string;
  labelOf: (code: string) => string;
}) {
  if (gap.required_codes.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1" data-testid={`${testId}-capabilities`}>
      {gap.required_codes.map((code) => (
        <Badge key={code} variant="outline" data-testid={`${testId}-capability-${code}`}>
          {labelOf(code)}
        </Badge>
      ))}
    </div>
  );
}
