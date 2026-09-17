"use client";

// HRP-760: the Coverage tab of a work container — per step who covers it
// (an agent type, a person, nobody) and how far it can move to an agent,
// the three shares as yearly hours, the hours editor of the candidate
// steps, the SKILL.md of a step, and the inline "I already use this" that registers
// an agent for the matched pack. The word "primitive" never reaches the
// screen.

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Bot, ExternalLink, FileText, Scale, ShieldCheck, User, UserRound } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { LoadErrorState } from "@/components/load-error-state";
import { type AssigneeField, AssignPersonDialog } from "@/components/coverage/assign-person-dialog";
import { MODE_COLOR, useCapabilityLabel } from "@/components/coverage/gaps-tab";
import { CoverageSummary, QUALITY_BADGE } from "@/components/coverage/coverage-summary";
import { HireFromStepDialog } from "@/components/coverage/hire-from-step-dialog";
import {
  HOURS_PER_RUN_MIN,
  HoursFields,
  type HoursDraft,
  draftOf,
  hoursOutOfRange,
  parseHours,
} from "@/components/coverage/hours-fields";
import { RegisterAgentInline } from "@/components/coverage/register-agent-inline";
import { SkillDialog } from "@/components/coverage/skill-dialog";
import { BADGE_COLOR, BADGE_OUTLINE } from "@/lib/badge-tones";
import { EECreditCostBadge } from "@/lib/ee-hooks";
import {
  type Coverage,
  type CoverageStep,
  type Primitive,
  SKILL_ACTION,
  type AutomationMode,
  type Verdict,
  type WorkStep,
  HOURS_PER_RUN_MAX,
  RUNS_PER_YEAR_MAX,
  workApi,
} from "@/lib/api/work";

const MAPPING_POLL_MS = 10_000;
const MAPPING_POLL_LIMIT = 30;

// The modes in which an agent produces the work (coverage.CANDIDATE_MODES).
const CANDIDATE_MODES: AutomationMode[] = ["automatable", "draft_then_review", "review_required"];

const VERDICT_COLOR: Record<Verdict, string> = {
  agent: BADGE_COLOR.green,
  human: BADGE_COLOR.blue,
  gap: BADGE_COLOR.amber,
  out_of_scope: BADGE_COLOR.neutral,
};

type Translate = (key: string, values?: Record<string, string | number>) => string;

interface CoverageTabProps {
  containerId: string;
  steps: WorkStep[];
  primitives: Primitive[];
  canEdit: boolean;
  /** Recruitment viewer as well as a Coverage editor (§5.9). */
  canOpenHireNeed: boolean;
  /** HRP-810: the agent registry is the section's roles', not the owner's. */
  canRegisterAgent: boolean;
  onStepsChanged: (updater: (prev: WorkStep[]) => WorkStep[]) => void;
}

