"use client";

// HRP-759 / W6 (§5.10): the To do tab of a work container — everything
// unclosed, in two sections. "Nobody does this" keeps the hire / agency
// label and the handoff of a selection to Recruitment as one draft
// vacancy; "an agent could, nobody has" is the work that is coverable on
// paper but where the company has registered no agent and written no
// skill file. The link back to a vacancy comes from work_hire_needs,
// never from the vacancy itself. A gap can also be closed by naming the
// person who does it (HRP-809), skills or not.

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Briefcase, ExternalLink, FileText, Sparkles, UserRound } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { LoadErrorState } from "@/components/load-error-state";
import { AssignPersonDialog } from "@/components/coverage/assign-person-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { RegisterAgentInline } from "@/components/coverage/register-agent-inline";
import { SkillDialog } from "@/components/coverage/skill-dialog";
import { BADGE_COLOR } from "@/lib/badge-tones";
import { EECreditCostBadge } from "@/lib/ee-hooks";
import { useCostConfirmation } from "@/hooks/use-cost-confirmation";
import { ApiError } from "@/lib/api";
import {
  type AutomationMode,
  type Gap,
  type GapLabel,
  type Primitive,
  SKILL_ACTION,
  type WorkStep,
  workApi,
} from "@/lib/api/work";

const GAP_LABELS: GapLabel[] = ["hire", "agency"];

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

interface GapsTabProps {
  containerId: string;
  primitives: Primitive[];
  canEdit: boolean;
  canOpenHireNeed: boolean;
  /** HRP-810: the agent registry is the section's roles', not the owner's. */
  canRegisterAgent: boolean;
  /** The label lives on the step: keep the Steps tab's copy in sync. */
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
      // Only the "nobody does this" rows are selectable: a step that moved
      // to the other section must leave the selection, not keep the button
      // counting it while the handoff would send an empty list.
      setSelected(
        (prev) =>
          new Set(
            [...prev].filter((id) =>
              fresh.some((g) => g.kind === "no_owner" && g.step_id === id),
            ),
          ),
      );
    } catch {
      setFailed(true);
    }
  }, [containerId]);

  useEffect(() => {
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

  // One hire need carries one label, so a selection that mixes "hire" and
  // "agency" has no right answer: the button waits rather than picking one
  // and sending the work somewhere the company did not ask for.
  const mixedLabels =
    new Set(noOwner.filter((g) => selected.has(g.step_id)).map((g) => g.gap_label ?? "hire"))
      .size > 1;

  function toggle(stepId: string, checked: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(stepId);
      else next.delete(stepId);
      return next;
    });
  }

  async function setLabel(gap: Gap, label: GapLabel) {
    try {
      const step = await workApi.updateStep(gap.step_id, { gap_label: label });
      setGaps((prev) => prev?.map((g) => (g.step_id === gap.step_id ? { ...g, gap_label: label } : g)) ?? prev);
      onStepsChanged((prev) => prev.map((s) => (s.id === step.id ? step : s)));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    }
  }

  async function openHireNeed() {
    if (selected.size === 0 || mixedLabels) return;
    const chosen = noOwner.filter((g) => selected.has(g.step_id));
    // One need, one label - and the selection is never mixed (see above).
    const label: GapLabel = chosen.every((g) => g.gap_label === "agency") ? "agency" : "hire";
    setBusy(true);
    try {
      await workApi.createHireNeed(containerId, {
        step_ids: chosen.map((g) => g.step_id),
        label,
        // Nothing to search for inside when the work goes to a provider.
        internal_search_allowed: label === "hire",
      });
      setSelected(new Set());
      await load();
      toast.success(t("hireNeedCreated"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setBusy(false);
    }
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
    // is collected and the loop goes on. Out of credits (402) is the
    // exception: every request after it is a guaranteed refusal.
    for (const gap of pendingSkills) {
      attempted += 1;
      try {
        await workApi.generateSkill(gap.step_id);
        queued += 1;
      } catch (err) {
        refused += 1;
        lastError = err instanceof Error ? err.message : t("saveFailed");
        if (err instanceof ApiError && err.status === 402) break;
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
              <div className="flex flex-col items-end gap-1">
                <Button
                  onClick={openHireNeed}
                  disabled={busy || selected.size === 0 || mixedLabels}
                  data-testid="coverage-gap-btn-hire-need"
                >
                  <Briefcase className="size-4" />
                  {t("openHireNeed", { count: selected.size })}
                </Button>
                {mixedLabels && (
                  <p
                    className="max-w-64 text-right text-xs text-muted-foreground"
                    data-testid="coverage-gap-mixed-labels"
                  >
                    {t("mixedGapLabelsHint")}
                  </p>
                )}
              </div>
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
                      {gap.hire_need?.vacancy_id && (
                        <Link
                          href={`/recruitment/requisitions/${gap.hire_need.vacancy_id}`}
                          className="inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline"
                          data-testid={`${testId}-link-vacancy`}
                        >
                          <ExternalLink className="size-3.5" />
                          {t("openVacancy")}
                        </Link>
                      )}
                    </div>
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
                    <Select
                      value={gap.gap_label ?? "hire"}
                      onValueChange={(value) => void setLabel(gap, value as GapLabel)}
                      disabled={!canEdit}
                    >
                      <SelectTrigger
                        className="w-32"
                        aria-label={t("gapLabelAria")}
                        title={canEdit ? undefined : t("gapLabelReadOnlyHint")}
                        data-testid={`${testId}-select-label`}
                      >
                        <SelectValue>{t(`gapLabel_${gap.gap_label ?? "hire"}`)}</SelectValue>
                      </SelectTrigger>
                      <SelectContent>
                        {GAP_LABELS.map((label) => (
                          <SelectItem key={label} value={label} data-testid={`${testId}-select-label-${label}`}>
                            {t(`gapLabel_${label}`)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
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
              <h2 className="font-medium">{t("todoNotAutomatedTitle")}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{t("todoNotAutomatedHint")}</p>
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
