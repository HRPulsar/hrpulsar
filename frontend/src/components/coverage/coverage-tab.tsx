"use client";

// HRP-760: the Coverage tab of a work container — per step who covers it
// (an agent type, a person, nobody) and how far it can move to an agent,
// the three shares as yearly hours, the hours editor of the candidate
// steps, the SKILL.md of a step, and the inline "I already use this" that registers
// an agent for the matched pack. The word "primitive" never reaches the
// screen.

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";
import {
  Bot,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileText,
  ListChecks,
  Scale,
  ShieldCheck,
  User,
  UserRound,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmployeeSummaryLine } from "@/components/employee/employee-summary-line";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Hint } from "@/components/ui/hint";
import { LoadErrorState } from "@/components/load-error-state";
import { AgentGuide, skillLabel } from "@/components/coverage/agent-guide";
import { type AssigneeField, AssignPersonDialog } from "@/components/coverage/assign-person-dialog";
import { MODE_COLOR, useCapabilityLabel } from "@/components/coverage/gaps-tab";
import {
  CoverageSummary,
  QUALITY_BADGE,
  RATE_SETTINGS_HREF,
} from "@/components/coverage/coverage-summary";
import { HireFromStepDialog } from "@/components/coverage/hire-from-step-dialog";
import { MatchGroundsDrawer } from "@/components/coverage/match-grounds-drawer";
import {
  HOURS_PER_RUN_MIN,
  HoursFields,
  type HoursDraft,
  NumberField,
  STEP_RATE_MAX,
  STEP_RATE_MIN,
  draftOf,
  hoursOutOfRange,
  parseHours,
  parseRate,
  parseShare,
  rateOutOfRange,
  shareOutOfRange,
} from "@/components/coverage/hours-fields";
import { RegisterAgentInline } from "@/components/coverage/register-agent-inline";
import { PackChip, PersonLink, StepJump, around, stepRowId } from "@/components/coverage/row-links";
import { SkillDialog } from "@/components/coverage/skill-dialog";
import { StepOverrideMenu } from "@/components/coverage/step-override-menu";
import { BADGE_COLOR, BADGE_OUTLINE } from "@/lib/badge-tones";
import { EECreditCostBadge } from "@/lib/ee-hooks";
import {
  type AgentPack,
  CANDIDATE_MODES,
  type Coverage,
  type CoveragePerson,
  type CoverageStep,
  type Primitive,
  type StepPatch,
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

// HRP-863: what a step's mode can be set to by hand (models.AUTOMATION_MODES).
const AUTOMATION_MODES: AutomationMode[] = [...CANDIDATE_MODES, "blocked_judgment", "blocked_physical"];

const VERDICT_COLOR: Record<Verdict, string> = {
  agent: BADGE_COLOR.green,
  human: BADGE_COLOR.blue,
  gap: BADGE_COLOR.amber,
  out_of_scope: BADGE_COLOR.neutral,
  // HRP-944: typed in with no capabilities and never classified.
  unclassified: BADGE_COLOR.yellow,
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
  // HRP-871: the matched person whose grounds are open.
  const [groundsOf, setGroundsOf] = useState<NonNullable<CoverageStep["human"]> | null>(null);
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
  // HRP-863: fetched on the first open of a pack menu, not with the tab.
  const [packs, setPacks] = useState<AgentPack[] | null>(null);
  const loadPacks = useCallback(() => {
    // Nothing is cached on a failure: the list stays null, so the next open
    // of a menu asks again instead of showing "Loading..." for good.
    if (packs === null)
      void workApi
        .listPacks()
        .then(setPacks)
        .catch(() => toast.error(tc("loadFailed")));
  }, [packs, tc]);

  const load = useCallback(async () => {
    try {
      const fresh = await workApi.getCoverage(containerId);
      setCoverage(fresh);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [containerId]);

  // HRP-863: the company's override of a step's mode or pack. Like an
  // assignment: the steps tab gets the saved step, the summary is re-read.
  const override = useCallback(
    async (stepId: string, patch: StepPatch) => {
      try {
        const step = await workApi.updateStep(stepId, patch);
        onStepsChanged((prev) => prev.map((s) => (s.id === step.id ? step : s)));
        await load();
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t("saveFailed"));
      }
    },
    [load, onStepsChanged, t],
  );

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
  // HRP-868: the hours editor lists every step in scope, not only the
  // candidates - hours, a review share and a rate belong to a step whoever
  // ends up doing it. A boundary step is outside the arithmetic and stays out.
  const inScopeIds = new Set(coverage.steps.filter((s) => s.in_scope).map((s) => s.step_id));
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
          hint={t("summaryToReviewHint")}
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
        {canEdit && inScopeIds.size > 0 && (
          <Button variant="outline" onClick={() => setWizardOpen(true)} data-testid="coverage-btn-weights">
            <Scale className="size-4" />
            {t("setWeights")}
          </Button>
        )}
      </div>

      <AgentGuide
        containerId={containerId}
        steps={coverage.steps}
        canEdit={canEdit}
        canRegisterAgent={canRegisterAgent}
        packLabel={packLabel}
        onSkill={setSkillStep}
        onChanged={load}
      />

      {/* HRP-866 REDO: headed like the agent guide above, so the two lists
          are told apart at a glance. */}
      <section className="space-y-3">
        <header className="flex items-center gap-2">
          <ListChecks className="size-5 text-sky-600" />
          <h2 className="text-lg font-semibold" data-testid="coverage-match-list-title">
            {t("matchListTitle")}
          </h2>
        </header>
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
              packs={packs}
              onLoadPacks={loadPacks}
              onOverride={(patch) => void override(row.step_id, patch)}
              onGrounds={() => setGroundsOf(row.human)}
            />
          ))}
        </ol>
      </section>

      {wizardOpen && (
        <HoursEditor
          steps={steps.filter((s) => inScopeIds.has(s.id))}
          coverage={coverage}
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

      {groundsOf && (
        <MatchGroundsDrawer human={groundsOf} capabilityLabel={capabilityLabel} onClose={() => setGroundsOf(null)} />
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
  hint,
  share,
  rows,
  t,
}: {
  testId: string;
  title: string;
  /** What the bucket means, when the label alone does not say it. */
  hint?: string;
  share: number | null;
  rows: CoverageStep[];
  t: Translate;
}) {
  return (
    <div className="rounded-lg border p-4" data-testid={testId} data-share={share ?? ""}>
      <p className="flex items-center gap-1 text-sm text-muted-foreground">
        {title}
        {hint && <Hint text={hint} />}
      </p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">
        {share === null ? t("summaryCount", { count: rows.length }) : `${Math.round(share)}%`}
      </p>
      {rows.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-sm">
          {rows.map((r) => (
            <li key={r.step_id} className="truncate">
              <StepJump stepId={r.step_id} testId={`${testId}-step-${r.step_id}`}>
                {r.position}. {r.title}
              </StepJump>
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
  packs,
  onLoadPacks,
  onOverride,
  onGrounds,
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
  /** HRP-863: the packs a step can be set to; null until first asked for. */
  packs: AgentPack[] | null;
  onLoadPacks: () => void;
  onOverride: (patch: StepPatch) => void;
  /** HRP-871: open what the human match stands on. */
  onGrounds: () => void;
}) {
  const tc = useTranslations("common");
  const testId = `coverage-match-row-${row.step_id}`;
  // HRP-863: a step out of scope is in no bucket - nothing to override.
  // The agent type is only offered in a mode where an agent produces the
  // work: coverage ignores a pack named on a blocked step, so offering it
  // there would save a value nothing reads.
  const canOverride = canEdit && row.in_scope;
  // HRP-809: a person the company named outranks the match.
  const assigned = row.human?.label === "assigned" ? row.human : null;
  // HRP-863 (decision 2026-09-21): the company put the step in a bucket by
  // hand and has not named the agent yet. Until it does, the row keeps quiet:
  // no "nobody covers this" verdict against its word, and no quality light on
  // an agent nobody picked. Only where an agent can be named - in a candidate
  // mode, with no person assigned - or the row would stay silent for good
  // while To do lists the step.
  const awaitingAgent =
    Boolean(row.mode_manual) &&
    !!row.mode &&
    CANDIDATE_MODES.includes(row.mode) &&
    !assigned &&
    !row.agent?.agent_id &&
    !row.agent?.pack_manual;
  const canHaveSkill = candidate;

  return (
    <li
      data-testid={testId}
      id={stepRowId(row.step_id)}
      tabIndex={-1}
      className="rounded-lg border bg-background p-3 focus:outline-none focus:ring-2 focus:ring-ring"
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5 w-6 shrink-0 text-sm tabular-nums text-muted-foreground">
          {row.position}
        </span>
        <div className="flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-medium">{row.title}</p>
            {!awaitingAgent && (
              <Badge
                className={VERDICT_COLOR[row.verdict]}
                data-testid={`coverage-verdict-${row.step_id}`}
                data-verdict={row.verdict}
              >
                {t(`verdict_${row.verdict}`)}
              </Badge>
            )}
            {row.mode && !canOverride && (
              <Badge className={MODE_COLOR[row.mode]} data-testid={`coverage-mode-${row.step_id}`}>
                {t(`mode_${row.mode}`)}
              </Badge>
            )}
            {row.mode && canOverride && (
              <StepOverrideMenu
                testId={`coverage-btn-change-mode-${row.step_id}`}
                trigger={<button type="button" className="inline-flex" title={t("changeMode")} />}
                options={AUTOMATION_MODES.map((mode) => ({ value: mode, label: t(`mode_${mode}`) }))}
                value={row.mode}
                manual={row.mode_manual ?? false}
                resetLabel={t("manualReset")}
                emptyLabel={tc("loading")}
                onPick={(mode) => onOverride({ manual_mode: mode as AutomationMode | null })}
              >
                <Badge className={MODE_COLOR[row.mode]} data-testid={`coverage-mode-${row.step_id}`}>
                  {t(`mode_${row.mode}`)}
                  <ChevronDown className="size-3" />
                </Badge>
              </StepOverrideMenu>
            )}
            {row.quality && !awaitingAgent && (
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
                <PackChip
                  code={row.agent.pack_code}
                  label={packLabel(row.agent.pack_code)}
                  testId={`coverage-pack-chip-${row.step_id}`}
                />
                {row.agent.agent_name && ` ${t("agentVia", { name: row.agent.agent_name })}`}
              </span>
            )}
            {assigned && (
              <div className="inline-flex flex-wrap items-start gap-1" data-testid={`coverage-executor-${row.step_id}`}>
                <UserRound className="mt-0.5 size-4" />
                <PersonLine
                  sentence={(name) => t("executorPerson", { name })}
                  person={assigned}
                  testId={`coverage-link-executor-${row.step_id}`}
                />
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
              </div>
            )}
            {assigned && row.agent && (
              <span className="inline-flex items-center gap-1 text-xs" data-testid={`coverage-agent-${row.step_id}`}>
                <Bot className="size-3.5" />
                {around(
                  (pack) => t("agentCouldTake", { pack }),
                  <PackChip
                    code={row.agent.pack_code}
                    label={packLabel(row.agent.pack_code)}
                    testId={`coverage-pack-chip-${row.step_id}`}
                  />,
                )}
              </span>
            )}
            {row.human && !assigned && (
              <div className="inline-flex items-start gap-1" data-testid={`coverage-human-${row.step_id}`}>
                <UserRound className="mt-0.5 size-4" />
                <PersonLine
                  sentence={(name) => (row.human_backup ? t("backupPerson", { name }) : name)}
                  person={row.human}
                  testId={`coverage-link-human-${row.step_id}`}
                  summaryTestId={`coverage-human-summary-${row.step_id}`}
                />
                {/* After the position, not between it and the name (HRP-859 REDO). */}
                {row.human_backup && <Hint text={t("backupPersonHint")} />}
                {row.human.grounds?.length ? (
                  // HRP-871 REDO: a chip that opens a drawer says so with a
                  // chevron, the way a row that opens a detail does.
                  <button
                    type="button"
                    className="inline-flex rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    title={t("groundsOpenHint")}
                    onClick={onGrounds}
                    data-testid={`coverage-btn-grounds-${row.step_id}`}
                  >
                    <Badge variant="outline" className="cursor-pointer hover:bg-muted">
                      {t(`humanLabel_${row.human.label}`)}
                      <ChevronRight className="size-3" />
                    </Badge>
                  </button>
                ) : (
                  <Badge variant="outline">{t(`humanLabel_${row.human.label}`)}</Badge>
                )}
              </div>
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
            {row.verdict === "unclassified" && (
              <span data-testid={`coverage-unclassified-${row.step_id}`}>
                {/* A reader has no picker and no Reclassify button to be sent to. */}
                {t(canEdit ? "unclassifiedHint" : "unclassifiedReadOnly")}
              </span>
            )}
            {canOverride && row.mode && CANDIDATE_MODES.includes(row.mode) && (
              <StepOverrideMenu
                testId={`coverage-btn-change-pack-${row.step_id}`}
                trigger={<Button size="sm" variant="link" className="h-auto p-0" />}
                options={packs && packs.map((pack) => ({ value: pack.code, label: packLabel(pack.code) }))}
                value={row.agent?.pack_code ?? null}
                manual={row.agent?.pack_manual ?? false}
                resetLabel={t("manualReset")}
                emptyLabel={tc("loading")}
                onOpen={onLoadPacks}
                onPick={(code) => onOverride({ manual_pack_code: code })}
              >
                {row.agent ? t("changeAgent") : t("setAgent")}
              </StepOverrideMenu>
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
              {skillLabel(t, row.skill_status)}
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

/** HRP-859 REDO: a person on the row the way every other screen shows one -
 * the name, and under it the position in the shared EmployeeSummaryLine
 * (HRP-182). `sentence` gives the name its role ("Executor: {name}"). */
function PersonLine({
  sentence,
  person,
  testId,
  summaryTestId,
}: {
  sentence: (name: string) => string;
  person: CoveragePerson;
  testId: string;
  summaryTestId?: string;
}) {
  return (
    <div className="inline-flex min-w-0 flex-col">
      <span>{around(sentence, <PersonLink person={person} testId={testId} />)}</span>
      <EmployeeSummaryLine employee={{ position_title: person.position }} hideName data-testid={summaryTestId} />
    </div>
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
        <div className="inline-flex items-start gap-1" data-testid={`coverage-accountable-${row.step_id}`}>
          <ShieldCheck className="mt-0.5 size-4" />
          <PersonLine
            sentence={(name) => t("accountablePerson", { name })}
            person={row.accountable}
            testId={`coverage-link-accountable-${row.step_id}`}
          />
        </div>
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
            {t("needsAccountableBadge")}
          </Badge>
        )
      )}
    </div>
  );
}

function HoursEditor({
  steps,
  coverage,
  t,
  onClose,
  onSaved,
}: {
  steps: WorkStep[];
  /** HRP-861: which steps sit in the review bucket, and the share each one
   * effectively has - the step's own or the backend's default. */
  coverage: Coverage;
  t: Translate;
  onClose: () => void;
  onSaved: (updated: Map<string, WorkStep>, keepOpen?: boolean) => void;
}) {
  const [values, setValues] = useState<Record<string, HoursDraft>>(() =>
    Object.fromEntries(steps.map((s) => [s.id, draftOf(s)])),
  );
  const [saving, setSaving] = useState(false);
  // A step that comes into scope while the dialog is open has no draft yet:
  // fall back to its own estimate, never to an empty one, or saving would
  // PATCH null over it.
  const valueOf = (step: WorkStep) => values[step.id] ?? draftOf(step);

  // HRP-861: null for a step outside the review bucket - no share input.
  const effectiveShare = useMemo(
    () => new Map(coverage.steps.map((r) => [r.step_id, r.review_human_share])),
    [coverage],
  );
  const [shares, setShares] = useState<Record<string, string>>({});
  const shareOf = (step: WorkStep) =>
    shares[step.id] ?? String(effectiveShare.get(step.id) ?? "");
  const reviewed = steps.filter((s) => effectiveShare.get(s.id) != null);

  // HRP-868: a step's own hourly rate, in the company's currency; empty
  // falls back to the company rate. HRP-859 REDO: the field is prefilled with
  // the rate the step is actually priced at, like the review share above, and
  // open without a company rate too - the money shows once the company names
  // its currency, and the summary card says so meanwhile.
  const locale = useLocale();
  const [rates, setRates] = useState<Record<string, string>>({});
  const companyRate = coverage.hourly_rate;
  const rateOf = (step: WorkStep) => {
    const effective = step.hourly_rate ?? companyRate;
    // A company rate of 0 is below a step's minimum: prefilled, it would
    // block Save, so the field stays empty and the step follows the company.
    return rates[step.id] ?? (effective ? String(effective) : "");
  };

  function patchOf(step: WorkStep): StepPatch {
    const patch: StepPatch = {};
    const next = parseHours(valueOf(step));
    if (next.hours_per_run !== step.hours_per_run) patch.hours_per_run = next.hours_per_run;
    if (next.runs_per_year !== step.runs_per_year) patch.runs_per_year = next.runs_per_year;
    const effective = effectiveShare.get(step.id);
    if (effective != null) {
      const share = parseShare(shareOf(step));
      // The prefilled default left as it was is not a choice: the step
      // keeps following the default instead of pinning today's number.
      if (share !== effective && share !== step.review_human_share) {
        patch.review_human_share = share;
      }
    }
    const rate = parseRate(rateOf(step));
    // The prefilled company rate left as it was keeps following the company.
    if (rate !== step.hourly_rate && !(step.hourly_rate === null && rate === companyRate)) {
      patch.hourly_rate = rate;
    }
    return patch;
  }

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
    if (reviewed.some((s) => shareOutOfRange(shareOf(s)))) {
      toast.error(t("reviewShareRangeError"));
      return;
    }
    if (steps.some((s) => rateOutOfRange(rateOf(s)))) {
      toast.error(
        t("stepRateRangeError", {
          min: STEP_RATE_MIN.toLocaleString(locale),
          max: STEP_RATE_MAX.toLocaleString(locale),
        }),
      );
      return;
    }
    setSaving(true);
    const updated = new Map<string, WorkStep>();
    try {
      for (const step of steps) {
        const patch = patchOf(step);
        if (Object.keys(patch).length === 0) continue;
        updated.set(step.id, await workApi.updateStep(step.id, patch));
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
          <DialogTitle>{t("hoursEditorTitle")}</DialogTitle>
          <DialogDescription>{t("weightsIntro")}</DialogDescription>
          {reviewed.length > 0 && (
            <p className="text-sm text-muted-foreground" data-testid="coverage-weights-review-share-hint">
              {t("weightsReviewShareNote", { share: coverage.review_human_share_default })}
            </p>
          )}
          {/* Which rate an untouched step is priced at, and where it is set:
              "set one" or "change", like the summary card (HRP-859 REDO). */}
          <p
            className="text-sm text-muted-foreground"
            data-testid={companyRate === null ? "coverage-weights-rate-unset" : "coverage-weights-rate-hint"}
          >
            {companyRate === null
              ? t("weightsRateUnset")
              : t("weightsRateNote", {
                  rate: companyRate.toLocaleString(locale, {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  }),
                  currency: coverage.hourly_rate_currency ?? "",
                })}{" "}
            <Link href={RATE_SETTINGS_HREF} className="text-primary underline-offset-4 hover:underline">
              {companyRate === null ? t("roiRateSet") : t("roiRateEdit")}
            </Link>
          </p>
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
                {effectiveShare.get(step.id) != null && (
                  <NumberField
                    label={t("attrReviewShare")}
                    value={shareOf(step)}
                    min={0}
                    max={100}
                    step={1}
                    disabled={false}
                    placeholder={String(coverage.review_human_share_default)}
                    testId={`coverage-weights-step-${step.id}-input-review-share`}
                    onChange={(raw) => setShares((prev) => ({ ...prev, [step.id]: raw }))}
                  />
                )}
                <NumberField
                  label={t("attrStepRate", { currency: coverage.hourly_rate_currency ?? "none" })}
                  value={rateOf(step)}
                  min={STEP_RATE_MIN}
                  max={STEP_RATE_MAX}
                  step="any"
                  disabled={false}
                  placeholder={companyRate === null ? undefined : String(companyRate)}
                  testId={`coverage-weights-step-${step.id}-input-rate`}
                  onChange={(raw) => setRates((prev) => ({ ...prev, [step.id]: raw }))}
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
