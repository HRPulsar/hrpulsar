"use client";

// HRP-866 (W6-10): the agent setup guide of a work container. A verdict and
// a SKILL.md per step are nine local answers; the question the company is
// left with is one - which agents to set up for this work, in what order,
// and what to do with the files. The section answers it by AGENT TYPE, not
// by step: the number of distinct packs is the number of agents to set up.
//
// Nothing is fetched: the groups are folded on the client from the coverage
// the tab already holds. The actions are the existing ones - the inline
// agent registration and the step's skill dialog - plus one download of
// everything that is ready.

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";
import { Bot, Download, FileText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MODE_COLOR } from "@/components/coverage/gaps-tab";
import { RegisterAgentInline } from "@/components/coverage/register-agent-inline";
import { EECreditCostBadge } from "@/lib/ee-hooks";
import { CANDIDATE_MODES, type CoverageStep, SKILL_ACTION, type SkillStatus, workApi } from "@/lib/api/work";

type Translate = (key: string) => string;

/** The skill button's label, on the coverage row and in the guide alike. */
export function skillLabel(t: Translate, status: SkillStatus): string {
  if (status === "ready") return t("openSkill");
  if (status === "failed") return t("retrySkill");
  if (status === "generating") return t("generatingSkill");
  return t("getSkill");
}

export const BUNDLE_FILE_NAME = "agent-skills.zip";

export interface AgentGroup {
  packCode: string;
  packId: string | null;
  /** The registered agents covering the group's steps, by name. */
  agentNames: string[];
  steps: CoverageStep[];
  /** Yearly hours the group frees - an estimated step's hours, less
   * what its checker keeps when the step goes to review. */
  hours: number;
  ready: number;
}

/** The steps an agent takes, grouped by agent type. A step is in when its
 * verdict is `agent` - an agent type covers it and the company named no
 * person to do it - and its mode is one an agent produces work in. Largest
 * yearly hours first; the first step's position settles a tie.
 * `backend/app/modules/work/bundle.py::agent_groups` is the same rule, so
 * the downloaded README lists what this section shows. */
/** HRP-861: the yearly hours a step takes off people - all of them for a
 * step an agent does alone, less the share its checker keeps when it goes
 * to review. `coverage.freed_hours` on the backend is the same formula. */
function freedHours(step: CoverageStep): number {
  const hours = step.hours_per_year ?? 0;
  return step.review_human_share === null ? hours : hours * (1 - step.review_human_share / 100);
}

export function agentGroups(steps: CoverageStep[]): AgentGroup[] {
  const groups = new Map<string, AgentGroup>();
  for (const step of [...steps].sort((a, b) => a.position - b.position)) {
    const code = step.agent?.pack_code;
    if (step.verdict !== "agent" || !code || !step.mode || !CANDIDATE_MODES.includes(step.mode)) {
      continue;
    }
    let group = groups.get(code);
    if (!group) {
      group = { packCode: code, packId: null, agentNames: [], steps: [], hours: 0, ready: 0 };
      groups.set(code, group);
    }
    group.steps.push(step);
    group.hours += freedHours(step);
    group.packId ??= step.agent?.pack_id ?? null;
    if (step.skill_status === "ready") group.ready += 1;
    const name = step.agent?.agent_name;
    if (name && !group.agentNames.includes(name)) group.agentNames.push(name);
  }
  return [...groups.values()].sort(
    (a, b) => b.hours - a.hours || a.steps[0].position - b.steps[0].position,
  );
}

interface AgentGuideProps {
  containerId: string;
  steps: CoverageStep[];
  canEdit: boolean;
  canRegisterAgent: boolean;
  packLabel: (code: string | null) => string;
  /** Opens the step's skill dialog - the tab owns it. */
  onSkill: (step: CoverageStep) => void;
  onChanged: () => void;
}