export function CoverageTab({
  containerId,
  steps,
  primitives,
  canEdit,
  canOpenHireNeed,
  canRegisterAgent,
  onStepsChanged,
}: CoverageTabProps) {
  const t = useTranslations("coverage");
  const tc = useTranslations("common");
  const tRef = useTranslations("reference");
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [failed, setFailed] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [skillStep, setSkillStep] = useState<CoverageStep | null>(null);
  const [hireStep, setHireStep] = useState<CoverageStep | null>(null);
  const [assign, setAssign] = useState<{ row: CoverageStep; field: AssigneeField } | null>(null);
  const packLabel = useCallback(
    (code: string | null) => {
      if (!code) return "";
      // A pack the interface catalog does not know yet reads as its code -
      // the way a capability does - never as a raw message path.
      const key = `agentPack.${code}.label`;
      return tRef.has(key) ? tRef(key) : code;
    },
    [tRef],
  );
  const capabilityLabel = useCapabilityLabel(primitives);

  const load = useCallback(async () => {
    try {
      const fresh = await workApi.getCoverage(containerId);
      setCoverage(fresh);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [containerId]);

  useEffect(() => {
    // The state writes happen after the await, not in the effect body;
    // the rule cannot see through the async boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  // The competence mapping runs in a worker: follow it by polling, bounded.
  // Once the budget is spent the tab no longer refreshes on its own, so the
  // banner that promises it must go.
  const mappingPending = coverage?.mapping_pending ?? false;
  const [pollExhausted, setPollExhausted] = useState(false);
  useEffect(() => {
    if (!mappingPending) return;
    let polls = 0;
    const timer = window.setInterval(() => {
      polls += 1;
      if (polls > MAPPING_POLL_LIMIT) {
        window.clearInterval(timer);
        setPollExhausted(true);
        return;
      }
      void load();
    }, MAPPING_POLL_MS);
    return () => {
      window.clearInterval(timer);
      // A new run gets a new budget, and its banner back.
      setPollExhausted(false);
    };
  }, [mappingPending, load]);

  const buckets = useMemo(() => {
    const rows = coverage?.steps.filter((s) => s.in_scope) ?? [];
    return {
      moves: rows.filter((s) => s.mode === "automatable"),
      to_review: rows.filter((s) => s.mode === "draft_then_review" || s.mode === "review_required"),
      stays: rows.filter((s) => s.mode === "blocked_judgment" || s.mode === "blocked_physical"),
    };
  }, [coverage]);

  if (failed) {
    return <LoadErrorState onRetry={load} testIdPrefix="coverage-coverage" />;
  }
  if (!coverage) {
    return <div className="py-12 text-center text-muted-foreground">{tc("loading")}</div>;
  }

  if (coverage.steps.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center" data-testid="coverage-coverage-empty">
        <p className="font-medium">{t("noStepsTitle")}</p>
        <p className="mt-1 text-sm text-muted-foreground">{t("coverageEmptyText")}</p>
      </div>
    );
  }

  const candidates = coverage.candidate_step_ids.length;
  const unestimated = coverage.steps.filter(
    (s) => coverage.candidate_step_ids.includes(s.step_id) && s.hours_per_year === null,
  ).length;
  const shares = coverage.shares;

  return (
    <div className="space-y-6">
      <p className="max-w-3xl text-sm text-muted-foreground">{t("coverageHint")}</p>

      {coverage.mapping_pending && !pollExhausted && (
        <div
          className="rounded-lg border bg-muted/40 p-3 text-sm"
          data-testid="coverage-mapping-pending"
        >
          {t("mappingPending")}
        </div>
      )}

      <CoverageSummary coverage={coverage} />

      <div className="grid gap-3 sm:grid-cols-3">
        <SummaryCard
          testId="coverage-summary-automatable"
          title={t("summaryMoves")}
          share={shares?.moves ?? null}
          rows={buckets.moves}
          t={t}
        />
        <SummaryCard
          testId="coverage-summary-draft"
          title={t("summaryToReview")}
          share={shares?.to_review ?? null}
          rows={buckets.to_review}
          t={t}
        />
        <SummaryCard
          testId="coverage-summary-blocked"
          title={t("summaryStays")}
          share={shares?.stays ?? null}
          rows={buckets.stays}
          t={t}
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground" data-testid="coverage-summary-weight-note">
          {candidates === 0
            ? t("weightNoteNoCandidates")
            : shares
              ? t("weightNoteReady", { unestimated: coverage.hours.unestimated })
              : unestimated > 0
                ? t("weightNotePending", { count: unestimated })
                : t("weightNoteShort")}
        </p>
        {canEdit && candidates > 0 && (
          <Button variant="outline" onClick={() => setWizardOpen(true)} data-testid="coverage-btn-weights">
            <Scale className="size-4" />
            {t("setWeights")}
          </Button>
        )}
      </div>

      <ol className="space-y-3" data-testid="coverage-match-list">
        {coverage.steps.map((row) => (
          <MatchRow
            key={row.step_id}
            row={row}
            candidate={coverage.candidate_step_ids.includes(row.step_id)}
            canEdit={canEdit}
            canOpenHireNeed={canOpenHireNeed}
            canRegisterAgent={canRegisterAgent}
            packLabel={packLabel}
            capabilityLabel={capabilityLabel}
            t={t}
            onSkill={() => setSkillStep(row)}
            onHire={() => setHireStep(row)}
            onAssign={(field) => setAssign({ row, field })}
            onChanged={load}
          />
        ))}
      </ol>

      {wizardOpen && (
        <HoursEditor
          steps={steps.filter((s) => coverage.candidate_step_ids.includes(s.id))}
          t={t}
          onClose={() => setWizardOpen(false)}
          onSaved={(updated, keepOpen) => {
            onStepsChanged((prev) => prev.map((s) => updated.get(s.id) ?? s));
            if (!keepOpen) setWizardOpen(false);
            void load();
          }}
        />
      )}

      {assign && (
        <AssignPersonDialog
          containerId={containerId}
          stepId={assign.row.step_id}
          field={assign.field}
          // The stored id, not the coverage row: coverage hides a terminated
          // assignee, and the assignment must still be removable.
          currentId={steps.find((s) => s.id === assign.row.step_id)?.[assign.field] ?? null}
          onClose={() => setAssign(null)}
          onSaved={(step) => {
            onStepsChanged((prev) => prev.map((s) => (s.id === step.id ? step : s)));
            void load();
          }}
        />
      )}

      {hireStep && (
        <HireFromStepDialog
          containerId={containerId}
          stepId={hireStep.step_id}
          title={hireStep.title}
          onClose={() => setHireStep(null)}
          onCreated={load}
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
    </div>
  );
}

function SummaryCard({
  testId,
  title,
  share,
  rows,
  t,
}: {
  testId: string;
  title: string;
  share: number | null;
  rows: CoverageStep[];
  t: Translate;
}) {
  return (
    <div className="rounded-lg border p-4" data-testid={testId} data-share={share ?? ""}>
      <p className="text-sm text-muted-foreground">{title}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">
        {share === null ? t("summaryCount", { count: rows.length }) : `${Math.round(share)}%`}
      </p>
      {rows.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-sm">
          {rows.map((r) => (
            <li key={r.step_id} className="truncate">
              {r.position}. {r.title}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MatchRow({
  row,
  candidate,
  canEdit,
  canOpenHireNeed,
  canRegisterAgent,
  packLabel,
  capabilityLabel,
  t,
  onSkill,
  onHire,
  onAssign,
  onChanged,
}: {
  row: CoverageStep;
  /** The backend's list of candidate steps: the ones a skill applies to. */
  candidate: boolean;
  canEdit: boolean;
  canOpenHireNeed: boolean;
  canRegisterAgent: boolean;
  packLabel: (code: string | null) => string;
  capabilityLabel: (code: string) => string;
  t: Translate;
  onSkill: () => void;
  onHire: () => void;
  onAssign: (field: AssigneeField) => void;
  onChanged: () => void;
}) {
  const testId = `coverage-match-row-${row.step_id}`;
  const canHaveSkill = candidate;
  // HRP-809: a person the company named outranks the match.
  const assigned = row.human?.label === "assigned" ? row.human : null;

  const skillLabel =
    row.skill_status === "ready"
      ? t("openSkill")
      : row.skill_status === "failed"
        ? t("retrySkill")
        : row.skill_status === "generating"
          ? t("generatingSkill")
          : t("getSkill");

  return (
    <li data-testid={testId} className="rounded-lg border bg-background p-3">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 w-6 shrink-0 text-sm tabular-nums text-muted-foreground">
          {row.position}
        </span>
        <div className="flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-medium">{row.title}</p>
            <Badge
              className={VERDICT_COLOR[row.verdict]}
              data-testid={`coverage-verdict-${row.step_id}`}
              data-verdict={row.verdict}
            >
              {t(`verdict_${row.verdict}`)}
            </Badge>
            {row.mode && (
              <Badge className={MODE_COLOR[row.mode]} data-testid={`coverage-mode-${row.step_id}`}>
                {t(`mode_${row.mode}`)}
              </Badge>
            )}
            {row.quality && (
              <Badge
                className={QUALITY_BADGE[row.quality]}
                data-testid={`coverage-quality-${row.step_id}`}
                data-quality={row.quality}
              >
                {t(`quality_${row.quality}`)}
              </Badge>
            )}
            {row.tentative && (
              <Badge
                variant="outline"
                className="border-dashed text-muted-foreground"
                title={t("tentativeVerdictHint")}
                data-testid={`coverage-tentative-${row.step_id}`}
              >
                {t("tentativeVerdict")}
              </Badge>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
            {row.agent && !assigned && (
              <span className="inline-flex items-center gap-1" data-testid={`coverage-agent-${row.step_id}`}>
                <Bot className="size-4" />
                {packLabel(row.agent.pack_code)}
                {row.agent.agent_name && ` ${t("agentVia", { name: row.agent.agent_name })}`}
              </span>
            )}
            {assigned && (
              <span className="inline-flex flex-wrap items-center gap-1" data-testid={`coverage-executor-${row.step_id}`}>
                <UserRound className="size-4" />
                {assigned.name}
                {assigned.position && (
                  <span className="text-xs">{t("humanPosition", { position: assigned.position })}</span>
                )}
                <Badge variant="outline">{t("humanLabel_assigned")}</Badge>
                {assigned.missing_codes.length > 0 && (
                  <Badge
                    className={BADGE_COLOR.amber}
                    title={t("noMatchingSkillsHint", {
                      capabilities: assigned.missing_codes.map(capabilityLabel).join(", "),
                    })}
                    data-testid={`coverage-executor-unmatched-${row.step_id}`}
                  >
                    {t("noMatchingSkills")}
                  </Badge>
                )}
              </span>
            )}
            {assigned && row.agent && (
              <span className="inline-flex items-center gap-1 text-xs" data-testid={`coverage-agent-${row.step_id}`}>
                <Bot className="size-3.5" />
                {t("agentCouldTake", { pack: packLabel(row.agent.pack_code) })}
              </span>
            )}
            {row.human && !assigned && (
              <span className="inline-flex items-center gap-1" data-testid={`coverage-human-${row.step_id}`}>
                <UserRound className="size-4" />
                {row.human_backup ? t("backupPerson", { name: row.human.name }) : row.human.name}
                {row.human.position && (
                  <span className="text-xs" data-testid={`coverage-human-position-${row.step_id}`}>
                    {t("humanPosition", { position: row.human.position })}
                  </span>
                )}
                <Badge variant="outline">{t(`humanLabel_${row.human.label}`)}</Badge>
              </span>
            )}
            {!row.agent && row.mode && CANDIDATE_MODES.includes(row.mode) && (
              <span className="text-xs" data-testid={`coverage-pack-gap-${row.step_id}`}>
                {t("noSinglePackHint")}
              </span>
            )}
            {row.verdict === "gap" && row.gap_label && (
              <span className="inline-flex items-center gap-1">
                <User className="size-4" />
                {t("gapVerdictText", { label: t(`gapLabel_${row.gap_label}`) })}
                {/* Already handed over: link to the draft rather than
                    offer a second vacancy for the same step. */}
                {row.hire_need?.vacancy_id ? (
                  <Link
                    href={`/recruitment/requisitions/${row.hire_need.vacancy_id}`}
                    className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline"
                    data-testid={`coverage-link-vacancy-${row.step_id}`}
                  >
                    <ExternalLink className="size-3.5" />
                    {t("openVacancy")}
                  </Link>
                ) : (
                  canOpenHireNeed && (
                    <Button
                      size="sm"
                      variant="link"
                      className="h-auto p-0"
                      onClick={onHire}
                      data-testid={`coverage-btn-hire-${row.step_id}`}
                    >
                      {t("openHireNeedOne")}
                    </Button>
                  )
                )}
              </span>
            )}
            {row.verdict === "out_of_scope" && (
              <span>
                {row.mode === "blocked_physical"
                  ? t("outOfScopePhysical")
                  : t("outOfScopeAccountability")}
              </span>
            )}
            {canEdit && (
              <Button
                size="sm"
                variant="link"
                className="h-auto p-0"
                onClick={() => onAssign("executor_employee_id")}
                data-testid={`coverage-btn-assign-executor-${row.step_id}`}
              >
                {assigned ? t("changeExecutor") : t("assignExecutor")}
              </Button>
            )}
          </div>

          <AccountableLine row={row} canEdit={canEdit} t={t} onAssign={() => onAssign("accountable_employee_id")} />

          {canRegisterAgent && !assigned && row.agent?.pack_id && !row.agent.agent_id && (
            <RegisterAgentInline
              packId={row.agent.pack_id}
              testId={`coverage-btn-use-agent-${row.step_id}`}
              onRegistered={onChanged}
            />
          )}
        </div>

        {canHaveSkill && (
          <div className="flex shrink-0 flex-col items-end gap-1">
            <Button
              size="sm"
              variant={row.skill_status === "ready" ? "outline" : "default"}
              disabled={row.skill_status === "generating" || (!canEdit && row.skill_status !== "ready")}
              title={!canEdit && row.skill_status !== "ready" ? t("skillReadOnlyHint") : undefined}
              onClick={onSkill}
              data-testid={`coverage-btn-get-skill-${row.step_id}`}
            >
              <FileText className="size-4" />
              {skillLabel}
              {row.skill_status !== "ready" && canEdit && <EECreditCostBadge action={SKILL_ACTION} />}
            </Button>
            {/* The person is redacted for a reader who may not see people;
                the verdict stays "human", so the hint has no name to give. */}
            {row.verdict === "human" && !assigned && row.human && row.skill_status === "none" && (
              <span className="text-xs text-muted-foreground" data-testid={`coverage-skill-hint-${row.step_id}`}>
                {t("skillHumanHint", { name: row.human.name })}
              </span>
            )}
            <span
              className="text-xs text-muted-foreground"
              data-testid={`coverage-skill-status-${row.step_id}`}
              data-status={row.skill_status}
            >
              {t(`skillStatus_${row.skill_status}`)}
            </span>
          </div>
        )}
      </div>
    </li>
  );
}

/** HRP-809: who checks and signs the step - named, asked for where an
 * agent drafts or somebody answers for the step, or offered quietly. */
function AccountableLine({
  row,
  canEdit,
  t,
  onAssign,
}: {
  row: CoverageStep;
  canEdit: boolean;
  t: Translate;
  onAssign: () => void;
}) {
  if (!row.accountable && !row.needs_accountable && !canEdit) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
      {row.accountable && (
        <span className="inline-flex items-center gap-1" data-testid={`coverage-accountable-${row.step_id}`}>
          <ShieldCheck className="size-4" />
          {t("accountablePerson", { name: row.accountable.name })}
          {row.accountable.position && (
            <span className="text-xs">{t("humanPosition", { position: row.accountable.position })}</span>
          )}
        </span>
      )}
      {canEdit ? (
        <Button
          size="sm"
          variant="outline"
          className={`h-7 ${row.needs_accountable ? BADGE_OUTLINE.amber : ""}`}
          title={row.needs_accountable ? t("whoChecksHint") : undefined}
          onClick={onAssign}
          data-testid={`coverage-btn-assign-accountable-${row.step_id}`}
          data-needs={row.needs_accountable || undefined}
        >
          {!row.accountable && <ShieldCheck className="size-4" />}
          {row.accountable ? t("changeExecutor") : t("whoChecks")}
        </Button>
      ) : (
        row.needs_accountable && (
          <Badge
            className={BADGE_COLOR.amber}
            title={t("whoChecksHint")}
            data-testid={`coverage-needs-accountable-${row.step_id}`}
          >
            {t("whoChecks")}
          </Badge>
        )
      )}
    </div>
  );
}

function HoursEditor({
  steps,
  t,
  onClose,
  onSaved,
}: {
  steps: WorkStep[];
  t: Translate;
  onClose: () => void;
  onSaved: (updated: Map<string, WorkStep>, keepOpen?: boolean) => void;
}) {
  const [values, setValues] = useState<Record<string, HoursDraft>>(() =>
    Object.fromEntries(steps.map((s) => [s.id, draftOf(s)])),
  );
  const [saving, setSaving] = useState(false);
  // A step that joins the candidate list while the dialog is open has no
  // draft yet: fall back to its own estimate, never to an empty one, or
  // saving would PATCH null over it.
  const valueOf = (step: WorkStep) => values[step.id] ?? draftOf(step);

  async function save() {
    // Out of range is answered by the backend with a 422 per row: say it
    // once here instead, and send nothing.
    if (steps.some((s) => hoursOutOfRange(valueOf(s)))) {
      toast.error(
        t("hoursRangeError", {
          minHours: HOURS_PER_RUN_MIN,
          maxHours: HOURS_PER_RUN_MAX,
          maxRuns: RUNS_PER_YEAR_MAX,
        }),
      );
      return;
    }
    setSaving(true);
    const updated = new Map<string, WorkStep>();
    try {
      for (const step of steps) {
        const next = parseHours(valueOf(step));
        if (next.hours_per_run === step.hours_per_run && next.runs_per_year === step.runs_per_year) continue;
        updated.set(step.id, await workApi.updateStep(step.id, next));
      }
      onSaved(updated);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
      // Keep what did save: a retry must not patch (and pay for) it again.
      // The dialog stays open — the rows that did not save are still typed in.
      if (updated.size > 0) onSaved(updated, true);
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-2xl" data-testid="coverage-weights-wizard">
        <DialogHeader>
          <DialogTitle>{t("weightsTitle")}</DialogTitle>
          <DialogDescription>{t("weightsText")}</DialogDescription>
        </DialogHeader>
        <ol className="max-h-[60vh] space-y-3 overflow-auto">
          {steps.map((step) => (
            <li
              key={step.id}
              className="space-y-2 rounded-md border p-2"
              data-testid={`coverage-weights-step-${step.id}`}
            >
              <span className="block truncate text-sm" title={`${step.position}. ${step.title}`}>
                {step.position}. {step.title}
              </span>
              <div className="flex flex-wrap gap-2">
                <HoursFields
                  value={valueOf(step)}
                  testId={`coverage-weights-step-${step.id}`}
                  labels={{ hours: t("attrHoursPerRun"), runs: t("attrRunsPerYear") }}
                  onChange={(next) => setValues((prev) => ({ ...prev, [step.id]: next }))}
                />
              </div>
            </li>
          ))}
        </ol>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button disabled={saving} onClick={save} data-testid="coverage-btn-weights-save">
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
