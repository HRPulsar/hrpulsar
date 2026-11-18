"use client";

// HRP-1200: how a breakdown ends, in people rather than percentages - which
// steps an agent closes by itself, which it does while a person checks, and
// which people keep, with who checks and who does. The same buckets as the
// summary's shares (`bucketsOf`), so the two never count differently. The
// closing popup (HRP-1205) reads the same `outcomeOf`. A person the match
// found is not the person who does the step until the company assigns them:
// the people line keeps assigned, matched-not-assigned and nobody apart.

import { useTranslations } from "next-intl";
import { Bot, ShieldCheck, UserRound } from "lucide-react";

import { bucketsOf } from "@/components/coverage/coverage-summary";
import type { AssigneeField } from "@/components/coverage/assign-person-dialog";
import { PersonLink, StepJump } from "@/components/coverage/row-links";
import type { CoverageHuman, CoveragePerson, CoverageStep } from "@/lib/api/work";

/** Who does a step: the people the company assigned to it, by name - one or
 * several (HRP-1197). The one place it is read: the row, this block, the
 * closing popup and To do. */
export function stepExecutors(row: Pick<CoverageStep, "executors">): CoverageHuman[] {
  return row.executors;
}

/** Who the match found for a step nobody is assigned to: covers it by
 * capability, not confirmed as its executor. Beside `stepExecutors`, so the
 * two never overlap. A coverage row or a To do row (HRP-1198). */
export function stepMatches(row: { human?: CoverageStep["human"] }): CoveragePerson[] {
  return row.human && row.human.label !== "assigned" ? [row.human] : [];
}

export type PersonSteps = { person: CoveragePerson; steps: number };

export interface Outcome {
  /** An agent closes these by itself. */
  agentAlone: CoverageStep[];
  /** An agent does these and a person checks them. */
  agentChecked: CoverageStep[];
  /** Who checks `agentChecked`, most steps first. */
  checkers: PersonSteps[];
  /** `agentChecked` steps nobody is named to check. */
  unchecked: CoverageStep[];
  /** People do these. */
  people: CoverageStep[];
  /** Who is assigned to `people`, most steps first. */
  doers: PersonSteps[];
  /** Who the match found on `people` steps nobody is assigned to. */
  matched: PersonSteps[];
  /** `people` steps someone covers but nobody is assigned to - by a match,
   * named or hidden from this reader (HRP-810). */
  unassigned: CoverageStep[];
  /** `people` steps nobody covers at all. */
  nobody: CoverageStep[];
}

function tally(rows: CoverageStep[], of: (row: CoverageStep) => CoveragePerson[]): PersonSteps[] {
  const byId = new Map<string, PersonSteps>();
  for (const row of rows)
    for (const person of of(row)) {
      const seen = byId.get(person.employee_id) ?? { person, steps: 0 };
      seen.steps += 1;
      byId.set(person.employee_id, seen);
    }
  return [...byId.values()].sort((a, b) => b.steps - a.steps);
}

export function outcomeOf(steps: CoverageStep[]): Outcome {
  const buckets = bucketsOf(steps);
  const open = buckets.stays.filter((row) => stepExecutors(row).length === 0);
  return {
    agentAlone: buckets.moves,
    agentChecked: buckets.to_review,
    checkers: tally(buckets.to_review, (row) => (row.accountable ? [row.accountable] : [])),
    unchecked: buckets.to_review.filter((row) => !row.accountable),
    people: buckets.stays,
    doers: tally(buckets.stays, stepExecutors),
    matched: tally(open, stepMatches),
    unassigned: open.filter((row) => row.verdict !== "gap"),
    nobody: open.filter((row) => row.verdict === "gap"),
  };
}

type Translate = (key: string, values?: Record<string, string | number>) => string;

/** People with their step counts: "Anna Petrova · 3 steps, Ivan Roe · 1 step". */
export function PeopleList({ people, testId, t }: { people: PersonSteps[]; testId: string; t: Translate }) {
  return (
    <>
      {people.map(({ person, steps }, i) => (
        <span key={person.employee_id} className="inline-flex items-baseline gap-1">
          <PersonLink person={person} testId={`${testId}-${person.employee_id}`} />
          <span className="text-muted-foreground">
            · {t("summaryCount", { count: steps })}
            {i < people.length - 1 && ","}
          </span>
        </span>
      ))}
    </>
  );
}

/** Step titles behind a missing assignment. `onAssign` opens the step's
 * assign dialog for `field`; without it (a reader) a title scrolls to its row,
 * and with `linkSteps` off (the closing popup, over the page) it is text. */
function StepList({
  rows,
  field,
  actionTestId,
  stepTestId,
  onAssign,
  linkSteps,
  hint,
}: {
  rows: CoverageStep[];
  field: AssigneeField;
  /** The assign button's id prefix, and the plain or scrolling title's. */
  actionTestId: string;
  stepTestId: string;
  onAssign?: (row: CoverageStep, field: AssigneeField) => void;
  linkSteps: boolean;
  hint: string;
}) {
  return rows.map((row) =>
    !linkSteps ? (
      <span key={row.step_id} data-testid={`${stepTestId}-${row.step_id}`}>
        {row.position}. {row.title}
      </span>
    ) : onAssign ? (
      <button
        key={row.step_id}
        type="button"
        className="underline underline-offset-4 hover:no-underline"
        title={hint}
        onClick={() => onAssign(row, field)}
        data-testid={`${actionTestId}-${row.step_id}`}
      >
        {row.position}. {row.title}
      </button>
    ) : (
      <span key={row.step_id} className="max-w-64">
        <StepJump stepId={row.step_id} testId={`${stepTestId}-${row.step_id}`}>
          {row.position}. {row.title}
        </StepJump>
      </span>
    ),
  );
}