export function AgentGuide({
  containerId,
  steps,
  canEdit,
  canRegisterAgent,
  packLabel,
  onSkill,
  onChanged,
}: AgentGuideProps) {
  const t = useTranslations("coverage");
  const locale = useLocale();
  const [downloading, setDownloading] = useState(false);
  const groups = agentGroups(steps);
  // No step for an agent, no section: an empty frame answers nothing.
  if (groups.length === 0) return null;

  const ready = groups.reduce((sum, g) => sum + g.ready, 0);

  async function downloadAll() {
    setDownloading(true);
    try {
      const blob = await workApi.downloadAgentBundle(containerId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = BUNDLE_FILE_NAME;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setDownloading(false);
    }
  }

  return (
    // The ids read `coverage-guide-*`, not `coverage-agent-guide-*`: the
    // latter falls under the row chip's `[data-testid^="coverage-agent-"]`
    // in coverage.spec.ts, and a `.first()` there would pin this section
    // instead of the chip it means to assert.
    <section className="space-y-4 rounded-lg border p-4" data-testid="coverage-guide">
      <div className="space-y-1">
        <h3 className="font-medium" data-testid="coverage-guide-title">
          {t("agentGuideTitle", { count: groups.length })}
        </h3>
        <p className="max-w-3xl text-sm text-muted-foreground">{t("agentGuideText")}</p>
      </div>

      <ol className="space-y-4">
        {groups.map((group, index) => {
          const testId = `coverage-guide-group-${group.packCode}`;
          return (
            <li
              key={group.packCode}
              className="space-y-2 border-t pt-4 first:border-t-0 first:pt-0"
              data-testid={testId}
              data-hours={group.hours}
            >
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <p className="inline-flex min-w-0 items-center gap-2 font-medium">
                  <span className="tabular-nums text-muted-foreground">{index + 1}</span>
                  <Bot className="size-4 shrink-0" />
                  <span className="break-words">{packLabel(group.packCode)}</span>
                </p>
                <span className="text-sm tabular-nums text-muted-foreground" data-testid={`${testId}-hours`}>
                  {group.hours > 0
                    ? t("roiHours", { hours: Math.round(group.hours).toLocaleString(locale) })
                    : t("agentGuideHoursUnknown")}
                </span>
              </div>

              <p className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted-foreground">
                <span data-testid={`${testId}-agent`} data-registered={group.agentNames.length > 0}>
                  {group.agentNames.length > 0
                    ? t("agentGuideAgentRegistered", { name: group.agentNames.join(", ") })
                    : t("agentGuideAgentMissing")}
                </span>
                <span data-testid={`${testId}-skills`}>
                  {t("agentGuideSkills", { ready: group.ready, total: group.steps.length })}
                </span>
              </p>

              {canRegisterAgent && group.packId && group.agentNames.length === 0 && (
                <RegisterAgentInline
                  packId={group.packId}
                  testId={`${testId}-use-agent`}
                  onRegistered={onChanged}
                />
              )}

              <ul className="space-y-1.5">
                {group.steps.map((step) => (
                  <li
                    key={step.step_id}
                    className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm"
                  >
                    <span className="inline-flex min-w-0 flex-wrap items-center gap-2">
                      <span className="break-words">
                        {step.position}. {step.title}
                      </span>
                      {step.mode && <Badge className={MODE_COLOR[step.mode]}>{t(`mode_${step.mode}`)}</Badge>}
                    </span>
                    <Button
                      size="sm"
                      variant={step.skill_status === "ready" ? "outline" : "ghost"}
                      disabled={
                        step.skill_status === "generating" ||
                        (!canEdit && step.skill_status !== "ready")
                      }
                      title={
                        !canEdit && step.skill_status !== "ready" ? t("skillReadOnlyHint") : undefined
                      }
                      onClick={() => onSkill(step)}
                      data-testid={`coverage-guide-skill-${step.step_id}`}
                      data-status={step.skill_status}
                    >
                      <FileText className="size-3.5" />
                      {skillLabel(t, step.skill_status)}
                      {step.skill_status !== "ready" && canEdit && (
                        <EECreditCostBadge action={SKILL_ACTION} />
                      )}
                    </Button>
                  </li>
                ))}
              </ul>
            </li>
          );
        })}
      </ol>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t pt-4">
        <Button
          variant="outline"
          disabled={ready === 0 || downloading}
          onClick={downloadAll}
          data-testid="coverage-guide-download"
        >
          <Download className="size-4" />
          {t("agentGuideDownloadAll")}
        </Button>
        {/* A disabled button says why, in text rather than in a tooltip a
            touch screen never shows. */}
        <p className="min-w-0 flex-1 text-xs text-muted-foreground" data-testid="coverage-guide-download-hint">
          {ready === 0 ? t("agentGuideDownloadEmpty") : t("agentGuideDownloadHint")}
        </p>
      </div>
    </section>
  );
}