/** HRP-1200: the who-does / who-checks block under the summary. `onAssign`
 * opens "Who checks?" or the executor's Assign for a step that lacks one. */
export function CoverageOutcome({
  steps,
  onAssign,
  linkSteps = true,
}: {
  steps: CoverageStep[];
  onAssign?: (row: CoverageStep, field: AssigneeField) => void;
  linkSteps?: boolean;
}) {
  const t = useTranslations("coverage");
  const o = outcomeOf(steps);
  if (o.agentAlone.length + o.agentChecked.length + o.people.length === 0) return null;

  return (
    <section className="rounded-lg border p-4" data-testid="coverage-outcome">
      <h2 className="text-sm font-semibold">{t("outcomeTitle")}</h2>
      <ul className="mt-2 space-y-2 text-sm">
        <OutcomeLine
          testId="coverage-outcome-agent-alone"
          icon={<Bot className="size-4 text-muted-foreground" />}
          label={t("outcomeAgentAlone")}
          count={o.agentAlone.length}
          t={t}
        />
        <OutcomeLine
          testId="coverage-outcome-agent-checked"
          icon={<ShieldCheck className="size-4 text-muted-foreground" />}
          label={t("outcomeAgentChecked")}
          count={o.agentChecked.length}
          t={t}
        >
          {o.checkers.length > 0 && (
            <span className="inline-flex flex-wrap items-baseline gap-x-2" data-testid="coverage-outcome-checkers">
              <span className="text-muted-foreground">{t("outcomeCheckers")}</span>
              <PeopleList people={o.checkers} testId="coverage-outcome-checker" t={t} />
            </span>
          )}
          {o.unchecked.length > 0 && (
            <span
              className="inline-flex flex-wrap items-baseline gap-x-2 text-amber-700 dark:text-amber-400"
              data-testid="coverage-outcome-unchecked"
              data-count={o.unchecked.length}
            >
              {t("outcomeNoChecker", { count: o.unchecked.length })}
              <StepList
                rows={o.unchecked}
                field="accountable_employee_id"
                actionTestId="coverage-outcome-assign-checker"
                stepTestId="coverage-outcome-unchecked"
                onAssign={onAssign}
                linkSteps={linkSteps}
                hint={t("whoChecks")}
              />
            </span>
          )}
        </OutcomeLine>
        <OutcomeLine
          testId="coverage-outcome-people"
          icon={<UserRound className="size-4 text-muted-foreground" />}
          label={t("outcomePeople")}
          count={o.people.length}
          t={t}
        >
          {o.doers.length > 0 && (
            <span className="inline-flex flex-wrap items-baseline gap-x-2" data-testid="coverage-outcome-doers">
              <span className="text-muted-foreground">{t("outcomeDoers")}</span>
              <PeopleList people={o.doers} testId="coverage-outcome-doer" t={t} />
            </span>
          )}
          {o.matched.length > 0 && (
            <span className="inline-flex flex-wrap items-baseline gap-x-2" data-testid="coverage-outcome-matched">
              <span className="text-muted-foreground">{t("outcomeMatched", { count: o.matched.length })}</span>
              <PeopleList people={o.matched} testId="coverage-outcome-match" t={t} />
            </span>
          )}
          {o.unassigned.length > 0 && (
            <span
              className="inline-flex flex-wrap items-baseline gap-x-2 text-amber-700 dark:text-amber-400"
              data-testid="coverage-outcome-unassigned"
              data-count={o.unassigned.length}
            >
              {t("outcomeNoExecutor", { count: o.unassigned.length })}
              <StepList
                rows={o.unassigned}
                field="executor_employee_ids"
                actionTestId="coverage-outcome-assign-executor"
                stepTestId="coverage-outcome-unassigned"
                onAssign={onAssign}
                linkSteps={linkSteps}
                hint={t("assignExecutor")}
              />
            </span>
          )}
          {o.nobody.length > 0 && (
            <span className="text-amber-700 dark:text-amber-400" data-testid="coverage-outcome-nobody">
              {t("outcomeNobody", { count: o.nobody.length })}
            </span>
          )}
        </OutcomeLine>
      </ul>
    </section>
  );
}

function OutcomeLine({
  testId,
  icon,
  label,
  count,
  t,
  children,
}: {
  testId: string;
  icon: React.ReactNode;
  label: string;
  count: number;
  t: Translate;
  children?: React.ReactNode;
}) {
  return (
    <li className="flex items-start gap-2" data-testid={testId} data-count={count}>
      <span className="mt-0.5 shrink-0">{icon}</span>
      <div className="flex min-w-0 flex-col gap-0.5">
        <p>
          <span className="font-medium">{label}</span>{" "}
          <span className="text-muted-foreground tabular-nums">· {t("summaryCount", { count })}</span>
        </p>
        {count > 0 && children}
      </div>
    </li>
  );
}
